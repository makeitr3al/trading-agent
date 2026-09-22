#!/usr/bin/env python3
"""Market profitability screener over Propr-whitelisted Hyperliquid assets.

See CLAUDE.md — Market Profitability Screener.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.daily_universe import (  # noqa: E402
    BacktestSimConfig,
    fetch_merged_daily_candles,
    simulate_market_daily,
    stable_shard_market,
    write_trade_csv,
)
from backtest.metrics import RANKING_FORMULA  # noqa: E402
from backtest.propr_exchange_assets import (  # noqa: E402
    ExchangeAssetRow,
    fetch_exchange_assets,
    load_exchange_assets_from_file,
    resolve_propr_api_base,
    whitelisted_assets,
)
from backtest.screener import (  # noqa: E402
    ScreenerGateConfig,
    evaluate_market,
    render_report_md,
    sort_go_rows,
)
from broker.asset_registry import AssetRegistry  # noqa: E402
from config.strategy_config import build_strategy_config  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backtest_market_screener")

SUMMARY_FIELDS = [
    "rank",
    "market",
    "asset_type",
    "decision",
    "fail_reasons",
    "taker_bps",
    "fee_roundtrip_bps",
    "max_order_notional",
    "history_coverage",
    "n_bars",
    "start_ts",
    "end_ts",
    "n_trades",
    "n_trend_trades",
    "n_countertrend_trades",
    "net_pnl_trend",
    "net_pnl_countertrend",
    "win_rate",
    "gross_pnl",
    "fees_total",
    "slippage_total",
    "net_pnl",
    "return_pct",
    "max_drawdown_pct",
    "longest_dd_bars",
    "profit_factor",
    "expectancy",
    "sharpe_ann",
    "calmar",
    "active_years",
    "year_pass_rate",
    "recent_n_trades",
    "recent_net_pnl",
    "exit_reason_distribution",
    "skipped_reason",
]


def _parse_include(raw: str | None) -> set[str] | None:
    """None means all (including unclassified)."""
    if not raw or raw.strip().lower() == "all":
        return None
    parts = {p.strip().lower() for p in raw.split(",") if p.strip()}
    allowed = {"crypto", "builder_perp", "hip3", "unknown"}
    bad = parts - allowed
    if bad:
        raise SystemExit(f"Invalid --include types {bad}; allowed: {sorted(allowed)} or all")
    return parts


def _parse_shard(raw: str | None) -> tuple[int, int]:
    if not raw or not raw.strip():
        return (0, 1)
    parts = raw.strip().split("/")
    if len(parts) != 2:
        raise SystemExit("--shard must look like 0/8 (index/total)")
    a, b = int(parts[0]), int(parts[1])
    if b <= 0 or a < 0 or a >= b:
        raise SystemExit("Invalid --shard: need 0 <= index < total and total > 0")
    return (a, b)


def _classify(asset: str, registry: AssetRegistry | None) -> str:
    if registry is None:
        if asset.upper().startswith("XYZ:"):
            return "unknown"
        return "unknown"
    entry = registry.get(asset)
    if entry is not None:
        return entry.asset_type
    return "unknown"


def _fmt_cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if v != v:  # NaN
            return ""
        return v
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return v


def _row_from_eval(
    *,
    market: str,
    asset_type: str,
    asset_row: ExchangeAssetRow | None,
    fee_bps: float,
    eval_res,
) -> dict[str, Any]:
    m = eval_res.metrics
    row: dict[str, Any] = {k: "" for k in SUMMARY_FIELDS}
    for k in SUMMARY_FIELDS:
        if k in m:
            row[k] = _fmt_cell(m.get(k))
    row.update(
        {
            "rank": "",
            "market": market,
            "asset_type": asset_type,
            "decision": eval_res.decision,
            "fail_reasons": "|".join(eval_res.fail_reasons),
            "taker_bps": "" if asset_row is None or asset_row.taker_bps() is None else asset_row.taker_bps(),
            "fee_roundtrip_bps": fee_bps,
            "max_order_notional": "" if asset_row is None else (asset_row.max_order_notional_value or ""),
            "skipped_reason": m.get("skipped_reason", ""),
        }
    )
    return row


def _skipped_row(market: str, asset_type: str, reason: str, asset_row: ExchangeAssetRow | None = None) -> dict[str, Any]:
    row = {k: "" for k in SUMMARY_FIELDS}
    row.update(
        {
            "market": market,
            "asset_type": asset_type,
            "decision": "SKIPPED",
            "fail_reasons": reason,
            "skipped_reason": reason,
            "taker_bps": "" if asset_row is None or asset_row.taker_bps() is None else asset_row.taker_bps(),
            "max_order_notional": "" if asset_row is None else (asset_row.max_order_notional_value or ""),
            "n_trades": 0,
            "n_trend_trades": 0,
            "n_countertrend_trades": 0,
        }
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="Propr-whitelist market profitability screener (HL 1D).")
    ap.add_argument("--years", type=float, default=5.0)
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--slippage-bps", type=float, default=5.0)
    ap.add_argument(
        "--fee-roundtrip-bps",
        type=float,
        default=None,
        help="Override per-asset catalog fees (default: 2*taker from catalog)",
    )
    ap.add_argument("--optimistic-fills", action="store_true")
    ap.add_argument("--min-trades", type=int, default=8)
    ap.add_argument("--min-trades-recent", type=int, default=2)
    ap.add_argument("--max-dd-pct", type=float, default=35.0)
    ap.add_argument("--min-profit-factor", type=float, default=1.2)
    ap.add_argument("--min-year-pass-rate", type=float, default=0.5)
    ap.add_argument("--min-history-coverage", type=float, default=0.80)
    ap.add_argument("--include", type=str, default="all", help="crypto,builder_perp,hip3,unknown or all")
    ap.add_argument("--shard", type=str, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--sleep-ms", type=int, default=250)
    ap.add_argument("--refresh-data", action="store_true")
    ap.add_argument("--refresh-propr-assets", action="store_true")
    ap.add_argument("--cache-dir", type=Path, default=Path("artifacts/backtests/cache"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--registry-cache", type=Path, default=None)
    ap.add_argument("--risk-per-trade-pct", type=float, default=None)
    ap.add_argument("--propr-env", type=str, default=None, help="beta|prod (default PROPR_ENV or beta)")
    ap.add_argument("--propr-base-url", type=str, default=None)
    ap.add_argument(
        "--propr-assets-file",
        type=Path,
        default=None,
        help="Offline snapshot of exchange-assets JSON (required if no network)",
    )
    ap.add_argument("--write-trades", action="store_true", help="Write per-market trades.csv")
    args = ap.parse_args()

    shard_i, shard_n = _parse_shard(args.shard)
    include_types = _parse_include(args.include)
    propr_env = (args.propr_env or os.getenv("PROPR_ENV") or "beta").strip().lower()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or (PROJECT_ROOT / "artifacts" / "backtests" / f"screener_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog_cache = (
        PROJECT_ROOT / "artifacts" / "backtests" / f"propr_exchange_assets_{propr_env}.json"
    )

    if args.propr_assets_file is not None:
        asset_rows = load_exchange_assets_from_file(args.propr_assets_file)
        catalog_meta = {
            "url": str(args.propr_assets_file),
            "env": propr_env,
            "from_cache": False,
            "from_file": True,
            "fetched_at_utc": None,
            "n_assets": len(asset_rows),
            "n_whitelisted": sum(1 for r in asset_rows if r.is_whitelisted),
        }
    else:
        try:
            asset_rows, catalog_meta = fetch_exchange_assets(
                env=propr_env,
                base_url=args.propr_base_url,
                cache_path=catalog_cache,
                refresh=bool(args.refresh_propr_assets),
            )
        except Exception as exc:
            raise SystemExit(
                f"Failed to load Propr exchange-assets catalog: {exc}. "
                "Pass --propr-assets-file with a saved snapshot, or fix network/base URL."
            ) from exc

    whitelist = whitelisted_assets(asset_rows)
    whitelist = [r for r in whitelist if stable_shard_market(r.asset, shard_i, shard_n)]
    whitelist.sort(key=lambda r: r.asset.upper())

    registry: AssetRegistry | None
    try:
        registry = AssetRegistry(cache_path=args.registry_cache) if args.registry_cache else AssetRegistry()
        registry.ensure_fresh()
    except Exception as exc:
        logger.warning("Asset registry unavailable (%s); asset_type=unknown", exc)
        registry = None

    candidates: list[ExchangeAssetRow] = []
    for row in whitelist:
        atype = _classify(row.asset, registry)
        if include_types is not None and atype not in include_types:
            continue
        candidates.append(row)
    if args.limit is not None:
        candidates = candidates[: max(0, args.limit)]

    strat_overrides: dict = {}
    if args.risk_per_trade_pct is not None:
        strat_overrides["risk_per_trade_pct"] = args.risk_per_trade_pct
    strategy_cfg = build_strategy_config(**strat_overrides)

    gates = ScreenerGateConfig(
        min_trades=int(args.min_trades),
        min_trades_recent=int(args.min_trades_recent),
        max_dd_pct=float(args.max_dd_pct),
        min_profit_factor=float(args.min_profit_factor),
        min_year_pass_rate=float(args.min_year_pass_rate),
        min_history_coverage=float(args.min_history_coverage),
    )

    base = resolve_propr_api_base(env=propr_env, base_url=args.propr_base_url)
    run_meta = {
        "generated_at_utc": ts,
        "propr_env": propr_env,
        "catalog_url": catalog_meta.get("url") or f"{base}/exchange-assets/config/hyperliquid",
        "catalog_meta": catalog_meta,
        "years": args.years,
        "capital": args.capital,
        "slippage_bps": args.slippage_bps,
        "fee_rule": "2*taker from catalog unless --fee-roundtrip-bps set",
        "fee_roundtrip_bps_override": args.fee_roundtrip_bps,
        "compound": False,
        "optimistic_fills": bool(args.optimistic_fills),
        "gates": {
            "min_trades": gates.min_trades,
            "min_trades_recent": gates.min_trades_recent,
            "max_dd_pct": gates.max_dd_pct,
            "min_profit_factor": gates.min_profit_factor,
            "min_year_pass_rate": gates.min_year_pass_rate,
            "min_history_coverage": gates.min_history_coverage,
            "min_active_years": gates.min_active_years,
        },
        "ranking": RANKING_FORMULA,
        "include": "all" if include_types is None else sorted(include_types),
        "shard": f"{shard_i}/{shard_n}",
        "limit": args.limit,
        "n_whitelist": len(whitelisted_assets(asset_rows)),
        "n_candidates": len(candidates),
        "strategy_config": strategy_cfg.model_dump(),
        "assumptions": [
            "One continuous daily simulation per market (trend + countertrend via run_agent_cycle).",
            "Open position at end marked to market at last close (mtm_end).",
            "Fees default to 2*taker from Propr exchange-assets catalog; slippage default 5 bps.",
            "No compounding (sizing from initial capital) for cross-market comparability.",
            "HL 1D OHLC ≠ Propr fills; live trend often uses market brackets (extra slippage possible).",
            "No funding; no true intraday beyond daily OHLC.",
            "Survivorship: today's whitelist for the chosen PROPR_ENV; beta ≠ prod catalogs.",
            "Same strategy params for all markets; many markets → some random GOs — review shortlist manually.",
            "Sharpe includes flat days and is conservatively low for sparse trading.",
            "Recent-12m is a pass/fail gate only; ranking uses full-sample Calmar.",
        ],
    }
    (out_dir / "run.json").write_text(json.dumps(run_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    sleep_s = max(0.0, args.sleep_ms / 1000.0)
    summary_rows: list[dict[str, Any]] = []

    for row in candidates:
        coin = row.asset
        atype = _classify(coin, registry)
        fee_bps = (
            float(args.fee_roundtrip_bps)
            if args.fee_roundtrip_bps is not None
            else (row.fee_roundtrip_bps_from_taker() or 0.0)
        )
        logger.info("Screen %s (%s) fee_rt_bps=%.2f", coin, atype, fee_bps)
        try:
            candles = fetch_merged_daily_candles(
                coin,
                years=float(args.years),
                end_ms=end_ms,
                cache_root=args.cache_dir,
                refresh_data=bool(args.refresh_data),
                sleep_s=sleep_s,
            )
        except Exception as exc:
            logger.warning("Fetch failed %s: %s", coin, exc)
            summary_rows.append(_skipped_row(coin, atype, f"fetch_error:{exc!s}", row))
            continue

        if not candles:
            summary_rows.append(_skipped_row(coin, atype, "empty_candles", row))
            continue

        sim_cfg = BacktestSimConfig(
            strategy=strategy_cfg,
            initial_capital=float(args.capital),
            fee_roundtrip_bps=fee_bps,
            slippage_bps=float(args.slippage_bps),
            compound=False,
            optimistic_fills=bool(args.optimistic_fills),
            min_trades=gates.min_trades,
        )
        sim = simulate_market_daily(candles, market=coin, cfg=sim_cfg)
        eval_res = evaluate_market(
            market=coin,
            candles=candles,
            sim_result=sim,
            years=float(args.years),
            initial_capital=float(args.capital),
            fee_roundtrip_bps=fee_bps,
            slippage_bps=float(args.slippage_bps),
            gates=gates,
        )
        if args.write_trades and eval_res.trades:
            safe = coin.replace(":", "_").replace("/", "_")
            write_trade_csv(out_dir / safe / "trades.csv", eval_res.trades)

        summary_rows.append(
            _row_from_eval(
                market=coin,
                asset_type=atype,
                asset_row=row,
                fee_bps=fee_bps,
                eval_res=eval_res,
            )
        )

    summary_rows = sort_go_rows(summary_rows)

    summary_path = out_dir / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as sf:
        w = csv.DictWriter(sf, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in summary_rows:
            w.writerow({k: _fmt_cell(r.get(k)) for k in SUMMARY_FIELDS})

    shortlist = [r for r in summary_rows if r.get("decision") == "GO"]
    shortlist_path = out_dir / "shortlist.csv"
    with shortlist_path.open("w", newline="", encoding="utf-8") as sf:
        w = csv.DictWriter(sf, fieldnames=SUMMARY_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in shortlist:
            w.writerow({k: _fmt_cell(r.get(k)) for k in SUMMARY_FIELDS})

    report = render_report_md(rows=summary_rows, run_meta=run_meta)
    (out_dir / "report.md").write_text(report, encoding="utf-8")

    run_meta["n_go"] = len(shortlist)
    run_meta["n_summary_rows"] = len(summary_rows)
    (out_dir / "run.json").write_text(json.dumps(run_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    logger.info(
        "Done: %d markets, %d GO → %s",
        len(summary_rows),
        len(shortlist),
        out_dir,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

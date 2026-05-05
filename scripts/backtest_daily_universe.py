#!/usr/bin/env python3
"""Daily 1D Hyperliquid universe backtest (per-market capital). See CLAUDE.md."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from broker.asset_registry import AssetRegistry
from backtest.daily_universe import (
    BacktestSimConfig,
    build_universe,
    fetch_merged_daily_candles,
    simulate_market_daily,
    stable_shard_market,
    write_trade_csv,
)
from config.strategy_config import build_strategy_config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("backtest_daily_universe")

SUMMARY_FIELDS = [
    "market",
    "asset_type",
    "n_bars",
    "start_ts",
    "end_ts",
    "n_trades",
    "win_rate",
    "gross_pnl",
    "fees_total",
    "slippage_total",
    "net_pnl",
    "return_pct",
    "max_drawdown_pct",
    "longest_dd_bars",
    "profitable",
    "profitable_oos",
    "oos_net_pnl",
    "oos_n_trades",
    "exit_reason_distribution",
    "skipped_reason",
]


def _summary_row_from_result(entry, coin: str, res: dict) -> dict:
    row: dict[str, object] = {}
    for k in SUMMARY_FIELDS:
        if k == "asset_type":
            row[k] = entry.asset_type
        elif k == "exit_reason_distribution":
            row[k] = json.dumps(res.get("exit_reason_distribution") or {}, ensure_ascii=False)
        elif k == "profitable_oos":
            v = res.get("profitable_oos")
            row[k] = "" if v is None else str(bool(v))
        elif k == "oos_net_pnl":
            v = res.get("oos_net_pnl")
            row[k] = "" if v is None else float(v)
        elif k == "profitable":
            row[k] = str(bool(res.get("profitable", False)))
        else:
            val = res.get(k)
            if val is None:
                row[k] = ""
            elif isinstance(val, bool):
                row[k] = str(val)
            else:
                row[k] = val
    row["market"] = coin
    return row


def _summary_row_fetch_error(entry, coin: str, exc: Exception) -> dict:
    row = {k: "" for k in SUMMARY_FIELDS}
    row.update(
        {
            "market": coin,
            "asset_type": entry.asset_type,
            "skipped_reason": f"fetch_error:{exc!s}",
            "exit_reason_distribution": "{}",
            "profitable": "False",
            "profitable_oos": "",
            "oos_net_pnl": "",
            "n_bars": 0,
            "n_trades": 0,
            "oos_n_trades": 0,
            "longest_dd_bars": 0,
            "win_rate": 0.0,
            "gross_pnl": 0.0,
            "fees_total": 0.0,
            "slippage_total": 0.0,
            "net_pnl": 0.0,
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
        }
    )
    return row


def _parse_include(raw: str | None) -> set[str]:
    if not raw or raw.strip().lower() == "all":
        return {"crypto", "builder_perp", "hip3"}
    parts = {p.strip().lower() for p in raw.split(",") if p.strip()}
    allowed = {"crypto", "builder_perp", "hip3"}
    bad = parts - allowed
    if bad:
        raise SystemExit(f"Invalid --include types {bad}; allowed: {sorted(allowed)}")
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Hyperliquid 1D daily universe backtest (per market).")
    ap.add_argument("--years", type=float, default=3.0, help="Years of 1D history (approx bars = years*365+30)")
    ap.add_argument("--capital", type=float, default=10_000.0, help="Starting capital per market (USDC notional)")
    ap.add_argument("--fee-roundtrip-bps", type=float, default=0.0, help="Total round-trip fee in bps (split half entry/half exit notionals)")
    ap.add_argument("--slippage-bps", type=float, default=0.0, help="Slippage bps applied worsening each leg")
    ap.add_argument("--no-compound", action="store_true", help="Size each cycle from initial capital instead of current equity")
    ap.add_argument("--optimistic-fills", action="store_true", help="If SL and TP both touch same bar, take TP first (sensitivity)")
    ap.add_argument("--min-trades", type=int, default=5)
    ap.add_argument("--min-trades-oos", type=int, default=2)
    ap.add_argument("--oos-years", type=float, default=None, help="If set, compute OOS PnL over last N years")
    ap.add_argument("--max-dd-pct", type=float, default=None, help="If set, mark not-profitable when max drawdown exceeds this %%")
    ap.add_argument("--include", type=str, default="all", help="Comma list: crypto,builder_perp,hip3 or 'all'")
    ap.add_argument("--shard", type=str, default=None, help="index/total for stable sharding over markets")
    ap.add_argument("--limit", type=int, default=None, help="Max markets after shard filter")
    ap.add_argument("--sleep-ms", type=int, default=250, help="Sleep between HL REST chunk fetches")
    ap.add_argument("--refresh-data", action="store_true", help="Ignore local candle caches")
    ap.add_argument("--cache-dir", type=Path, default=Path("artifacts/backtests/cache"))
    ap.add_argument("--out", type=Path, default=None, help="Output directory (default artifacts/backtests/daily_universe_<UTC>)")
    ap.add_argument("--registry-cache", type=Path, default=None, help="Optional override path for asset_registry.json")
    ap.add_argument("--risk-per-trade-pct", type=float, default=None, help="Override StrategyConfig.risk_per_trade_pct")
    args = ap.parse_args()

    shard_i, shard_n = _parse_shard(args.shard)
    include_types = _parse_include(args.include)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or (PROJECT_ROOT / "artifacts" / "backtests" / f"daily_universe_{ts}")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "summary.csv"

    registry = AssetRegistry(cache_path=args.registry_cache) if args.registry_cache else AssetRegistry()
    registry.ensure_fresh()
    universe = build_universe(registry, include_types)
    universe = [a for a in universe if stable_shard_market(a.propr_asset, shard_i, shard_n)]
    if args.limit is not None:
        universe = universe[: max(0, args.limit)]

    strat_overrides: dict = {}
    if args.risk_per_trade_pct is not None:
        strat_overrides["risk_per_trade_pct"] = args.risk_per_trade_pct
    strategy_cfg = build_strategy_config(**strat_overrides)

    sim_cfg = BacktestSimConfig(
        strategy=strategy_cfg,
        initial_capital=float(args.capital),
        fee_roundtrip_bps=float(args.fee_roundtrip_bps),
        slippage_bps=float(args.slippage_bps),
        compound=not args.no_compound,
        optimistic_fills=bool(args.optimistic_fills),
        min_trades=int(args.min_trades),
        min_trades_oos=int(args.min_trades_oos),
        oos_years=float(args.oos_years) if args.oos_years is not None else None,
        max_dd_pct=float(args.max_dd_pct) if args.max_dd_pct is not None else None,
    )

    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    sleep_s = max(0.0, args.sleep_ms / 1000.0)

    run_meta = {
        "generated_at_utc": ts,
        "years": args.years,
        "capital": args.capital,
        "fee_roundtrip_bps": args.fee_roundtrip_bps,
        "slippage_bps": args.slippage_bps,
        "compound": not args.no_compound,
        "optimistic_fills": args.optimistic_fills,
        "min_trades": args.min_trades,
        "min_trades_oos": args.min_trades_oos,
        "oos_years": args.oos_years,
        "max_dd_pct": args.max_dd_pct,
        "include": sorted(include_types),
        "shard": f"{shard_i}/{shard_n}",
        "limit": args.limit,
        "strategy_config": strategy_cfg.model_dump(),
        "assumptions": [
            "Uses run_agent_cycle (pending fills) + intrabar SL/TP touches on daily OHLC.",
            "Strategy trend entries are BUY_STOP/SELL_STOP in code; live Propr uses bracket limits — see plan.",
            "Strategic exits modeled at bar close when cycle sets close_active_trade.",
        ],
    }
    (out_dir / "run.json").write_text(json.dumps(run_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rows_written = 0
    with summary_path.open("w", newline="", encoding="utf-8") as sf:
        w = csv.DictWriter(sf, fieldnames=SUMMARY_FIELDS)
        w.writeheader()

        for entry in universe:
            coin = entry.propr_asset
            safe = coin.replace(":", "_").replace("/", "_")
            logger.info("Market %s (%s)", coin, entry.asset_type)
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
                w.writerow(_summary_row_fetch_error(entry, coin, exc))
                rows_written += 1
                continue

            res = simulate_market_daily(candles, market=coin, cfg=sim_cfg)
            trades = res.pop("trades", [])
            if trades:
                write_trade_csv(out_dir / safe / "trades.csv", trades)

            w.writerow(_summary_row_from_result(entry, coin, res))
            rows_written += 1

    logger.info("Wrote %d rows to %s", rows_written, summary_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

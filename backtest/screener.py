"""Market profitability screener: end-MTM, yearly stability, GO/NO_GO gates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from backtest.daily_universe import TradeRecord, realize_pnl_for_closed_trade
from backtest.metrics import (
    RANKING_FORMULA,
    calmar_ratio,
    expectancy,
    profit_factor,
    ranking_key,
    sharpe_ann_from_equity,
)
from models.candle import Candle
from models.trade import Trade


def parse_exit_ts(ts: str) -> datetime:
    t = ts.replace("Z", "+00:00")
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class ScreenerGateConfig:
    min_trades: int = 8
    min_trades_recent: int = 2
    max_dd_pct: float = 35.0
    min_profit_factor: float = 1.2
    min_year_pass_rate: float = 0.5
    min_active_years: int = 2
    min_history_coverage: float = 0.80
    recent_days: int = 365


@dataclass
class ScreenerEvalResult:
    decision: str
    fail_reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    trades: list[TradeRecord] = field(default_factory=list)


def apply_end_mtm(
    *,
    market: str,
    trades: list[TradeRecord],
    open_trade: Trade | None,
    last_candle: Candle | None,
    equity: float,
    equity_curve: list[float],
    fee_roundtrip_bps: float,
    slippage_bps: float,
    exit_hist: dict[str, int] | None = None,
) -> tuple[list[TradeRecord], float, list[float], dict[str, int]]:
    """Close remaining open trade at last close; append mtm_end trade."""
    hist = dict(exit_hist or {})
    out_trades = list(trades)
    eq = float(equity)
    curve = list(equity_curve)

    if open_trade is None or last_candle is None:
        return out_trades, eq, curve, hist

    r = realize_pnl_for_closed_trade(
        open_trade,
        float(last_candle.close),
        fee_roundtrip_bps=fee_roundtrip_bps,
        slippage_bps=slippage_bps,
    )
    eq += float(r["net_pnl"])
    if curve:
        curve[-1] = eq
    else:
        curve.append(eq)
    hist["mtm_end"] = hist.get("mtm_end", 0) + 1
    out_trades.append(
        TradeRecord(
            market=market,
            entry_ts=open_trade.opened_at or "",
            entry_price=float(open_trade.entry),
            exit_ts=last_candle.timestamp.isoformat(),
            exit_price=float(last_candle.close),
            exit_reason="mtm_end",
            qty=float(open_trade.quantity or 0.0),
            direction=open_trade.direction.value,
            trade_type=open_trade.trade_type.value,
            gross_pnl=float(r["gross_pnl"]),
            fees=float(r["fees"]),
            slippage_cost=float(r["slippage_cost"]),
            net_pnl=float(r["net_pnl"]),
        )
    )
    return out_trades, eq, curve, hist


def history_coverage(candles: Sequence[Candle], years: float) -> float:
    if not candles or years <= 0:
        return 0.0
    span_days = (candles[-1].timestamp - candles[0].timestamp).total_seconds() / 86400.0
    target = float(years) * 365.25
    if target <= 0:
        return 0.0
    return min(1.0, span_days / target)


def yearly_stability(trades: Sequence[TradeRecord]) -> dict[str, Any]:
    by_year: dict[int, list[float]] = {}
    for t in trades:
        try:
            y = parse_exit_ts(t.exit_ts).year
        except Exception:
            continue
        by_year.setdefault(y, []).append(float(t.net_pnl))

    active_years = sorted(by_year.keys())
    year_results: dict[str, float] = {}
    pass_years = 0
    for y in active_years:
        net = sum(by_year[y])
        year_results[str(y)] = net
        if net > 0.0:
            pass_years += 1

    n_active = len(active_years)
    year_pass_rate = (pass_years / n_active) if n_active else None
    return {
        "active_years": n_active,
        "year_pass_rate": year_pass_rate,
        "year_net_pnl": year_results,
        "pass_years": pass_years,
    }


def recent_window_stats(
    trades: Sequence[TradeRecord],
    *,
    end_ts: datetime,
    recent_days: int,
) -> dict[str, Any]:
    cutoff = end_ts - timedelta(days=int(recent_days))
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    recent = []
    for t in trades:
        try:
            if parse_exit_ts(t.exit_ts) >= cutoff:
                recent.append(t)
        except Exception:
            continue
    net = sum(t.net_pnl for t in recent)
    return {
        "recent_n_trades": len(recent),
        "recent_net_pnl": net,
    }


def sleeve_breakdown(trades: Sequence[TradeRecord]) -> dict[str, Any]:
    trend = [t for t in trades if str(t.trade_type).upper() == "TREND"]
    ct = [t for t in trades if str(t.trade_type).upper() == "COUNTERTREND"]
    return {
        "n_trend_trades": len(trend),
        "n_countertrend_trades": len(ct),
        "net_pnl_trend": sum(t.net_pnl for t in trend),
        "net_pnl_countertrend": sum(t.net_pnl for t in ct),
    }


def recompute_drawdown_from_equity(equity_curve: Sequence[float]) -> tuple[float, int]:
    if not equity_curve:
        return 0.0, 0
    peak = float(equity_curve[0])
    max_dd = 0.0
    dd_run = 0
    longest = 0
    for eq in equity_curve:
        e = float(eq)
        if e >= peak:
            peak = e
            dd_run = 0
        else:
            dd = (peak - e) / peak * 100.0 if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
            dd_run += 1
            longest = max(longest, dd_run)
    return max_dd, longest


def evaluate_market(
    *,
    market: str,
    candles: list[Candle],
    sim_result: dict[str, Any],
    years: float,
    initial_capital: float,
    fee_roundtrip_bps: float,
    slippage_bps: float,
    gates: ScreenerGateConfig,
) -> ScreenerEvalResult:
    """Apply end-MTM and GO/NO_GO gates to one continuous simulation result."""
    if sim_result.get("skipped_reason"):
        return ScreenerEvalResult(
            decision="SKIPPED",
            fail_reasons=[str(sim_result["skipped_reason"])],
            metrics={"skipped_reason": sim_result["skipped_reason"]},
            trades=list(sim_result.get("trades") or []),
        )

    if not candles:
        return ScreenerEvalResult(
            decision="SKIPPED",
            fail_reasons=["empty_candles"],
            metrics={"skipped_reason": "empty_candles"},
        )

    coverage = history_coverage(candles, years)
    trades, equity, equity_curve, exit_hist = apply_end_mtm(
        market=market,
        trades=list(sim_result.get("trades") or []),
        open_trade=sim_result.get("open_trade"),
        last_candle=candles[-1],
        equity=float(sim_result.get("final_equity", initial_capital)),
        equity_curve=list(sim_result.get("equity_curve") or []),
        fee_roundtrip_bps=fee_roundtrip_bps,
        slippage_bps=slippage_bps,
        exit_hist=dict(sim_result.get("exit_reason_distribution") or {}),
    )

    max_dd, longest_dd = recompute_drawdown_from_equity(equity_curve)
    net_pnl = equity - float(initial_capital)
    ret_pct = (net_pnl / initial_capital) * 100.0 if initial_capital else 0.0
    pnls = [t.net_pnl for t in trades]
    n_trades = len(trades)
    winning = sum(1 for p in pnls if p > 0.0)
    win_rate = (winning / n_trades) * 100.0 if n_trades else 0.0
    pf = profit_factor(pnls)
    exp = expectancy(pnls)
    sharpe = sharpe_ann_from_equity(equity_curve)
    calmar = calmar_ratio(ret_pct, max_dd)
    yearly = yearly_stability(trades)
    recent = recent_window_stats(
        trades,
        end_ts=candles[-1].timestamp
        if candles[-1].timestamp.tzinfo
        else candles[-1].timestamp.replace(tzinfo=timezone.utc),
        recent_days=gates.recent_days,
    )
    sleeves = sleeve_breakdown(trades)

    metrics: dict[str, Any] = {
        "market": market,
        "n_bars": len(candles),
        "start_ts": candles[0].timestamp.isoformat(),
        "end_ts": candles[-1].timestamp.isoformat(),
        "history_coverage": coverage,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "gross_pnl": sum(t.gross_pnl for t in trades),
        "fees_total": sum(t.fees for t in trades),
        "slippage_total": sum(t.slippage_cost for t in trades),
        "net_pnl": net_pnl,
        "return_pct": ret_pct,
        "max_drawdown_pct": max_dd,
        "longest_dd_bars": longest_dd,
        "profit_factor": pf,
        "expectancy": exp,
        "sharpe_ann": sharpe,
        "calmar": calmar,
        "active_years": yearly["active_years"],
        "year_pass_rate": yearly["year_pass_rate"],
        "year_net_pnl": yearly["year_net_pnl"],
        "recent_n_trades": recent["recent_n_trades"],
        "recent_net_pnl": recent["recent_net_pnl"],
        "exit_reason_distribution": exit_hist,
        **sleeves,
    }

    insuff: list[str] = []
    if coverage < gates.min_history_coverage:
        insuff.append("insufficient_history_coverage")
    if n_trades < gates.min_trades:
        insuff.append("min_trades")
    if int(yearly["active_years"] or 0) < gates.min_active_years:
        insuff.append("min_active_years")
    if pf is None and n_trades >= gates.min_trades:
        insuff.append("profit_factor_undefined")

    if insuff:
        return ScreenerEvalResult(
            decision="INSUFFICIENT_DATA",
            fail_reasons=insuff,
            metrics=metrics,
            trades=trades,
        )

    fails: list[str] = []
    if net_pnl <= 0.0:
        fails.append("net_pnl")
    if max_dd > gates.max_dd_pct:
        fails.append("max_drawdown")
    if pf is None or pf < gates.min_profit_factor:
        fails.append("profit_factor")
    ypr = yearly["year_pass_rate"]
    if ypr is None or float(ypr) < gates.min_year_pass_rate:
        fails.append("year_pass_rate")
    if float(recent["recent_net_pnl"]) <= 0.0:
        fails.append("recent_net_pnl")
    if int(recent["recent_n_trades"]) < gates.min_trades_recent:
        fails.append("recent_n_trades")

    if fails:
        return ScreenerEvalResult(
            decision="NO_GO",
            fail_reasons=fails,
            metrics=metrics,
            trades=trades,
        )

    return ScreenerEvalResult(
        decision="GO",
        fail_reasons=[],
        metrics=metrics,
        trades=trades,
    )


def sort_go_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    go = [r for r in rows if str(r.get("decision")) == "GO"]
    rest = [r for r in rows if str(r.get("decision")) != "GO"]
    go_sorted = sorted(go, key=ranking_key, reverse=True)
    for i, r in enumerate(go_sorted, start=1):
        r["rank"] = i
    return go_sorted + rest


def render_report_md(
    *,
    rows: list[dict[str, Any]],
    run_meta: dict[str, Any],
    top_n: int = 20,
) -> str:
    n_tested = sum(1 for r in rows if r.get("decision") in {"GO", "NO_GO", "INSUFFICIENT_DATA"})
    n_go = sum(1 for r in rows if r.get("decision") == "GO")
    n_nogo = sum(1 for r in rows if r.get("decision") == "NO_GO")
    n_insuff = sum(1 for r in rows if r.get("decision") == "INSUFFICIENT_DATA")
    n_skip = sum(1 for r in rows if r.get("decision") == "SKIPPED")

    fail_counts: dict[str, int] = {}
    for r in rows:
        if r.get("decision") != "NO_GO":
            continue
        for reason in str(r.get("fail_reasons") or "").split("|"):
            reason = reason.strip()
            if reason:
                fail_counts[reason] = fail_counts.get(reason, 0) + 1

    lines: list[str] = []
    lines.append("# Market Profitability Screener Report")
    lines.append("")
    lines.append(f"- Catalog URL: `{run_meta.get('catalog_url', '')}`")
    lines.append(f"- Env: `{run_meta.get('propr_env', '')}`")
    lines.append(f"- Years: {run_meta.get('years')}")
    lines.append(f"- Ranking: `{RANKING_FORMULA}`")
    lines.append(f"- n_tested (with decision): **{n_tested}**")
    lines.append(f"- n_go: **{n_go}** | n_nogo: {n_nogo} | n_insufficient: {n_insuff} | n_skipped: {n_skip}")
    lines.append("")
    lines.append("## Caveats")
    for a in run_meta.get("assumptions") or []:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("## Top GO (by Calmar)")
    go_rows = [r for r in rows if r.get("decision") == "GO"]
    if not go_rows:
        lines.append("_No GO markets._")
    else:
        by_type: dict[str, list[dict]] = {}
        for r in go_rows:
            by_type.setdefault(str(r.get("asset_type") or "unknown"), []).append(r)
        for atype, group in sorted(by_type.items()):
            lines.append(f"### {atype}")
            lines.append("")
            lines.append("| rank | market | calmar | return_pct | max_dd | n_trades | trend | CT |")
            lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
            for r in group[:top_n]:
                lines.append(
                    "| {rank} | {market} | {calmar} | {ret} | {dd} | {n} | {nt}/{npt} | {nc}/{npc} |".format(
                        rank=r.get("rank", ""),
                        market=r.get("market", ""),
                        calmar=_fmt(r.get("calmar")),
                        ret=_fmt(r.get("return_pct")),
                        dd=_fmt(r.get("max_drawdown_pct")),
                        n=r.get("n_trades", ""),
                        nt=r.get("n_trend_trades", ""),
                        npt=_fmt(r.get("net_pnl_trend")),
                        nc=r.get("n_countertrend_trades", ""),
                        npc=_fmt(r.get("net_pnl_countertrend")),
                    )
                )
            lines.append("")

    lines.append("## Frequent NO_GO reasons")
    if not fail_counts:
        lines.append("_None._")
    else:
        for reason, cnt in sorted(fail_counts.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{reason}`: {cnt}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _fmt(v: Any) -> str:
    if v is None or v == "":
        return ""
    try:
        f = float(v)
        if math.isnan(f):
            return ""
        return f"{f:.2f}"
    except (TypeError, ValueError):
        return str(v)

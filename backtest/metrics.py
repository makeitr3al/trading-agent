"""Risk-adjusted metrics and ranking helpers for the market screener."""

from __future__ import annotations

import math
from typing import Sequence


def profit_factor(net_pnls: Sequence[float]) -> float | None:
    """Gross wins / abs(gross losses). None when there are no losing trades."""
    wins = sum(p for p in net_pnls if p > 0.0)
    losses = sum(p for p in net_pnls if p < 0.0)
    if losses == 0.0:
        return None
    return wins / abs(losses)


def expectancy(net_pnls: Sequence[float]) -> float | None:
    if not net_pnls:
        return None
    return sum(net_pnls) / len(net_pnls)


def sharpe_ann_from_equity(equity_curve: Sequence[float], *, periods_per_year: float = 365.0) -> float | None:
    """Annualized Sharpe from daily equity levels (includes flat days)."""
    if len(equity_curve) < 2:
        return None
    rets: list[float] = []
    for i in range(1, len(equity_curve)):
        prev = float(equity_curve[i - 1])
        cur = float(equity_curve[i])
        if prev <= 0.0:
            continue
        rets.append((cur - prev) / prev)
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    std = math.sqrt(var)
    if std <= 0.0 or math.isnan(std):
        return None
    return (mean / std) * math.sqrt(periods_per_year)


def calmar_ratio(return_pct: float, max_drawdown_pct: float) -> float:
    """Return% / max(DD%, 1). Always defined."""
    dd = max(float(max_drawdown_pct), 1.0)
    return float(return_pct) / dd


RANKING_FORMULA = "calmar desc, then return_pct desc, then n_trades desc"


def ranking_key(row: dict) -> tuple[float, float, int]:
    """Sort key for GO shortlist (higher is better; use with reverse=True)."""
    calmar = row.get("calmar")
    if calmar is None:
        calmar = float("-inf")
    ret = row.get("return_pct")
    if ret is None:
        ret = float("-inf")
    n = int(row.get("n_trades") or 0)
    return (float(calmar), float(ret), n)

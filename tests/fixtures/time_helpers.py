from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from models.candle import Candle


def _infer_candle_interval(candles: list[Candle], *, lookback: int = 20) -> timedelta | None:
    if len(candles) < 2:
        return None
    deltas_s: list[float] = []
    start = max(1, len(candles) - lookback)
    for i in range(start, len(candles)):
        dt = candles[i].timestamp - candles[i - 1].timestamp
        if dt.total_seconds() > 0:
            deltas_s.append(dt.total_seconds())
    if not deltas_s:
        return None
    return timedelta(seconds=float(median(deltas_s)))


def after_last_closed_bar(candles: list[Candle]) -> datetime:
    """Deterministic 'now' value ensuring the last candle is considered closed."""
    if not candles:
        return datetime.now(timezone.utc)
    interval = _infer_candle_interval(candles) or timedelta(seconds=0)
    ts = candles[-1].timestamp
    now = ts + interval + timedelta(seconds=1)
    if ts.tzinfo is None:
        return now.replace(tzinfo=None)
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)


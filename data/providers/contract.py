"""Data-batch contract for all :class:`CandleDataProvider` implementations.

**Candles**

- At least one bar after validation (empty series is rejected).
- When ``min_candles`` is set, ``len(candles) >= min_candles`` (indicator warmup; use
  :func:`config.strategy_config.min_strategy_candle_count` with the same
  :class:`~config.strategy_config.StrategyConfig` as the batch when present).
- Each ``Candle.timestamp`` is timezone-aware with UTC offset zero (normalized UTC;
  ``datetime`` may use ``datetime.timezone.utc`` or an equivalent fixed-offset UTC).
- Timestamps are strictly increasing (no duplicates, no backward steps).
- ``open``, ``high``, ``low``, ``close`` are finite floats (OHLC range rules remain on
  :class:`models.candle.Candle`).

**Batch metadata**

- ``source_name`` is a non-blank string.
- For ``source_name == "hyperliquid_historical"``, ``symbol`` must be a non-blank
  string (coin / instrument id for the snapshot).

Hyperliquid REST candle rows may use aliases ``time`` / ``t``, ``open`` / ``o``, etc.;
see ``HyperliquidHistoricalProvider._parse_candles`` — contract tests
should fail if required fields stop mapping to :class:`models.candle.Candle`.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from data.providers.base import DataBatch
from models.candle import Candle


def _is_utc_wall_time(ts: datetime) -> bool:
    if ts.tzinfo is None:
        return False
    offset = ts.utcoffset()
    return offset is not None and offset == timedelta(0)


def validate_data_batch(batch: DataBatch, *, min_candles: int | None = None) -> None:
    """Raise ``ValueError`` with a stable message if ``batch`` violates the provider contract."""
    name = (batch.source_name or "").strip()
    if not name:
        raise ValueError("data batch contract: source_name must be non-blank")

    candles = batch.candles
    if not candles:
        raise ValueError("data batch contract: candles must be non-empty")

    if min_candles is not None:
        if min_candles < 1:
            raise ValueError("data batch contract: min_candles must be >= 1 when set")
        if len(candles) < min_candles:
            raise ValueError(
                f"data batch contract: need at least {min_candles} candles, got {len(candles)}"
            )

    if name == "hyperliquid_historical":
        sym = (batch.symbol or "").strip() if batch.symbol is not None else ""
        if not sym:
            raise ValueError(
                "data batch contract: hyperliquid_historical batches require a non-blank symbol"
            )

    prev: Candle | None = None
    for c in candles:
        ts = c.timestamp
        if not _is_utc_wall_time(ts):
            raise ValueError(
                "data batch contract: each candle timestamp must be timezone-aware UTC "
                f"(got tzinfo={ts.tzinfo!r})"
            )
        for field_name in ("open", "high", "low", "close"):
            v = getattr(c, field_name)
            if not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                raise ValueError(
                    f"data batch contract: candle OHLC must be finite floats ({field_name}={v!r})"
                )
        if prev is not None and prev.timestamp >= c.timestamp:
            raise ValueError(
                "data batch contract: candle timestamps must be strictly increasing "
                f"({prev.timestamp!r} >= {c.timestamp!r})"
            )
        prev = c

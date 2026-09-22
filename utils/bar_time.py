"""UTC bar open/close helpers for Hyperliquid interval strings."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_INTERVAL_TO_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 3 * 60,
    "5m": 5 * 60,
    "15m": 15 * 60,
    "30m": 30 * 60,
    "1h": 60 * 60,
    "2h": 2 * 60 * 60,
    "4h": 4 * 60 * 60,
    "8h": 8 * 60 * 60,
    "12h": 12 * 60 * 60,
    "1d": 24 * 60 * 60,
    "3d": 3 * 24 * 60 * 60,
    "1w": 7 * 24 * 60 * 60,
}


def interval_to_seconds(interval: str) -> int:
    key = (interval or "").strip()
    seconds = _INTERVAL_TO_SECONDS.get(key)
    if seconds is None:
        raise ValueError(f"Unsupported Hyperliquid interval: {interval!r}")
    return seconds


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def floor_bar_open_utc(dt: datetime, interval: str) -> datetime:
    """Return the open timestamp of the bar that contains ``dt`` (UTC)."""
    utc = ensure_utc(dt)
    seconds = interval_to_seconds(interval)
    epoch = int(utc.timestamp())
    floored = epoch - (epoch % seconds)
    return datetime.fromtimestamp(floored, tz=timezone.utc)


def next_bar_open_utc(dt: datetime, interval: str) -> datetime:
    open_ts = floor_bar_open_utc(dt, interval)
    return open_ts + timedelta(seconds=interval_to_seconds(interval))


def bar_close_utc(bar_open: datetime, interval: str) -> datetime:
    """Exclusive close instant of the bar that opened at ``bar_open``."""
    return ensure_utc(bar_open) + timedelta(seconds=interval_to_seconds(interval))

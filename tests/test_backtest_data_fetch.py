"""Tests for daily-universe backtest data merge helpers."""

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.daily_universe import merge_candles_sorted_values, stable_shard_market
from models.candle import Candle


def _c(ts_day: int) -> Candle:
    return Candle(
        timestamp=datetime(2024, 1, ts_day, tzinfo=timezone.utc),
        open=float(ts_day),
        high=float(ts_day) + 0.5,
        low=float(ts_day) - 0.5,
        close=float(ts_day),
    )


def test_merge_candles_sorted_values_dedupes_by_timestamp() -> None:
    a = [_c(1), _c(2)]
    t2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    t3 = datetime(2024, 1, 3, tzinfo=timezone.utc)
    b = [
        Candle(timestamp=t2, open=99.0, high=100.0, low=98.0, close=99.5),
        Candle(timestamp=t3, open=3.0, high=3.5, low=2.5, close=3.0),
    ]
    merged = merge_candles_sorted_values([a, b])
    assert len(merged) == 3
    assert merged[0].close == 1.0
    assert merged[1].close == 99.5
    assert merged[2].close == 3.0


def test_stable_shard_market_is_deterministic() -> None:
    assert stable_shard_market("BTC", 0, 4) == stable_shard_market("BTC", 0, 4)
    assert stable_shard_market("BTC", 0, 1) is True


def test_stable_shard_market_exhaustive_partition_covers_each_coin_once() -> None:
    """Each coin maps to exactly one shard index in range(total)."""
    for coin in ("BTC", "ETH", "SOL", "xyz:EUR"):
        hits = [i for i in range(3) if stable_shard_market(coin, i, 3)]
        assert len(hits) == 1

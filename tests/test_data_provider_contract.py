from __future__ import annotations

from datetime import datetime, timezone

import pytest

from config.strategy_config import build_strategy_config, min_strategy_candle_count
from data.providers.base import DataBatch
from data.providers.contract import validate_data_batch
from data.providers.golden_data_provider import GoldenDataProvider
from data.providers.live_data_provider import LiveDataProvider
from models.candle import Candle


def _utc(hour: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, 0, 0, tzinfo=timezone.utc)


def test_validate_rejects_blank_source_name() -> None:
    batch = DataBatch(
        candles=[Candle(timestamp=_utc(), open=1.0, high=2.0, low=0.5, close=1.5)],
        source_name="   ",
    )
    with pytest.raises(ValueError, match="source_name must be non-blank"):
        validate_data_batch(batch)


def test_validate_rejects_empty_candles() -> None:
    batch = DataBatch(candles=[], source_name="golden:test")
    with pytest.raises(ValueError, match="candles must be non-empty"):
        validate_data_batch(batch)


def test_validate_rejects_naive_timestamp() -> None:
    batch = DataBatch(
        candles=[
            Candle(
                timestamp=datetime(2026, 1, 1, 0, 0, 0),
                open=1.0,
                high=2.0,
                low=0.5,
                close=1.5,
            )
        ],
        source_name="unit:test",
    )
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        validate_data_batch(batch)


def test_validate_rejects_non_increasing_timestamps() -> None:
    batch = DataBatch(
        candles=[
            Candle(timestamp=_utc(1), open=1.0, high=2.0, low=0.5, close=1.5),
            Candle(timestamp=_utc(1), open=1.5, high=2.0, low=1.0, close=1.8),
        ],
        source_name="unit:test",
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        validate_data_batch(batch)


def test_validate_rejects_out_of_order_timestamps() -> None:
    batch = DataBatch(
        candles=[
            Candle(timestamp=_utc(2), open=1.0, high=2.0, low=0.5, close=1.5),
            Candle(timestamp=_utc(1), open=1.5, high=2.0, low=1.0, close=1.8),
        ],
        source_name="unit:test",
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        validate_data_batch(batch)


def test_validate_rejects_insufficient_candles_when_min_set() -> None:
    batch = DataBatch(
        candles=[
            Candle(timestamp=_utc(i), open=1.0, high=2.0, low=0.5, close=1.5) for i in range(3)
        ],
        source_name="unit:test",
        config=build_strategy_config(),
    )
    with pytest.raises(ValueError, match="need at least 26 candles"):
        validate_data_batch(batch, min_candles=min_strategy_candle_count(batch.config))


def test_validate_hyperliquid_requires_symbol() -> None:
    batch = DataBatch(
        candles=[Candle(timestamp=_utc(), open=1.0, high=2.0, low=0.5, close=1.5)],
        symbol=None,
        source_name="hyperliquid_historical",
    )
    with pytest.raises(ValueError, match="non-blank symbol"):
        validate_data_batch(batch)


def test_validate_accepts_hyperliquid_batch_with_symbol() -> None:
    batch = DataBatch(
        candles=[Candle(timestamp=_utc(), open=1.0, high=2.0, low=0.5, close=1.5)],
        symbol="BTC",
        source_name="hyperliquid_historical",
    )
    validate_data_batch(batch)


def test_golden_data_provider_get_data_satisfies_contract() -> None:
    batch = GoldenDataProvider("valid trend long").get_data()
    assert batch.source_name.startswith("golden:")
    assert batch.candles[0].timestamp.tzinfo is not None
    validate_data_batch(batch, min_candles=min_strategy_candle_count(batch.config))


def test_live_data_provider_stub_get_data_passes_contract() -> None:
    batch = LiveDataProvider().get_data()
    assert batch.source_name == "live_stub"
    assert batch.candles[0].timestamp.tzinfo is not None
    validate_data_batch(batch, min_candles=min_strategy_candle_count(batch.config))

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from models.candle import Candle
from scripts.golden_schema_compare import (
    check_candle_consistency,
    compare_candle_shape,
    is_chronologically_sorted,
    summarize_candles,
    summarize_time_spacing,
)


class MissingCloseCandle:
    def __init__(self) -> None:
        self.timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.open = 1.0
        self.high = 2.0
        self.low = 0.5



def _make_candle(timestamp: datetime, open_price: float, high: float, low: float, close: float) -> Candle:
    return Candle(timestamp=timestamp, open=open_price, high=high, low=low, close=close)



def test_compare_candle_shape_returns_true_for_matching_candle_structure() -> None:
    candles_a = [_make_candle(datetime(2026, 1, 1, tzinfo=timezone.utc), 1, 2, 0.5, 1.5)]
    candles_b = [_make_candle(datetime(2026, 1, 2, tzinfo=timezone.utc), 2, 3, 1.5, 2.5)]

    assert compare_candle_shape(candles_a, candles_b) is True



def test_compare_candle_shape_returns_false_for_missing_core_field() -> None:
    candles_a = [_make_candle(datetime(2026, 1, 1, tzinfo=timezone.utc), 1, 2, 0.5, 1.5)]
    candles_b = [MissingCloseCandle()]

    assert compare_candle_shape(candles_a, candles_b) is False



def test_chronological_check_detects_sorted_candles() -> None:
    candles = [
        _make_candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1, 2, 0.5, 1.5),
        _make_candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), 1.5, 2.5, 1.0, 2.0),
    ]

    assert is_chronologically_sorted(candles) is True



def test_chronological_check_detects_unsorted_candles() -> None:
    candles = [
        _make_candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), 1.5, 2.5, 1.0, 2.0),
        _make_candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1, 2, 0.5, 1.5),
    ]

    assert is_chronologically_sorted(candles) is False



def test_summarize_candles_returns_count_and_basic_range_info() -> None:
    candles = [
        _make_candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1, 2, 0.5, 1.5),
        _make_candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), 2, 3, 1.5, 2.5),
    ]

    summary = summarize_candles(candles)

    assert summary["count"] == 2
    assert summary["close_min"] == 1.5
    assert summary["close_max"] == 2.5
    assert summary["high_max"] == 3
    assert summary["low_min"] == 0.5
    assert summary["magnitude_ratio"] is not None



def test_candle_consistency_check_passes_for_valid_candles() -> None:
    candles = [
        _make_candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1, 2, 0.5, 1.5),
        _make_candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), 2, 3, 1.5, 2.5),
    ]

    result = check_candle_consistency(candles)

    assert result["ok"] is True
    assert result["invalid_count"] == 0



def test_candle_consistency_check_fails_for_invalid_candles() -> None:
    # Candle model now validates OHLC constraints at construction time,
    # so an invalid candle (high < close) raises a ValidationError.
    with pytest.raises(Exception):
        _make_candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1, 0.8, 0.5, 1.5)



def test_spacing_summary_handles_short_or_empty_inputs_gracefully() -> None:
    empty_summary = summarize_time_spacing([])
    single_summary = summarize_time_spacing(
        [_make_candle(datetime(2026, 1, 1, tzinfo=timezone.utc), 1, 2, 0.5, 1.5)]
    )
    multi_summary = summarize_time_spacing(
        [
            _make_candle(datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc), 1, 2, 0.5, 1.5),
            _make_candle(datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc), 1.5, 2.5, 1.0, 2.0),
            _make_candle(datetime(2026, 1, 1, 3, 0, tzinfo=timezone.utc), 2.0, 3.0, 1.5, 2.8),
        ]
    )

    assert empty_summary == {"min_seconds": None, "max_seconds": None, "median_seconds": None}
    assert single_summary == {"min_seconds": None, "max_seconds": None, "median_seconds": None}
    assert multi_summary["min_seconds"] == 3600.0
    assert multi_summary["max_seconds"] == 7200.0
    assert multi_summary["median_seconds"] == 5400.0

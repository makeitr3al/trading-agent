from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from indicators.bollinger import compute_bollinger_bands
from indicators.macd import compute_macd


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


def test_bollinger_known_values() -> None:
    closes = pd.Series([float(i) for i in range(1, 21)])  # 1..20
    period = 5
    bb = compute_bollinger_bands(closes, period=period, std_dev=2.0)

    assert list(bb.columns) == ["bb_middle", "bb_upper", "bb_lower"]

    # First (period-1) values must be NaN
    assert bb["bb_middle"].isna().sum() == period - 1

    # Middle band equals rolling mean
    expected_middle = closes.rolling(window=period).mean()
    pd.testing.assert_series_equal(bb["bb_middle"], expected_middle, check_names=False)

    # Upper and lower are symmetric around middle
    diff_upper = bb["bb_upper"] - bb["bb_middle"]
    diff_lower = bb["bb_middle"] - bb["bb_lower"]
    pd.testing.assert_series_equal(diff_upper, diff_lower, check_names=False)

    # Bands are ordered: lower <= middle <= upper (where not NaN)
    valid = bb.dropna()
    assert (valid["bb_lower"] <= valid["bb_middle"]).all()
    assert (valid["bb_middle"] <= valid["bb_upper"]).all()


def test_bollinger_empty_series() -> None:
    bb = compute_bollinger_bands(pd.Series([], dtype=float), period=5, std_dev=2.0)
    assert len(bb) == 0


def test_bollinger_series_shorter_than_period() -> None:
    bb = compute_bollinger_bands(pd.Series([1.0, 2.0, 3.0]), period=5, std_dev=2.0)
    assert bb["bb_middle"].isna().all()


def test_bollinger_single_value() -> None:
    bb = compute_bollinger_bands(pd.Series([42.0]), period=1, std_dev=2.0)
    assert bb["bb_middle"].iloc[0] == pytest.approx(42.0)


def test_bollinger_constant_series_has_zero_bandwidth() -> None:
    closes = pd.Series([100.0] * 20)
    bb = compute_bollinger_bands(closes, period=5, std_dev=2.0)
    valid = bb.dropna()
    pd.testing.assert_series_equal(
        valid["bb_upper"], valid["bb_lower"], check_names=False
    )


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def test_macd_known_values() -> None:
    closes = pd.Series([float(i) for i in range(1, 51)])  # 1..50
    result = compute_macd(closes, fast_period=12, slow_period=26, signal_period=9)

    assert list(result.columns) == ["macd", "macd_signal"]
    assert len(result) == len(closes)

    # MACD = fast_ema - slow_ema
    fast_ema = closes.ewm(span=12, adjust=False).mean()
    slow_ema = closes.ewm(span=26, adjust=False).mean()
    expected_macd = fast_ema - slow_ema
    pd.testing.assert_series_equal(result["macd"], expected_macd, check_names=False)

    # Signal = EMA of MACD line
    expected_signal = expected_macd.ewm(span=9, adjust=False).mean()
    pd.testing.assert_series_equal(
        result["macd_signal"], expected_signal, check_names=False
    )


def test_macd_empty_series() -> None:
    result = compute_macd(pd.Series([], dtype=float), 12, 26, 9)
    assert len(result) == 0


def test_macd_short_series() -> None:
    result = compute_macd(pd.Series([1.0, 2.0, 3.0]), 12, 26, 9)
    assert len(result) == 3
    # EWM still produces values (unlike rolling), so no NaN expected
    assert not result["macd"].isna().any()


def test_macd_constant_series_produces_zero_macd() -> None:
    closes = pd.Series([50.0] * 100)
    result = compute_macd(closes, fast_period=12, slow_period=26, signal_period=9)
    assert result["macd"].iloc[-1] == pytest.approx(0.0)
    assert result["macd_signal"].iloc[-1] == pytest.approx(0.0)


def test_macd_uptrend_produces_positive_macd() -> None:
    closes = pd.Series([float(i) for i in range(1, 101)])
    result = compute_macd(closes, fast_period=12, slow_period=26, signal_period=9)
    # In a steady uptrend, fast EMA > slow EMA → positive MACD
    assert result["macd"].iloc[-1] > 0

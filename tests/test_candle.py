from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import datetime, timezone

import pytest

from models.candle import Candle

_TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_valid_candle() -> None:
    c = Candle(timestamp=_TS, open=100.0, high=110.0, low=90.0, close=105.0)
    assert c.high == 110.0


def test_high_below_open_rejected() -> None:
    with pytest.raises(ValueError, match="high must be >= open and close"):
        Candle(timestamp=_TS, open=100.0, high=99.0, low=90.0, close=95.0)


def test_high_below_close_rejected() -> None:
    with pytest.raises(ValueError, match="high must be >= open and close"):
        Candle(timestamp=_TS, open=95.0, high=99.0, low=90.0, close=100.0)


def test_low_above_open_rejected() -> None:
    with pytest.raises(ValueError, match="low must be <= open and close"):
        Candle(timestamp=_TS, open=100.0, high=110.0, low=101.0, close=105.0)


def test_low_above_close_rejected() -> None:
    with pytest.raises(ValueError, match="low must be <= open and close"):
        Candle(timestamp=_TS, open=105.0, high=110.0, low=104.0, close=103.0)


def test_negative_low_rejected() -> None:
    with pytest.raises(ValueError, match="low must be >= 0"):
        Candle(timestamp=_TS, open=10.0, high=20.0, low=-1.0, close=15.0)


def test_doji_candle_valid() -> None:
    c = Candle(timestamp=_TS, open=100.0, high=100.0, low=100.0, close=100.0)
    assert c.open == c.high == c.low == c.close

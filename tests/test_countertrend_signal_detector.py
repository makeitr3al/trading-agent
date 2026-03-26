from datetime import datetime, timedelta
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.strategy_config import StrategyConfig
from models.candle import Candle
from models.regime import RegimeState, RegimeType
from models.signal import SignalType
from strategy.countertrend_signal_detector import detect_countertrend_signal


def _make_config() -> StrategyConfig:
    return StrategyConfig(
        min_bandwidth_avg_period=3,
        outside_buffer_pct=0.20,
    )


def _make_candles(final_open: float, final_close: float) -> list[Candle]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    closes = [8.0, 8.4, final_close]
    opens = [7.9, 8.3, final_open]

    return [
        Candle(
            timestamp=base_time + timedelta(hours=index),
            open=opens[index],
            high=max(opens[index], closes[index]) + 0.1,
            low=min(opens[index], closes[index]) - 0.1,
            close=closes[index],
        )
        for index in range(3)
    ]


def _make_bollinger_df(last_row: tuple[float, float, float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"bb_upper": 10.0, "bb_middle": 8.0, "bb_lower": 6.0},
            {"bb_upper": 10.2, "bb_middle": 8.0, "bb_lower": 5.8},
            {
                "bb_upper": last_row[0],
                "bb_middle": last_row[1],
                "bb_lower": last_row[2],
            },
        ]
    )


def _make_regime_states(
    regime: RegimeType, bars_since_regime_start: int
) -> list[RegimeState]:
    return [
        RegimeState(regime=regime, bars_since_regime_start=3),
        RegimeState(regime=regime, bars_since_regime_start=2),
        RegimeState(
            regime=regime,
            bars_since_regime_start=bars_since_regime_start,
        ),
    ]


def test_detect_countertrend_signal_valid_countertrend_short_signal() -> None:
    config = _make_config()
    candles = _make_candles(final_open=10.3, final_close=10.9)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.0, 6.0))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=1)

    signal = detect_countertrend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is True
    assert signal.signal_type == SignalType.COUNTERTREND_SHORT
    assert signal.entry == 10.9
    assert signal.stop_loss is not None
    assert signal.take_profit == 8.0
    assert signal.stop_loss > signal.entry


def test_detect_countertrend_signal_valid_countertrend_long_signal() -> None:
    config = _make_config()
    candles = _make_candles(final_open=5.7, final_close=5.1)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.0, 6.0))
    regime_states = _make_regime_states(RegimeType.BEARISH, bars_since_regime_start=1)

    signal = detect_countertrend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is True
    assert signal.signal_type == SignalType.COUNTERTREND_LONG
    assert signal.entry == 5.1
    assert signal.stop_loss is not None
    assert signal.take_profit == 8.0
    assert signal.stop_loss < signal.entry


def test_detect_countertrend_signal_invalid_because_neutral_regime() -> None:
    config = _make_config()
    candles = _make_candles(final_open=10.3, final_close=10.9)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.0, 6.0))
    regime_states = _make_regime_states(RegimeType.NEUTRAL, bars_since_regime_start=1)

    signal = detect_countertrend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "neutral regime"


def test_detect_countertrend_signal_invalid_because_not_first_regime_bar() -> None:
    config = _make_config()
    candles = _make_candles(final_open=10.3, final_close=10.9)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.0, 6.0))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=2)

    signal = detect_countertrend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "not first regime bar"


def test_detect_countertrend_signal_invalid_because_close_not_deep_outside_bands() -> None:
    config = _make_config()
    candles = _make_candles(final_open=10.1, final_close=10.3)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.0, 6.0))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=1)

    signal = detect_countertrend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "close not deep outside bands"


def test_detect_countertrend_signal_invalid_because_insufficient_bandwidth() -> None:
    config = _make_config()
    candles = _make_candles(final_open=8.2, final_close=8.65)
    bollinger_df = _make_bollinger_df(last_row=(8.5, 8.0, 7.5))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=1)

    signal = detect_countertrend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "insufficient bandwidth"

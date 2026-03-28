from datetime import datetime, timedelta
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.strategy_config import StrategyConfig
from models.candle import Candle
from models.regime import RegimeState, RegimeType
from models.signal import SignalType
from strategy.trend_signal_detector import detect_trend_signal


def _make_config() -> StrategyConfig:
    return StrategyConfig(
        min_bandwidth_avg_period=3,
        max_bars_since_regime_start_for_trend_signal=6,
        inside_buffer_pct=0.20,
        trend_tp_rr=2.0,
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
            {"bb_upper": 9.0, "bb_middle": 8.0, "bb_lower": 7.0},
            {"bb_upper": 9.2, "bb_middle": 8.0, "bb_lower": 6.8},
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
        RegimeState(regime=regime, bars_since_regime_start=1),
        RegimeState(regime=regime, bars_since_regime_start=2),
        RegimeState(
            regime=regime,
            bars_since_regime_start=bars_since_regime_start,
        ),
    ]


def test_detect_trend_signal_valid_trend_long_signal() -> None:
    config = _make_config()
    candles = _make_candles(final_open=9.2, final_close=9.5)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.5, 7.0))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=3)

    signal = detect_trend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is True
    assert signal.signal_type == SignalType.TREND_LONG
    assert signal.entry == 10.0
    assert signal.stop_loss == 8.5
    assert signal.take_profit == 13.0


def test_detect_trend_signal_invalid_because_neutral_regime() -> None:
    config = _make_config()
    candles = _make_candles(final_open=9.2, final_close=9.5)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.5, 7.0))
    regime_states = _make_regime_states(RegimeType.NEUTRAL, bars_since_regime_start=3)

    signal = detect_trend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "neutral regime"


def test_detect_trend_signal_invalid_because_regime_too_old() -> None:
    config = _make_config()
    candles = _make_candles(final_open=9.2, final_close=9.5)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.5, 7.0))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=7)

    signal = detect_trend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "regime too old"


def test_detect_trend_signal_invalid_because_candle_not_in_trend_direction() -> None:
    config = _make_config()
    candles = _make_candles(final_open=9.7, final_close=9.5)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.5, 7.0))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=3)

    signal = detect_trend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "candle not in trend direction"


def test_detect_trend_signal_invalid_because_close_not_deep_inside_bands() -> None:
    config = _make_config()
    candles = _make_candles(final_open=9.7, final_close=9.9)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.5, 7.0))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=3)

    signal = detect_trend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "close not deep inside bands"



def test_detect_trend_signal_invalid_because_close_in_wrong_band_half() -> None:
    config = _make_config()
    candles = _make_candles(final_open=8.2, final_close=8.4)
    bollinger_df = _make_bollinger_df(last_row=(10.0, 8.5, 7.0))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=3)

    signal = detect_trend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "close not deep inside bands"
def test_detect_trend_signal_invalid_because_insufficient_bandwidth() -> None:
    config = _make_config()
    candles = _make_candles(final_open=8.1, final_close=8.3)
    bollinger_df = _make_bollinger_df(last_row=(8.5, 8.3, 8.1))
    regime_states = _make_regime_states(RegimeType.BULLISH, bars_since_regime_start=3)

    signal = detect_trend_signal(candles, bollinger_df, regime_states, config)

    assert signal is not None
    assert signal.is_valid is False
    assert signal.reason == "insufficient bandwidth"


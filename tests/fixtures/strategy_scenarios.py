from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from models.trade import Trade, TradeDirection, TradeType


@dataclass
class StrategyGoldenScenario:
    name: str
    candles: list[Candle]
    config: StrategyConfig
    account_balance: float = 10000.0
    active_trade: Trade | None = None
    agent_state: AgentState | None = None
    expected_trend_signal_valid: bool | None = None
    expected_trend_signal_type: str | None = None
    expected_countertrend_signal_valid: bool | None = None
    expected_countertrend_signal_type: str | None = None
    expected_decision_action: str | None = None
    expected_order_present: bool | None = None
    expected_break_even_activated: bool | None = None
    expected_consumed_flag: bool | None = None
    expected_close_active_trade: bool | None = None
    expected_updated_stop_loss: float | None = None


BASE_TIME = datetime(2026, 1, 1, 0, 0, 0)
TREND_CONTEXT_CLOSES = [
    10.9,
    10.7,
    10.8,
    10.55,
    10.45,
    10.25,
    10.35,
    10.15,
    10.05,
    10.15,
    10.0,
    9.9,
    10.0,
    9.85,
    9.95,
    9.8,
]
BULLISH_REVERSAL_CONTEXT_CLOSES = [
    10.8,
    10.65,
    10.55,
    10.4,
    10.25,
    10.15,
    10.0,
    9.9,
    9.8,
    9.7,
    9.6,
    9.55,
    9.5,
    9.45,
    9.4,
    9.35,
]
BEARISH_REVERSAL_CONTEXT_CLOSES = [
    9.0,
    9.1,
    9.2,
    9.3,
    9.4,
    9.5,
    9.6,
    9.7,
    9.8,
    9.9,
    10.0,
    10.05,
    10.1,
    10.15,
    10.2,
    10.25,
]
LONGER_SWING_CLOSES = [
    100.0,
    100.5,
    101.0,
    100.8,
    101.4,
    102.0,
    101.7,
    102.5,
    103.1,
    102.9,
    103.4,
    104.0,
    103.8,
    104.6,
    105.1,
    104.9,
    105.5,
    106.0,
    105.7,
    106.4,
    107.0,
    106.8,
    107.3,
    108.0,
    107.6,
    108.4,
    109.0,
    108.7,
    109.5,
    110.0,
    109.8,
    110.4,
    111.0,
    110.6,
    111.3,
    112.0,
    111.8,
    112.4,
    113.0,
    112.7,
]


def make_config(**overrides: float | int) -> StrategyConfig:
    defaults = {
        "bollinger_period": 3,
        "bollinger_std_dev": 2.0,
        "macd_fast_period": 2,
        "macd_slow_period": 4,
        "macd_signal_period": 2,
        "min_bandwidth_avg_period": 3,
        "max_bars_since_regime_start_for_trend_signal": 3,
        "inside_buffer_pct": 0.20,
        "outside_buffer_pct": 0.20,
        "outside_band_sweet_spot": 0.0,
        "trend_tp_rr": 2.0,
        "risk_per_trade_pct": 0.01,
    }
    defaults.update(overrides)
    return StrategyConfig(**defaults)


def _build_candles(
    closes: list[float],
    final_open: float | None = None,
    default_open_offset: float = -0.1,
    high_padding: float = 0.2,
    low_padding: float = 0.2,
) -> list[Candle]:
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        open_price = close + default_open_offset
        if index == len(closes) - 1 and final_open is not None:
            open_price = final_open

        candles.append(
            Candle(
                timestamp=BASE_TIME + timedelta(days=index),
                open=float(open_price),
                high=float(max(open_price, close) + high_padding),
                low=float(min(open_price, close) - low_padding),
                close=float(close),
            )
        )
    return candles


def _prepend_context(tail: list[float], context: list[float]) -> list[float]:
    return context + tail


def _make_trade(
    trade_type: TradeType,
    direction: TradeDirection,
    entry: float,
    stop_loss: float,
    take_profit: float,
    break_even_activated: bool = False,
) -> Trade:
    return Trade(
        trade_type=trade_type,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        break_even_activated=break_even_activated,
    )


def _chart_scenario(
    name: str,
    closes: list[float],
    config: StrategyConfig,
    final_open: float | None = None,
    default_open_offset: float = -0.1,
    **expected: bool | str | float | None,
) -> StrategyGoldenScenario:
    return StrategyGoldenScenario(
        name=name,
        candles=_build_candles(
            closes,
            final_open=final_open,
            default_open_offset=default_open_offset,
        ),
        config=config,
        **expected,
    )


def _state_scenario(
    name: str,
    closes: list[float],
    config: StrategyConfig,
    active_trade: Trade | None = None,
    agent_state: AgentState | None = None,
    final_open: float | None = None,
    default_open_offset: float = -0.1,
    **expected: bool | str | float | None,
) -> StrategyGoldenScenario:
    return StrategyGoldenScenario(
        name=name,
        candles=_build_candles(
            closes,
            final_open=final_open,
            default_open_offset=default_open_offset,
        ),
        config=config,
        active_trade=active_trade,
        agent_state=agent_state,
        **expected,
    )


def valid_trend_long_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="valid trend long",
        closes=_prepend_context([10.0, 10.1, 10.0, 9.8, 9.8, 9.8, 9.9], TREND_CONTEXT_CLOSES),
        config=make_config(),
        expected_trend_signal_valid=True,
        expected_trend_signal_type="TREND_LONG",
        expected_countertrend_signal_valid=False,
        expected_decision_action="PREPARE_TREND_ORDER",
        expected_order_present=True,
    )


def invalid_trend_regime_too_old_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="invalid trend regime too old",
        closes=_prepend_context([9.7, 9.7, 9.7, 9.7, 9.7, 9.8, 9.8], TREND_CONTEXT_CLOSES),
        config=make_config(max_bars_since_regime_start_for_trend_signal=1),
        expected_trend_signal_valid=False,
        expected_trend_signal_type="TREND_LONG",
        expected_countertrend_signal_valid=False,
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
    )


def invalid_trend_candle_not_in_direction_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="invalid trend candle not in direction",
        closes=_prepend_context([10.0, 10.1, 10.0, 9.8, 9.8, 9.8, 9.9], TREND_CONTEXT_CLOSES),
        config=make_config(),
        final_open=10.05,
        expected_trend_signal_valid=False,
        expected_trend_signal_type="TREND_LONG",
        expected_countertrend_signal_valid=False,
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
    )


def valid_countertrend_short_first_bullish_regime_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="valid countertrend short first bullish regime bar",
        closes=_prepend_context([9.6, 9.55, 9.5, 9.45, 9.4, 9.35, 11.0], BULLISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(bollinger_std_dev=0.5),
        expected_trend_signal_valid=False,
        expected_countertrend_signal_valid=True,
        expected_countertrend_signal_type="COUNTERTREND_SHORT",
        expected_decision_action="PREPARE_COUNTERTREND_ORDER",
        expected_order_present=True,
    )


def sweet_spot_should_manage_active_trend_without_countertrend_signal_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="sweet spot manages active trend without countertrend signal",
        closes=_prepend_context([9.6, 9.55, 9.5, 9.45, 9.4, 9.35, 9.4], BULLISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(bollinger_std_dev=0.5, outside_band_sweet_spot=0.2),
        active_trade=_make_trade(
            TradeType.TREND,
            TradeDirection.LONG,
            entry=9.2,
            stop_loss=9.0,
            take_profit=9.9,
        ),
        expected_countertrend_signal_valid=False,
        expected_countertrend_signal_type="COUNTERTREND_SHORT",
        expected_decision_action="ADJUST_TREND_STOP_TO_LAST_CLOSE",
        expected_order_present=False,
        expected_close_active_trade=False,
        expected_updated_stop_loss=9.4,
    )


def valid_countertrend_long_first_bearish_regime_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="valid countertrend long first bearish regime bar",
        closes=_prepend_context([10.4, 10.45, 10.5, 10.55, 10.6, 10.65, 9.0], BEARISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(bollinger_std_dev=0.5),
        final_open=9.1,
        expected_trend_signal_valid=False,
        expected_countertrend_signal_valid=True,
        expected_countertrend_signal_type="COUNTERTREND_LONG",
        expected_decision_action="PREPARE_COUNTERTREND_ORDER",
        expected_order_present=True,
    )


def no_countertrend_not_first_regime_bar_scenario() -> StrategyGoldenScenario:
    return _chart_scenario(
        name="no countertrend not first regime bar",
        closes=_prepend_context([9.6, 9.55, 9.5, 9.45, 9.4, 11.0, 11.3], BULLISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(bollinger_std_dev=0.5),
        expected_trend_signal_valid=False,
        expected_countertrend_signal_valid=False,
        expected_countertrend_signal_type="COUNTERTREND_SHORT",
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
    )


def trend_order_should_be_prepared_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="trend order should be prepared",
        closes=_prepend_context([10.0, 10.1, 10.0, 9.8, 9.8, 9.8, 9.9], TREND_CONTEXT_CLOSES),
        config=make_config(),
        agent_state=AgentState(),
        expected_trend_signal_valid=True,
        expected_trend_signal_type="TREND_LONG",
        expected_decision_action="PREPARE_TREND_ORDER",
        expected_order_present=True,
        expected_consumed_flag=True,
    )


def countertrend_should_override_active_trend_trade_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="countertrend overrides active trend trade by locking stop",
        closes=_prepend_context([9.6, 9.55, 9.5, 9.45, 9.4, 9.35, 11.0], BULLISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(bollinger_std_dev=0.5),
        active_trade=_make_trade(
            TradeType.TREND,
            TradeDirection.LONG,
            entry=10.2,
            stop_loss=9.7,
            take_profit=11.2,
        ),
        expected_countertrend_signal_valid=True,
        expected_countertrend_signal_type="COUNTERTREND_SHORT",
        expected_decision_action="ADJUST_TREND_STOP_TO_LAST_CLOSE",
        expected_order_present=False,
        expected_close_active_trade=False,
        expected_updated_stop_loss=11.0,
    )


def countertrend_should_close_active_trend_trade_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="countertrend closes active trend trade",
        closes=_prepend_context([10.4, 10.45, 10.5, 10.55, 10.6, 10.65, 9.0], BEARISH_REVERSAL_CONTEXT_CLOSES),
        config=make_config(bollinger_std_dev=0.5),
        final_open=9.1,
        active_trade=_make_trade(
            TradeType.TREND,
            TradeDirection.SHORT,
            entry=8.8,
            stop_loss=9.4,
            take_profit=8.0,
        ),
        expected_countertrend_signal_valid=True,
        expected_countertrend_signal_type="COUNTERTREND_LONG",
        expected_decision_action="CLOSE_TREND_TRADE",
        expected_order_present=False,
        expected_close_active_trade=True,
    )


def break_even_should_activate_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="break even should activate",
        closes=LONGER_SWING_CLOSES,
        config=StrategyConfig(),
        active_trade=_make_trade(
            TradeType.TREND,
            TradeDirection.LONG,
            entry=100.0,
            stop_loss=95.0,
            take_profit=110.0,
        ),
        expected_break_even_activated=True,
    )


def countertrend_tp_should_update_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="countertrend tp should update",
        closes=LONGER_SWING_CLOSES,
        config=StrategyConfig(),
        active_trade=_make_trade(
            TradeType.COUNTERTREND,
            TradeDirection.SHORT,
            entry=100.0,
            stop_loss=110.0,
            take_profit=95.0,
        ),
        expected_break_even_activated=False,
    )


def trend_signal_consumed_duplicate_order_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="trend signal consumed duplicate order",
        closes=_prepend_context([10.0, 10.1, 10.0, 9.8, 9.8, 9.8, 9.9], TREND_CONTEXT_CLOSES),
        config=make_config(),
        agent_state=AgentState(
            trend_signal_consumed_in_regime=True,
            last_regime="bullish",
        ),
        expected_trend_signal_valid=False,
        expected_trend_signal_type="TREND_LONG",
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
        expected_consumed_flag=True,
    )


def regime_change_should_reset_consumed_flag_scenario() -> StrategyGoldenScenario:
    return _state_scenario(
        name="regime change should reset consumed flag",
        closes=_prepend_context([9.7, 9.7, 9.7, 9.7, 9.7, 9.8, 9.8], TREND_CONTEXT_CLOSES),
        config=make_config(max_bars_since_regime_start_for_trend_signal=1),
        agent_state=AgentState(
            trend_signal_consumed_in_regime=True,
            last_regime="bearish",
        ),
        expected_trend_signal_valid=False,
        expected_decision_action="NO_ACTION",
        expected_order_present=False,
        expected_consumed_flag=False,
    )


__all__ = [
    "StrategyGoldenScenario",
    "valid_trend_long_scenario",
    "invalid_trend_regime_too_old_scenario",
    "invalid_trend_candle_not_in_direction_scenario",
    "valid_countertrend_short_first_bullish_regime_scenario",
    "sweet_spot_should_manage_active_trend_without_countertrend_signal_scenario",
    "valid_countertrend_long_first_bearish_regime_scenario",
    "no_countertrend_not_first_regime_bar_scenario",
    "trend_order_should_be_prepared_scenario",
    "countertrend_should_override_active_trend_trade_scenario",
    "countertrend_should_close_active_trend_trade_scenario",
    "break_even_should_activate_scenario",
    "countertrend_tp_should_update_scenario",
    "trend_signal_consumed_duplicate_order_scenario",
    "regime_change_should_reset_consumed_flag_scenario",
]




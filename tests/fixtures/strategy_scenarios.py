from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.runner_result import StrategyRunResult
from models.signal import SignalState, SignalType
from models.trade import Trade, TradeDirection, TradeType


@dataclass
class StrategyGoldenScenario:
    name: str
    candles: list[Candle]
    config: StrategyConfig
    account_balance: float = 10000.0
    active_trade: Trade | None = None
    state: AgentState | None = None
    trend_signal: SignalState | None = None
    countertrend_signal: SignalState | None = None
    strategy_result: StrategyRunResult | None = None
    expected: dict[str, object] = field(default_factory=dict)


BASE_TIME = datetime(2026, 1, 1, 0, 0, 0)


def make_config(**overrides: float | int) -> StrategyConfig:
    defaults = {
        "min_bandwidth_avg_period": 5,
        "max_bars_since_regime_start_for_trend_signal": 6,
        "inside_buffer_pct": 0.20,
        "outside_buffer_pct": 0.20,
        "trend_tp_rr": 2.0,
        "risk_per_trade_pct": 0.01,
    }
    defaults.update(overrides)
    return StrategyConfig(**defaults)


def _build_candles(
    closes: list[float],
    final_open: float | None = None,
    high_padding: float = 0.2,
    low_padding: float = 0.2,
) -> list[Candle]:
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        open_price = close - 0.1
        if index == len(closes) - 1 and final_open is not None:
            open_price = final_open

        candles.append(
            Candle(
                timestamp=BASE_TIME + timedelta(hours=index),
                open=float(open_price),
                high=float(max(open_price, close) + high_padding),
                low=float(min(open_price, close) - low_padding),
                close=float(close),
            )
        )
    return candles


def build_bullish_trend_candles(final_open: float | None = None) -> list[Candle]:
    closes = [
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
    return _build_candles(closes, final_open=final_open)


def build_bearish_trend_candles(final_open: float | None = None) -> list[Candle]:
    closes = [
        113.0,
        112.6,
        112.1,
        112.3,
        111.7,
        111.1,
        111.3,
        110.6,
        110.0,
        110.2,
        109.6,
        109.0,
        109.2,
        108.5,
        107.9,
        108.1,
        107.4,
        106.8,
        107.0,
        106.3,
        105.7,
        105.9,
        105.2,
        104.6,
        104.8,
        104.1,
        103.5,
        103.7,
        103.0,
        102.4,
        102.6,
        101.9,
        101.3,
        101.5,
        100.8,
        100.2,
        100.4,
        99.7,
        99.1,
        99.3,
    ]
    return _build_candles(closes, final_open=final_open)


def build_spike_above_band_candles() -> list[Candle]:
    closes = [
        100.0,
        100.4,
        100.9,
        101.3,
        101.8,
        102.2,
        102.7,
        103.0,
        103.5,
        103.9,
        104.4,
        104.8,
        105.3,
        105.7,
        106.2,
        106.6,
        107.1,
        107.5,
        108.0,
        108.4,
        108.9,
        109.3,
        109.8,
        110.2,
        110.7,
        111.1,
        111.6,
        112.0,
        112.5,
        112.9,
        113.4,
        113.8,
        114.3,
        114.7,
        115.2,
        115.6,
        116.1,
        116.5,
        117.0,
        119.0,
    ]
    return _build_candles(closes, final_open=118.2, high_padding=0.3, low_padding=0.2)


def build_spike_below_band_candles() -> list[Candle]:
    closes = [
        119.0,
        118.5,
        118.0,
        117.6,
        117.1,
        116.7,
        116.2,
        115.8,
        115.3,
        114.9,
        114.4,
        114.0,
        113.5,
        113.1,
        112.6,
        112.2,
        111.7,
        111.3,
        110.8,
        110.4,
        109.9,
        109.5,
        109.0,
        108.6,
        108.1,
        107.7,
        107.2,
        106.8,
        106.3,
        105.9,
        105.4,
        105.0,
        104.5,
        104.1,
        103.6,
        103.2,
        102.7,
        102.3,
        101.8,
        99.0,
    ]
    return _build_candles(closes, final_open=99.8, high_padding=0.2, low_padding=0.3)


def make_order(
    order_type: OrderType,
    entry: float,
    stop_loss: float,
    take_profit: float,
    signal_source: str,
    position_size: float = 10.0,
) -> Order:
    return Order(
        order_type=order_type,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_size=position_size,
        signal_source=signal_source,
    )


def make_signal(
    signal_type: SignalType,
    is_valid: bool,
    reason: str,
    entry: float | None = None,
    stop_loss: float | None = None,
    take_profit: float | None = None,
) -> SignalState:
    return SignalState(
        signal_type=signal_type,
        is_valid=is_valid,
        reason=reason,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def make_trade(
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


def make_strategy_result(
    action: DecisionAction,
    reason: str,
    order: Order | None = None,
    updated_trade: Trade | None = None,
    trend_signal: SignalState | None = None,
    countertrend_signal: SignalState | None = None,
    selected_signal_type: str | None = None,
) -> StrategyRunResult:
    return StrategyRunResult(
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        decision=DecisionResult(
            action=action,
            reason=reason,
            selected_signal_type=selected_signal_type,
        ),
        order=order,
        updated_trade=updated_trade,
    )


def valid_trend_long_scenario() -> StrategyGoldenScenario:
    candles = build_bullish_trend_candles()
    trend_signal = make_signal(
        SignalType.TREND_LONG,
        True,
        "trend signal detected",
        entry=114.0,
        stop_loss=109.0,
        take_profit=124.0,
    )
    return StrategyGoldenScenario(
        name="valid trend long",
        candles=candles,
        config=make_config(),
        trend_signal=trend_signal,
        countertrend_signal=None,
        expected={"decision": DecisionAction.PREPARE_TREND_ORDER},
    )


def invalid_trend_regime_too_old_scenario() -> StrategyGoldenScenario:
    candles = build_bullish_trend_candles()
    trend_signal = make_signal(
        SignalType.TREND_LONG,
        False,
        "regime too old",
    )
    return StrategyGoldenScenario(
        name="invalid trend regime too old",
        candles=candles,
        config=make_config(),
        trend_signal=trend_signal,
        countertrend_signal=None,
    )


def invalid_trend_candle_not_in_direction_scenario() -> StrategyGoldenScenario:
    candles = build_bullish_trend_candles(final_open=113.2)
    trend_signal = make_signal(
        SignalType.TREND_LONG,
        False,
        "candle not in trend direction",
    )
    return StrategyGoldenScenario(
        name="invalid trend candle not in direction",
        candles=candles,
        config=make_config(),
        trend_signal=trend_signal,
        countertrend_signal=None,
    )


def valid_countertrend_short_first_bullish_regime_scenario() -> StrategyGoldenScenario:
    candles = build_spike_above_band_candles()
    last_close = candles[-1].close
    countertrend_signal = make_signal(
        SignalType.COUNTERTREND_SHORT,
        True,
        "countertrend signal detected",
        entry=last_close,
        stop_loss=121.0,
        take_profit=114.0,
    )
    return StrategyGoldenScenario(
        name="valid countertrend short first bullish regime bar",
        candles=candles,
        config=make_config(),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
    )


def valid_countertrend_long_first_bearish_regime_scenario() -> StrategyGoldenScenario:
    candles = build_spike_below_band_candles()
    last_close = candles[-1].close
    countertrend_signal = make_signal(
        SignalType.COUNTERTREND_LONG,
        True,
        "countertrend signal detected",
        entry=last_close,
        stop_loss=97.0,
        take_profit=104.0,
    )
    return StrategyGoldenScenario(
        name="valid countertrend long first bearish regime bar",
        candles=candles,
        config=make_config(),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
    )


def no_countertrend_not_first_regime_bar_scenario() -> StrategyGoldenScenario:
    candles = build_spike_above_band_candles()
    countertrend_signal = make_signal(
        SignalType.COUNTERTREND_SHORT,
        False,
        "not first regime bar",
    )
    return StrategyGoldenScenario(
        name="no countertrend not first regime bar",
        candles=candles,
        config=make_config(),
        trend_signal=None,
        countertrend_signal=countertrend_signal,
    )


def trend_order_should_be_prepared_scenario() -> StrategyGoldenScenario:
    candles = build_bullish_trend_candles()
    order = make_order(
        OrderType.BUY_STOP,
        entry=114.0,
        stop_loss=109.0,
        take_profit=124.0,
        signal_source="trend_long",
    )
    trend_signal = make_signal(
        SignalType.TREND_LONG,
        True,
        "trend signal detected",
        entry=114.0,
        stop_loss=109.0,
        take_profit=124.0,
    )
    return StrategyGoldenScenario(
        name="trend order should be prepared",
        candles=candles,
        config=make_config(),
        state=AgentState(),
        strategy_result=make_strategy_result(
            action=DecisionAction.PREPARE_TREND_ORDER,
            reason="valid trend signal",
            order=order,
            trend_signal=trend_signal,
            countertrend_signal=None,
            selected_signal_type=SignalType.TREND_LONG.value,
        ),
    )


def countertrend_should_override_active_trend_trade_scenario() -> StrategyGoldenScenario:
    candles = build_spike_above_band_candles()
    last_close = candles[-1].close
    trend_signal = make_signal(
        SignalType.TREND_LONG,
        True,
        "trend signal detected",
        entry=118.0,
        stop_loss=112.0,
        take_profit=130.0,
    )
    countertrend_signal = make_signal(
        SignalType.COUNTERTREND_SHORT,
        True,
        "countertrend signal detected",
        entry=last_close,
        stop_loss=121.0,
        take_profit=114.0,
    )
    active_trade = make_trade(
        TradeType.TREND,
        TradeDirection.LONG,
        entry=110.0,
        stop_loss=105.0,
        take_profit=120.0,
    )
    return StrategyGoldenScenario(
        name="countertrend overrides active trend trade",
        candles=candles,
        config=make_config(),
        active_trade=active_trade,
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
    )


def break_even_should_activate_scenario() -> StrategyGoldenScenario:
    candles = build_bullish_trend_candles()
    active_trade = make_trade(
        TradeType.TREND,
        TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )
    return StrategyGoldenScenario(
        name="break even should activate",
        candles=candles,
        config=make_config(),
        active_trade=active_trade,
    )


def countertrend_tp_should_update_scenario() -> StrategyGoldenScenario:
    candles = build_bullish_trend_candles()
    active_trade = make_trade(
        TradeType.COUNTERTREND,
        TradeDirection.SHORT,
        entry=100.0,
        stop_loss=110.0,
        take_profit=95.0,
    )
    return StrategyGoldenScenario(
        name="countertrend tp should update",
        candles=candles,
        config=make_config(),
        active_trade=active_trade,
    )


def trend_signal_consumed_duplicate_order_scenario() -> StrategyGoldenScenario:
    candles = build_bullish_trend_candles()
    order = make_order(
        OrderType.BUY_STOP,
        entry=114.0,
        stop_loss=109.0,
        take_profit=124.0,
        signal_source="trend_long",
    )
    trend_signal = make_signal(
        SignalType.TREND_LONG,
        True,
        "trend signal detected",
        entry=114.0,
        stop_loss=109.0,
        take_profit=124.0,
    )
    state = AgentState(
        trend_signal_consumed_in_regime=True,
        last_regime="bullish",
    )
    return StrategyGoldenScenario(
        name="trend signal consumed duplicate order",
        candles=candles,
        config=make_config(),
        state=state,
        strategy_result=make_strategy_result(
            action=DecisionAction.PREPARE_TREND_ORDER,
            reason="valid trend signal",
            order=order,
            trend_signal=trend_signal,
            countertrend_signal=None,
            selected_signal_type=SignalType.TREND_LONG.value,
        ),
    )


def regime_change_should_reset_consumed_flag_scenario() -> StrategyGoldenScenario:
    candles = build_bullish_trend_candles()
    state = AgentState(
        trend_signal_consumed_in_regime=True,
        last_regime="bearish",
    )
    trend_signal = make_signal(SignalType.TREND_LONG, False, "regime too old")
    return StrategyGoldenScenario(
        name="regime change should reset consumed flag",
        candles=candles,
        config=make_config(),
        state=state,
        strategy_result=make_strategy_result(
            action=DecisionAction.NO_ACTION,
            reason="no valid signal",
            trend_signal=trend_signal,
            countertrend_signal=None,
        ),
    )


__all__ = [
    "StrategyGoldenScenario",
    "build_bullish_trend_candles",
    "build_bearish_trend_candles",
    "build_spike_above_band_candles",
    "build_spike_below_band_candles",
    "make_config",
    "make_trade",
    "valid_trend_long_scenario",
    "invalid_trend_regime_too_old_scenario",
    "invalid_trend_candle_not_in_direction_scenario",
    "valid_countertrend_short_first_bullish_regime_scenario",
    "valid_countertrend_long_first_bearish_regime_scenario",
    "no_countertrend_not_first_regime_bar_scenario",
    "trend_order_should_be_prepared_scenario",
    "countertrend_should_override_active_trend_trade_scenario",
    "break_even_should_activate_scenario",
    "countertrend_tp_should_update_scenario",
    "trend_signal_consumed_duplicate_order_scenario",
    "regime_change_should_reset_consumed_flag_scenario",
]

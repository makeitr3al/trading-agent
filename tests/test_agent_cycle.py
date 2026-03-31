from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.runner_result import StrategyRunResult
from models.signal import SignalState, SignalType
from models.trade import Trade, TradeDirection, TradeType
from strategy.agent_cycle import run_agent_cycle
from models.regime import RegimeState, RegimeType


def _make_candles(count: int = 40) -> list[Candle]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    return [
        Candle(
            timestamp=base_time + timedelta(hours=index),
            open=float(100.0 + index * 0.2 - 0.1),
            high=float(100.0 + index * 0.2 + 0.2),
            low=float(100.0 + index * 0.2 - 0.2),
            close=float(100.0 + index * 0.2),
        )
        for index in range(count)
    ]


def _make_decision(
    action: DecisionAction,
    selected_signal_type: str | None = None,
) -> DecisionResult:
    return DecisionResult(
        action=action,
        reason="test decision",
        selected_signal_type=selected_signal_type,
    )


def _make_trade(trade_type: TradeType) -> Trade:
    direction = TradeDirection.LONG if trade_type == TradeType.TREND else TradeDirection.SHORT
    return Trade(
        trade_type=trade_type,
        direction=direction,
        entry=100.0,
        stop_loss=95.0 if direction == TradeDirection.LONG else 105.0,
        take_profit=110.0 if direction == TradeDirection.LONG else 90.0,
    )


def _make_order() -> Order:
    return Order(
        order_type=OrderType.BUY_STOP,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
        position_size=10.0,
        signal_source="trend_long",
    )


def _make_refreshed_trend_order() -> Order:
    return Order(
        order_type=OrderType.BUY_STOP,
        entry=115.0,
        stop_loss=105.0,
        take_profit=135.0,
        position_size=10.0,
        signal_source="trend_long",
    )


def _make_countertrend_order() -> Order:
    return Order(
        order_type=OrderType.SELL_LIMIT,
        entry=110.0,
        stop_loss=120.0,
        take_profit=100.0,
        position_size=10.0,
        signal_source="countertrend_short",
    )


def _make_pending_order(
    order_type: OrderType,
    signal_source: str,
    entry: float = 110.0,
    stop_loss: float = 100.0,
    take_profit: float = 130.0,
) -> Order:
    return Order(
        order_type=order_type,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_size=10.0,
        signal_source=signal_source,
    )


def _make_result(
    decision: DecisionResult,
    order: Order | None = None,
    updated_trade: Trade | None = None,
    trend_signal: SignalState | None = None,
    countertrend_signal: SignalState | None = None,
    close_active_trade: bool = False,
) -> StrategyRunResult:
    if trend_signal is None:
        trend_signal = SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=decision.action == DecisionAction.PREPARE_TREND_ORDER,
            reason="trend signal detected" if decision.action == DecisionAction.PREPARE_TREND_ORDER else "test",
            entry=110.0,
            stop_loss=100.0,
            take_profit=130.0,
        )
    if countertrend_signal is None:
        countertrend_signal = SignalState(
            signal_type=SignalType.COUNTERTREND_SHORT,
            is_valid=decision.action
            in (
                DecisionAction.PREPARE_COUNTERTREND_ORDER,
                DecisionAction.CLOSE_TREND_AND_PREPARE_COUNTERTREND,
                DecisionAction.CLOSE_TREND_TRADE,
                DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE,
            ),
            reason="countertrend signal detected"
            if decision.action
            in (
                DecisionAction.PREPARE_COUNTERTREND_ORDER,
                DecisionAction.CLOSE_TREND_AND_PREPARE_COUNTERTREND,
                DecisionAction.CLOSE_TREND_TRADE,
                DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE,
            )
            else "test",
            entry=110.0,
            stop_loss=120.0,
            take_profit=100.0,
        )
    return StrategyRunResult(
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        decision=decision,
        order=order,
        updated_trade=updated_trade,
        close_active_trade=close_active_trade,
    )


def _stub_cycle_context(
    monkeypatch,
    candles: list[Candle],
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
    regime: RegimeType = RegimeType.BULLISH,
    bars_since_regime_start: int = 1,
) -> None:
    import pandas as pd

    bollinger_df = pd.DataFrame(
        {
            "bb_upper": [bb_upper] * len(candles),
            "bb_middle": [bb_middle] * len(candles),
            "bb_lower": [bb_lower] * len(candles),
        }
    )
    regime_states = [
        RegimeState(regime=regime, bars_since_regime_start=bars_since_regime_start)
        for _ in candles
    ]

    monkeypatch.setattr(
        "strategy.agent_cycle.compute_bollinger_bands",
        lambda closes, period, std_dev: bollinger_df,
    )
    monkeypatch.setattr(
        "strategy.agent_cycle.build_regime_states",
        lambda macd_df: regime_states,
    )


def test_run_agent_cycle_returns_result_and_new_state(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState()
    decision = _make_decision(DecisionAction.NO_ACTION)
    result_stub = _make_result(decision=decision)

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    result, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert isinstance(result, StrategyRunResult)
    assert isinstance(new_state, AgentState)
    assert new_state.last_decision_action == "NO_ACTION"
    assert new_state.last_cycle_timestamp == candles[-1].timestamp.isoformat()


def test_run_agent_cycle_carries_forward_active_trade_when_updated_trade_exists(
    monkeypatch,
) -> None:
    candles = _make_candles()
    updated_trade = _make_trade(TradeType.TREND)
    state = AgentState(active_trade=_make_trade(TradeType.TREND))
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.KEEP_EXISTING_TREND_TRADE),
        updated_trade=updated_trade,
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.active_trade is not None


def test_run_agent_cycle_stamps_created_at_on_new_pending_order(
    monkeypatch,
) -> None:
    candles = _make_candles()
    order = _make_order()
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_TREND_ORDER,
            selected_signal_type="TREND_LONG",
        ),
        order=order,
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=AgentState(),
    )

    assert new_state.pending_order is not None
    assert new_state.pending_order.created_at == candles[-1].timestamp.isoformat()



def test_run_agent_cycle_preserves_created_at_on_unchanged_pending_order(
    monkeypatch,
) -> None:
    candles = _make_candles()
    existing_created_at = candles[-2].timestamp.isoformat()
    pending_order = _make_pending_order(
        OrderType.BUY_STOP,
        "manual_pending_order",
    ).model_copy(update={"created_at": existing_created_at})
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=AgentState(pending_order=pending_order),
    )

    assert new_state.pending_order is not None
    assert new_state.pending_order.created_at == existing_created_at



def test_run_agent_cycle_refreshes_created_at_when_trend_pending_order_is_rebuilt(
    monkeypatch,
) -> None:
    candles = _make_candles()
    old_created_at = candles[-2].timestamp.isoformat()
    old_order = _make_order().model_copy(update={"created_at": old_created_at})
    refreshed_signal = SignalState(
        signal_type=SignalType.TREND_LONG,
        is_valid=True,
        reason="trend signal detected",
        entry=115.0,
        stop_loss=105.0,
        take_profit=135.0,
    )
    state = AgentState(pending_order=old_order)
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
        trend_signal=refreshed_signal,
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.pending_order is not None
    assert new_state.pending_order.created_at == candles[-1].timestamp.isoformat()
    assert new_state.pending_order.created_at != old_created_at



def test_run_agent_cycle_stores_pending_order_when_strategy_runner_returns_an_order(
    monkeypatch,
) -> None:
    candles = _make_candles()
    order = _make_order()
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_TREND_ORDER,
            selected_signal_type="TREND_LONG",
        ),
        order=order,
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=AgentState(),
    )

    assert new_state.pending_order is not None


def test_run_agent_cycle_stores_selected_signal_type_when_decision_selected_signal_exists(
    monkeypatch,
) -> None:
    candles = _make_candles()
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_COUNTERTREND_ORDER,
            selected_signal_type="COUNTERTREND_SHORT",
        ),
        order=_make_order(),
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=AgentState(),
    )

    assert new_state.last_signal_type == "COUNTERTREND_SHORT"


def test_run_agent_cycle_marks_trend_signal_consumed_when_prepare_trend_order_happens(
    monkeypatch,
) -> None:
    candles = _make_candles()
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_TREND_ORDER,
            selected_signal_type="TREND_LONG",
        ),
        order=_make_order(),
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=AgentState(),
    )

    assert new_state.trend_signal_consumed_in_regime is True


def test_run_agent_cycle_preserves_trend_signal_consumed_flag_when_no_new_trend_order_occurs(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState(trend_signal_consumed_in_regime=True)
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.trend_signal_consumed_in_regime is True


def test_run_agent_cycle_deletes_old_countertrend_pending_order_when_no_new_order_is_generated(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState(pending_order=_make_countertrend_order())
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.pending_order is None


def test_run_agent_cycle_deletes_unfilled_countertrend_pending_order_when_signal_is_no_longer_valid_next_day(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"high": 109.0, "low": 108.5})
    state = AgentState(
        pending_order=_make_pending_order(
            OrderType.SELL_LIMIT,
            "countertrend_short",
            entry=110.0,
            stop_loss=120.0,
            take_profit=100.0,
        )
    )
    invalid_countertrend_signal = SignalState(
        signal_type=SignalType.COUNTERTREND_SHORT,
        is_valid=False,
        reason="close not outside bands",
        entry=110.0,
        stop_loss=120.0,
        take_profit=100.0,
    )
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
        countertrend_signal=invalid_countertrend_signal,
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.active_trade is None
    assert new_state.pending_order is None


def test_run_agent_cycle_blocks_duplicate_countertrend_short_signal_in_same_regime(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState(
        last_regime="bullish",
        countertrend_short_signal_consumed_in_regime=True,
    )
    valid_countertrend_signal = SignalState(
        signal_type=SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="countertrend signal detected",
        entry=110.0,
        stop_loss=120.0,
        take_profit=100.0,
    )
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_COUNTERTREND_ORDER,
            selected_signal_type="COUNTERTREND_SHORT",
        ),
        order=_make_countertrend_order(),
        countertrend_signal=valid_countertrend_signal,
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    result, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is False
    assert result.countertrend_signal.reason == "countertrend regime direction consumed"
    assert result.decision.action == DecisionAction.NO_ACTION
    assert new_state.pending_order is None
    assert new_state.countertrend_short_signal_consumed_in_regime is True


def test_run_agent_cycle_allows_current_outside_close_countertrend_signal_and_sets_middle_band_retest_lock(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"close": 106.5, "high": 107.0, "low": 105.5})
    _stub_cycle_context(
        monkeypatch,
        candles=candles,
        bb_upper=105.0,
        bb_middle=100.0,
        bb_lower=95.0,
        regime=RegimeType.BULLISH,
        bars_since_regime_start=1,
    )
    valid_countertrend_signal = SignalState(
        signal_type=SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="countertrend signal detected",
        entry=106.5,
        stop_loss=113.0,
        take_profit=100.0,
    )
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_COUNTERTREND_ORDER,
            selected_signal_type="COUNTERTREND_SHORT",
        ),
        order=_make_countertrend_order(),
        countertrend_signal=valid_countertrend_signal,
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    result, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=AgentState(),
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is True
    assert result.decision.action == DecisionAction.PREPARE_COUNTERTREND_ORDER
    assert new_state.middle_band_retest_required is True


def test_run_agent_cycle_blocks_follow_up_countertrend_signal_until_middle_band_retest(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"close": 106.5, "high": 107.0, "low": 105.5})
    _stub_cycle_context(
        monkeypatch,
        candles=candles,
        bb_upper=105.0,
        bb_middle=100.0,
        bb_lower=95.0,
        regime=RegimeType.BULLISH,
        bars_since_regime_start=1,
    )
    valid_countertrend_signal = SignalState(
        signal_type=SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="countertrend signal detected",
        entry=106.5,
        stop_loss=113.0,
        take_profit=100.0,
    )
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_COUNTERTREND_ORDER,
            selected_signal_type="COUNTERTREND_SHORT",
        ),
        order=_make_countertrend_order(),
        countertrend_signal=valid_countertrend_signal,
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    result, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=AgentState(middle_band_retest_required=True),
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is False
    assert result.countertrend_signal.reason == "waiting for middle band retest"
    assert result.decision.action == DecisionAction.NO_ACTION
    assert new_state.pending_order is None
    assert new_state.middle_band_retest_required is True


def test_run_agent_cycle_middle_band_touch_unlocks_for_next_bar_but_current_bar_stays_blocked(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"close": 102.0, "high": 102.5, "low": 99.5})
    _stub_cycle_context(
        monkeypatch,
        candles=candles,
        bb_upper=105.0,
        bb_middle=100.0,
        bb_lower=95.0,
        regime=RegimeType.BULLISH,
        bars_since_regime_start=1,
    )
    valid_trend_signal = SignalState(
        signal_type=SignalType.TREND_LONG,
        is_valid=True,
        reason="trend signal detected",
        entry=105.0,
        stop_loss=100.0,
        take_profit=115.0,
    )
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_TREND_ORDER,
            selected_signal_type="TREND_LONG",
        ),
        order=_make_order(),
        trend_signal=valid_trend_signal,
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    result, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=AgentState(middle_band_retest_required=True),
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is False
    assert result.trend_signal.reason == "waiting for middle band retest"
    assert result.decision.action == DecisionAction.NO_ACTION
    assert new_state.middle_band_retest_required is False


def test_run_agent_cycle_sets_middle_band_retest_lock_for_sweet_spot_close_outside_bands_without_countertrend_signal(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"close": 105.5, "high": 105.8, "low": 105.2})
    _stub_cycle_context(
        monkeypatch,
        candles=candles,
        bb_upper=105.0,
        bb_middle=100.0,
        bb_lower=95.0,
        regime=RegimeType.BULLISH,
        bars_since_regime_start=1,
    )
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
        countertrend_signal=SignalState(
            signal_type=SignalType.COUNTERTREND_SHORT,
            is_valid=False,
            reason="close not outside bands",
        ),
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(outside_band_sweet_spot_pct=1.0),
        account_balance=10000.0,
        state=AgentState(),
    )

    assert new_state.middle_band_retest_required is True


def test_run_agent_cycle_does_not_set_middle_band_retest_lock_for_sweet_spot_close_inside_bands(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"close": 104.5, "high": 104.8, "low": 104.0})
    _stub_cycle_context(
        monkeypatch,
        candles=candles,
        bb_upper=105.0,
        bb_middle=100.0,
        bb_lower=95.0,
        regime=RegimeType.BULLISH,
        bars_since_regime_start=1,
    )
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
        countertrend_signal=SignalState(
            signal_type=SignalType.COUNTERTREND_SHORT,
            is_valid=False,
            reason="close not outside bands",
        ),
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(outside_band_sweet_spot_pct=1.0),
        account_balance=10000.0,
        state=AgentState(),
    )

    assert new_state.middle_band_retest_required is False


def test_run_agent_cycle_resets_countertrend_consumed_flags_on_regime_change(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState(
        last_regime="bearish",
        countertrend_long_signal_consumed_in_regime=True,
        countertrend_short_signal_consumed_in_regime=True,
    )
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.countertrend_long_signal_consumed_in_regime is False
    assert new_state.countertrend_short_signal_consumed_in_regime is False


def test_run_agent_cycle_replaces_old_trend_pending_order_with_refreshed_trend_order_when_current_trend_signal_is_still_valid(
    monkeypatch,
) -> None:
    candles = _make_candles()
    old_order = _make_order()
    refreshed_signal = SignalState(
        signal_type=SignalType.TREND_LONG,
        is_valid=True,
        reason="trend signal detected",
        entry=115.0,
        stop_loss=105.0,
        take_profit=135.0,
    )
    state = AgentState(pending_order=old_order)
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
        trend_signal=refreshed_signal,
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.pending_order is not None
    assert new_state.pending_order != old_order
    assert new_state.pending_order.entry == 115.0
    assert new_state.pending_order.stop_loss == 105.0
    assert new_state.pending_order.take_profit == 135.0
    assert new_state.pending_order.signal_source == "trend_long"


def test_run_agent_cycle_replaces_old_pending_order_when_a_new_order_is_generated(
    monkeypatch,
) -> None:
    candles = _make_candles()
    old_order = _make_countertrend_order()
    new_order = _make_order()
    state = AgentState(pending_order=old_order)
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.PREPARE_TREND_ORDER,
            selected_signal_type="TREND_LONG",
        ),
        order=new_order,
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.pending_order is not None
    assert new_state.pending_order != old_order
    assert new_state.pending_order.entry == new_order.entry
    assert new_state.pending_order.stop_loss == new_order.stop_loss
    assert new_state.pending_order.take_profit == new_order.take_profit
    assert new_state.pending_order.position_size == new_order.position_size
    assert new_state.pending_order.signal_source == new_order.signal_source
    assert new_state.pending_order.created_at == candles[-1].timestamp.isoformat()


def test_run_agent_cycle_deletes_old_trend_pending_order_when_current_trend_signal_is_no_longer_valid(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState(pending_order=_make_order())
    invalid_trend_signal = SignalState(
        signal_type=SignalType.TREND_LONG,
        is_valid=False,
        reason="regime too old",
        entry=115.0,
        stop_loss=105.0,
        take_profit=135.0,
    )
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
        trend_signal=invalid_trend_signal,
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.pending_order is None


def test_run_agent_cycle_does_not_refresh_trend_pending_order_with_mismatching_signal_type(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState(pending_order=_make_order())
    mismatching_trend_signal = SignalState(
        signal_type=SignalType.TREND_SHORT,
        is_valid=True,
        reason="trend signal detected",
        entry=95.0,
        stop_loss=105.0,
        take_profit=75.0,
    )
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
        trend_signal=mismatching_trend_signal,
    )

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.pending_order is None


def test_run_agent_cycle_resets_trend_signal_consumed_in_regime_on_regime_change(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState(
        last_regime="bearish",
        trend_signal_consumed_in_regime=True,
    )
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr("strategy.agent_cycle.run_strategy_cycle", lambda candles, config, account_balance, active_trade: result_stub)

    _, new_state = run_agent_cycle(
        candles=candles,
        config=StrategyConfig(),
        account_balance=10000.0,
        state=state,
    )

    assert new_state.trend_signal_consumed_in_regime is False


def test_run_agent_cycle_fills_buy_stop_pending_order_into_active_long_trade(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"high": 110.5})
    pending_order = _make_pending_order(OrderType.BUY_STOP, "trend_long")
    state = AgentState(pending_order=pending_order)
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade is not None
    assert new_state.active_trade.direction == TradeDirection.LONG
    assert new_state.active_trade.trade_type == TradeType.TREND
    assert new_state.pending_order is None


def test_run_agent_cycle_fills_sell_stop_pending_order_into_active_short_trade(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"low": 109.5})
    pending_order = _make_pending_order(
        OrderType.SELL_STOP,
        "trend_short",
        entry=110.0,
        stop_loss=120.0,
        take_profit=90.0,
    )
    state = AgentState(pending_order=pending_order)
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade is not None
    assert new_state.active_trade.direction == TradeDirection.SHORT


def test_run_agent_cycle_fills_buy_limit_pending_order_into_active_long_trade(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"low": 109.5})
    pending_order = _make_pending_order(OrderType.BUY_LIMIT, "countertrend_long")
    state = AgentState(pending_order=pending_order)
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade is not None
    assert new_state.active_trade.direction == TradeDirection.LONG


def test_run_agent_cycle_fills_sell_limit_pending_order_into_active_short_trade(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"high": 110.5})
    pending_order = _make_pending_order(
        OrderType.SELL_LIMIT,
        "countertrend_short",
        entry=110.0,
        stop_loss=120.0,
        take_profit=100.0,
    )
    state = AgentState(pending_order=pending_order)
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade is not None
    assert new_state.active_trade.direction == TradeDirection.SHORT


def test_run_agent_cycle_does_not_fill_pending_order_if_candle_does_not_reach_entry(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"high": 109.0, "low": 108.5})
    pending_order = _make_order()
    state = AgentState(pending_order=pending_order)
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.NO_ACTION),
        trend_signal=SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=True,
            reason="trend signal detected",
            entry=115.0,
            stop_loss=105.0,
            take_profit=135.0,
        ),
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade is None
    assert new_state.pending_order is not None


def test_run_agent_cycle_filled_trend_order_becomes_trend_trade(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"high": 110.5})
    state = AgentState(pending_order=_make_pending_order(OrderType.BUY_STOP, "trend_long"))
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade is not None
    assert new_state.active_trade.trade_type == TradeType.TREND


def test_run_agent_cycle_filled_countertrend_order_becomes_countertrend_trade(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"high": 110.5})
    state = AgentState(
        pending_order=_make_pending_order(
            OrderType.SELL_LIMIT,
            "countertrend_short",
            stop_loss=120.0,
            take_profit=100.0,
        )
    )
    result_stub = _make_result(decision=_make_decision(DecisionAction.NO_ACTION))

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade is not None
    assert new_state.active_trade.trade_type == TradeType.COUNTERTREND


def test_run_agent_cycle_filled_order_can_still_be_updated_by_later_trade_manager_logic_in_same_cycle(
    monkeypatch,
) -> None:
    candles = _make_candles()
    candles[-1] = candles[-1].model_copy(update={"high": 110.5})
    filled_pending_order = _make_pending_order(OrderType.BUY_STOP, "trend_long")
    updated_trade = Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=110.0,
        stop_loss=110.0,
        take_profit=130.0,
        break_even_activated=True,
    )
    state = AgentState(pending_order=filled_pending_order)
    result_stub = _make_result(
        decision=_make_decision(DecisionAction.KEEP_EXISTING_TREND_TRADE),
        updated_trade=updated_trade,
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade == updated_trade


def test_run_agent_cycle_clears_active_trade_when_strategy_requests_close(
    monkeypatch,
) -> None:
    candles = _make_candles()
    state = AgentState(active_trade=_make_trade(TradeType.TREND), last_regime="bullish")
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.CLOSE_TREND_TRADE,
            selected_signal_type="COUNTERTREND_SHORT",
        ),
        close_active_trade=True,
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade is None
    assert new_state.trend_signal_consumed_in_regime is True


def test_run_agent_cycle_keeps_tightened_trend_stop_when_strategy_requests_last_close_stop(
    monkeypatch,
) -> None:
    candles = _make_candles()
    tightened_trade = Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=108.0,
        take_profit=110.0,
    )
    state = AgentState(active_trade=_make_trade(TradeType.TREND), last_regime="bullish")
    result_stub = _make_result(
        decision=_make_decision(
            DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE,
            selected_signal_type="COUNTERTREND_SHORT",
        ),
        updated_trade=tightened_trade,
    )

    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: result_stub,
    )

    _, new_state = run_agent_cycle(candles, StrategyConfig(), 10000.0, state)

    assert new_state.active_trade == tightened_trade
    assert new_state.trend_signal_consumed_in_regime is True


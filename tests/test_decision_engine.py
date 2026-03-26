from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.decision import DecisionAction
from models.signal import SignalState, SignalType
from models.trade import Trade, TradeDirection, TradeType
from strategy.decision_engine import decide_next_action


def _make_signal(signal_type: SignalType, is_valid: bool, reason: str) -> SignalState:
    return SignalState(
        signal_type=signal_type,
        is_valid=is_valid,
        reason=reason,
    )


def _make_trade(trade_type: TradeType) -> Trade:
    direction = TradeDirection.LONG if trade_type == TradeType.TREND else TradeDirection.SHORT
    return Trade(
        trade_type=trade_type,
        direction=direction,
        entry=100.0,
        stop_loss=99.0,
        take_profit=102.0,
    )


def test_decide_next_action_valid_countertrend_with_active_trend_trade() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="countertrend signal detected",
    )
    active_trade = _make_trade(TradeType.TREND)

    result = decide_next_action(
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        active_trade=active_trade,
    )

    assert result.action == DecisionAction.CLOSE_TREND_AND_PREPARE_COUNTERTREND
    assert result.reason == "valid countertrend overrides active trend trade"
    assert result.selected_signal_type == SignalType.COUNTERTREND_SHORT.value


def test_decide_next_action_valid_countertrend_without_active_trade() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_LONG,
        is_valid=True,
        reason="countertrend signal detected",
    )

    result = decide_next_action(
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        active_trade=None,
    )

    assert result.action == DecisionAction.PREPARE_COUNTERTREND_ORDER
    assert result.reason == "valid countertrend signal"
    assert result.selected_signal_type == SignalType.COUNTERTREND_LONG.value


def test_decide_next_action_valid_trend_without_active_trade() -> None:
    trend_signal = _make_signal(
        SignalType.TREND_LONG,
        is_valid=True,
        reason="trend signal detected",
    )

    result = decide_next_action(
        trend_signal=trend_signal,
        countertrend_signal=None,
        active_trade=None,
    )

    assert result.action == DecisionAction.PREPARE_TREND_ORDER
    assert result.reason == "valid trend signal"
    assert result.selected_signal_type == SignalType.TREND_LONG.value


def test_decide_next_action_valid_trend_with_active_trend_trade() -> None:
    trend_signal = _make_signal(
        SignalType.TREND_SHORT,
        is_valid=True,
        reason="trend signal detected",
    )
    active_trade = _make_trade(TradeType.TREND)

    result = decide_next_action(
        trend_signal=trend_signal,
        countertrend_signal=None,
        active_trade=active_trade,
    )

    assert result.action == DecisionAction.KEEP_EXISTING_TREND_TRADE
    assert result.reason == "trend trade already active"
    assert result.selected_signal_type == SignalType.TREND_SHORT.value


def test_decide_next_action_no_valid_signals() -> None:
    trend_signal = _make_signal(
        SignalType.TREND_LONG,
        is_valid=False,
        reason="regime too old",
    )
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_SHORT,
        is_valid=False,
        reason="not first regime bar",
    )

    result = decide_next_action(
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        active_trade=None,
    )

    assert result.action == DecisionAction.NO_ACTION
    assert result.reason == "no valid signal"
    assert result.selected_signal_type is None


def test_decide_next_action_valid_countertrend_has_priority_over_valid_trend() -> None:
    trend_signal = _make_signal(
        SignalType.TREND_LONG,
        is_valid=True,
        reason="trend signal detected",
    )
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="countertrend signal detected",
    )

    result = decide_next_action(
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        active_trade=None,
    )

    assert result.action == DecisionAction.PREPARE_COUNTERTREND_ORDER
    assert result.selected_signal_type == SignalType.COUNTERTREND_SHORT.value

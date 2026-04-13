from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.decision import DecisionAction
from models.signal import SignalState, SignalType
from models.trade import Trade, TradeDirection, TradeType
from strategy.decision_engine import decide_next_action


def _make_signal(
    signal_type: SignalType,
    is_valid: bool,
    reason: str,
    *,
    signal_bar_close: float | None = None,
) -> SignalState:
    return SignalState(
        signal_type=signal_type,
        is_valid=is_valid,
        reason=reason,
        signal_bar_close=signal_bar_close,
    )


def _make_trade(trade_type: TradeType, direction: TradeDirection = TradeDirection.LONG) -> Trade:
    return Trade(
        trade_type=trade_type,
        direction=direction,
        entry=100.0,
        stop_loss=99.0 if direction == TradeDirection.LONG else 101.0,
        take_profit=102.0 if direction == TradeDirection.LONG else 98.0,
    )


def test_decide_next_action_valid_countertrend_with_active_trend_trade_can_tighten_stop() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="countertrend signal detected",
        signal_bar_close=99.5,
    )
    active_trade = _make_trade(TradeType.TREND, direction=TradeDirection.LONG)

    result = decide_next_action(
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        active_trade=active_trade,
        current_price=101.0,
    )

    assert result.action == DecisionAction.ADJUST_TREND_STOP_TO_SIGNAL_BAR_CLOSE
    assert result.reason == "valid countertrend locks trend stop to countertrend signal-bar close"
    assert result.selected_signal_type == SignalType.COUNTERTREND_SHORT.value


def test_decide_next_action_valid_countertrend_with_active_trend_trade_can_close_market() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_LONG,
        is_valid=True,
        reason="countertrend signal detected",
        signal_bar_close=99.0,
    )
    active_trade = _make_trade(TradeType.TREND, direction=TradeDirection.SHORT)

    result = decide_next_action(
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        active_trade=active_trade,
        current_price=101.5,
    )

    assert result.action == DecisionAction.CLOSE_TREND_TRADE
    assert result.reason == "valid countertrend closes active trend trade (price above signal-bar close)"
    assert result.selected_signal_type == SignalType.COUNTERTREND_LONG.value


def test_decide_next_action_countertrend_without_signal_bar_close_uses_legacy_last_close_rule() -> None:
    countertrend_signal = _make_signal(
        SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="countertrend signal detected",
    )
    active_trade = _make_trade(TradeType.TREND, direction=TradeDirection.LONG)

    result = decide_next_action(
        trend_signal=None,
        countertrend_signal=countertrend_signal,
        active_trade=active_trade,
        current_price=101.0,
    )

    assert result.action == DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE
    assert result.reason == "valid countertrend locks trend stop to last close"


def test_decide_next_action_outer_band_exit_trigger_can_tighten_stop_without_countertrend_signal() -> None:
    active_trade = _make_trade(TradeType.TREND, direction=TradeDirection.LONG)

    result = decide_next_action(
        trend_signal=None,
        countertrend_signal=None,
        active_trade=active_trade,
        current_price=101.0,
        trend_exit_triggered=True,
    )

    assert result.action == DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE
    assert result.reason == "outer band exit trigger locks trend stop to last close"
    assert result.selected_signal_type is None


def test_decide_next_action_outer_band_exit_trigger_can_close_market_without_countertrend_signal() -> None:
    active_trade = _make_trade(TradeType.TREND, direction=TradeDirection.SHORT)

    result = decide_next_action(
        trend_signal=None,
        countertrend_signal=None,
        active_trade=active_trade,
        current_price=101.5,
        trend_exit_triggered=True,
    )

    assert result.action == DecisionAction.CLOSE_TREND_TRADE
    assert result.reason == "outer band exit trigger closes active trend trade"
    assert result.selected_signal_type is None


def test_decide_next_action_countertrend_close_trigger_closes_active_countertrend_trade() -> None:
    active_trade = _make_trade(TradeType.COUNTERTREND, direction=TradeDirection.LONG)

    result = decide_next_action(
        trend_signal=None,
        countertrend_signal=None,
        active_trade=active_trade,
        current_price=100.5,
        countertrend_close_triggered=True,
    )

    assert result.action == DecisionAction.CLOSE_COUNTERTREND_TRADE
    assert result.reason == "middle band touch closes active countertrend trade"
    assert result.selected_signal_type is None


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
        current_price=100.0,
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
        current_price=100.0,
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
        current_price=100.0,
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
        current_price=100.0,
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
        current_price=100.0,
    )

    assert result.action == DecisionAction.PREPARE_COUNTERTREND_ORDER
    assert result.selected_signal_type == SignalType.COUNTERTREND_SHORT.value

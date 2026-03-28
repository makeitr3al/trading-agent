from models.decision import DecisionAction, DecisionResult
from models.signal import SignalState
from models.trade import Trade, TradeDirection, TradeType

# TODO: Later consider pending orders.
# TODO: Later add trade management beyond the aggressive reversal principle.
# TODO: Later add support for later countertrend setups.


def _can_tighten_stop_to_last_close(active_trade: Trade, latest_close: float) -> bool:
    if active_trade.direction == TradeDirection.LONG:
        return latest_close > active_trade.entry and latest_close > active_trade.stop_loss
    return latest_close < active_trade.entry and latest_close < active_trade.stop_loss


def decide_next_action(
    trend_signal: SignalState | None,
    countertrend_signal: SignalState | None,
    active_trade: Trade | None,
    current_price: float,
    trend_exit_triggered: bool = False,
    countertrend_close_triggered: bool = False,
) -> DecisionResult:
    valid_countertrend = countertrend_signal is not None and countertrend_signal.is_valid
    active_trend_trade = active_trade is not None and active_trade.trade_type == TradeType.TREND
    active_countertrend_trade = (
        active_trade is not None and active_trade.trade_type == TradeType.COUNTERTREND
    )

    if active_countertrend_trade and countertrend_close_triggered:
        return DecisionResult(
            action=DecisionAction.CLOSE_COUNTERTREND_TRADE,
            reason="middle band touch closes active countertrend trade",
            selected_signal_type=None,
        )

    if active_trend_trade and (valid_countertrend or trend_exit_triggered):
        selected_signal_type = (
            countertrend_signal.signal_type.value if valid_countertrend else None
        )
        reason_prefix = "valid countertrend" if valid_countertrend else "outer band exit trigger"

        if _can_tighten_stop_to_last_close(active_trade, current_price):
            return DecisionResult(
                action=DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE,
                reason=f"{reason_prefix} locks trend stop to last close",
                selected_signal_type=selected_signal_type,
            )

        return DecisionResult(
            action=DecisionAction.CLOSE_TREND_TRADE,
            reason=f"{reason_prefix} closes active trend trade",
            selected_signal_type=selected_signal_type,
        )

    if valid_countertrend:
        return DecisionResult(
            action=DecisionAction.PREPARE_COUNTERTREND_ORDER,
            reason="valid countertrend signal",
            selected_signal_type=countertrend_signal.signal_type.value,
        )

    if trend_signal is not None and trend_signal.is_valid:
        if active_trend_trade:
            return DecisionResult(
                action=DecisionAction.KEEP_EXISTING_TREND_TRADE,
                reason="trend trade already active",
                selected_signal_type=trend_signal.signal_type.value,
            )

        return DecisionResult(
            action=DecisionAction.PREPARE_TREND_ORDER,
            reason="valid trend signal",
            selected_signal_type=trend_signal.signal_type.value,
        )

    return DecisionResult(
        action=DecisionAction.NO_ACTION,
        reason="no valid signal",
        selected_signal_type=None,
    )

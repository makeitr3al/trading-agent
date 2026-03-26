from models.decision import DecisionAction, DecisionResult
from models.signal import SignalState
from models.trade import Trade, TradeType

# TODO: Later consider pending orders.
# TODO: Later add trade management beyond the aggressive reversal principle.
# TODO: Later add support for later countertrend setups.


def decide_next_action(
    trend_signal: SignalState | None,
    countertrend_signal: SignalState | None,
    active_trade: Trade | None,
) -> DecisionResult:
    if countertrend_signal is not None and countertrend_signal.is_valid:
        if active_trade is not None and active_trade.trade_type == TradeType.TREND:
            return DecisionResult(
                action=DecisionAction.CLOSE_TREND_AND_PREPARE_COUNTERTREND,
                reason="valid countertrend overrides active trend trade",
                selected_signal_type=countertrend_signal.signal_type.value,
            )

        return DecisionResult(
            action=DecisionAction.PREPARE_COUNTERTREND_ORDER,
            reason="valid countertrend signal",
            selected_signal_type=countertrend_signal.signal_type.value,
        )

    if trend_signal is not None and trend_signal.is_valid:
        if active_trade is not None and active_trade.trade_type == TradeType.TREND:
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

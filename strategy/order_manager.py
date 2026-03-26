from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.signal import SignalState, SignalType

# TODO: Later replace or cancel existing pending orders.
# TODO: Later add repricing logic.
# TODO: Later set created_at.
# TODO: Later add symbol-specific contract, pip, and tick logic for live trading.
# TODO: Later add broker-specific fields.


def build_order_from_decision(
    decision: DecisionResult,
    trend_signal: SignalState | None,
    countertrend_signal: SignalState | None,
    current_price: float,
    account_balance: float,
    risk_per_trade_pct: float,
) -> Order | None:
    if decision.action in (
        DecisionAction.NO_ACTION,
        DecisionAction.KEEP_EXISTING_TREND_TRADE,
    ):
        return None

    if decision.action == DecisionAction.PREPARE_TREND_ORDER:
        if trend_signal is None or not trend_signal.is_valid:
            return None

        if (
            trend_signal.entry is None
            or trend_signal.stop_loss is None
            or trend_signal.take_profit is None
        ):
            return None

        risk_amount = account_balance * risk_per_trade_pct
        risk_per_unit = abs(trend_signal.entry - trend_signal.stop_loss)
        if risk_per_unit <= 0:
            return None

        position_size = risk_amount / risk_per_unit

        if trend_signal.signal_type == SignalType.TREND_LONG:
            order_type = OrderType.BUY_STOP
        elif trend_signal.signal_type == SignalType.TREND_SHORT:
            order_type = OrderType.SELL_STOP
        else:
            return None

        return Order(
            order_type=order_type,
            entry=trend_signal.entry,
            stop_loss=trend_signal.stop_loss,
            take_profit=trend_signal.take_profit,
            position_size=position_size,
            signal_source=trend_signal.signal_type.value.lower(),
        )

    if decision.action in (
        DecisionAction.PREPARE_COUNTERTREND_ORDER,
        DecisionAction.CLOSE_TREND_AND_PREPARE_COUNTERTREND,
    ):
        if countertrend_signal is None or not countertrend_signal.is_valid:
            return None

        if (
            countertrend_signal.entry is None
            or countertrend_signal.stop_loss is None
            or countertrend_signal.take_profit is None
        ):
            return None

        risk_amount = account_balance * risk_per_trade_pct
        risk_per_unit = abs(countertrend_signal.entry - countertrend_signal.stop_loss)
        if risk_per_unit <= 0:
            return None

        position_size = risk_amount / risk_per_unit

        if countertrend_signal.signal_type == SignalType.COUNTERTREND_SHORT:
            order_type = (
                OrderType.SELL_LIMIT
                if current_price >= countertrend_signal.entry
                else OrderType.SELL_STOP
            )
        elif countertrend_signal.signal_type == SignalType.COUNTERTREND_LONG:
            order_type = (
                OrderType.BUY_LIMIT
                if current_price >= countertrend_signal.entry
                else OrderType.BUY_STOP
            )
        else:
            return None

        return Order(
            order_type=order_type,
            entry=countertrend_signal.entry,
            stop_loss=countertrend_signal.stop_loss,
            take_profit=countertrend_signal.take_profit,
            position_size=position_size,
            signal_source=countertrend_signal.signal_type.value.lower(),
        )

    return None

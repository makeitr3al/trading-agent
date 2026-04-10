from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.signal import SignalState, SignalType
from strategy.position_sizer import calculate_position_size


def _normalize_buy_spread(buy_spread: float) -> float:
    return max(0.0, float(buy_spread))


def _is_buy_order_type(order_type: OrderType) -> bool:
    return order_type in {OrderType.BUY_LIMIT, OrderType.BUY_STOP}


def _apply_buy_spread_to_levels(
    order_type: OrderType,
    entry: float,
    stop_loss: float,
    take_profit: float,
    buy_spread: float,
) -> tuple[float, float, float]:
    if not _is_buy_order_type(order_type):
        return entry, stop_loss, take_profit

    normalized_spread = _normalize_buy_spread(buy_spread)
    if normalized_spread == 0:
        return entry, stop_loss, take_profit

    return (
        entry + normalized_spread,
        stop_loss + normalized_spread,
        take_profit + normalized_spread,
    )


def build_order_from_decision(
    decision: DecisionResult,
    trend_signal: SignalState | None,
    countertrend_signal: SignalState | None,
    current_price: float,
    account_balance: float,
    risk_per_trade_pct: float,
    buy_spread: float = 0.0,
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

        sizing = calculate_position_size(
            entry=trend_signal.entry,
            stop_loss=trend_signal.stop_loss,
            account_balance=account_balance,
            risk_per_trade_pct=risk_per_trade_pct,
        )
        if sizing.position_size is None:
            return None
        position_size = sizing.position_size

        if trend_signal.signal_type == SignalType.TREND_LONG:
            order_type = OrderType.BUY_STOP
        elif trend_signal.signal_type == SignalType.TREND_SHORT:
            order_type = OrderType.SELL_STOP
        else:
            return None

        entry, stop_loss, take_profit = _apply_buy_spread_to_levels(
            order_type=order_type,
            entry=trend_signal.entry,
            stop_loss=trend_signal.stop_loss,
            take_profit=trend_signal.take_profit,
            buy_spread=buy_spread,
        )

        return Order(
            order_type=order_type,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
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

        sizing = calculate_position_size(
            entry=countertrend_signal.entry,
            stop_loss=countertrend_signal.stop_loss,
            account_balance=account_balance,
            risk_per_trade_pct=risk_per_trade_pct,
        )
        if sizing.position_size is None:
            return None
        position_size = sizing.position_size

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

        entry, stop_loss, take_profit = _apply_buy_spread_to_levels(
            order_type=order_type,
            entry=countertrend_signal.entry,
            stop_loss=countertrend_signal.stop_loss,
            take_profit=countertrend_signal.take_profit,
            buy_spread=buy_spread,
        )

        return Order(
            order_type=order_type,
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            signal_source=countertrend_signal.signal_type.value.lower(),
        )

    return None

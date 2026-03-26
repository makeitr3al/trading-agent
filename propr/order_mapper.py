from models.order import Order, OrderType


def map_internal_order_to_propr_payload(order: Order, symbol: str) -> dict:
    if not symbol or not symbol.strip():
        raise ValueError("symbol is required")
    if order.position_size is None:
        raise ValueError("position_size is required")
    if order.position_size <= 0:
        raise ValueError("position_size must be positive")

    if order.order_type == OrderType.BUY_STOP:
        side = "buy"
        order_type = "stop"
    elif order.order_type == OrderType.SELL_STOP:
        side = "sell"
        order_type = "stop"
    elif order.order_type == OrderType.BUY_LIMIT:
        side = "buy"
        order_type = "limit"
    elif order.order_type == OrderType.SELL_LIMIT:
        side = "sell"
        order_type = "limit"
    else:
        raise ValueError("unsupported order type")

    return {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "quantity": order.position_size,
        "price": order.entry,
        "stopLoss": order.stop_loss,
        "takeProfit": order.take_profit,
        "clientMetadata": {"signal_source": order.signal_source},
    }


def map_cancel_order_payload(order_id: str) -> dict:
    if not order_id or not order_id.strip():
        raise ValueError("order_id is required")
    return {"orderId": order_id}

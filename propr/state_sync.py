from typing import Any

from models.agent_state import AgentState
from models.order import Order, OrderStatus, OrderType
from models.trade import Trade, TradeDirection, TradeType
from propr.client import ProprClient

# TODO: Later add trade history handling.
# TODO: Later add closed-position handling.
# TODO: Later support multiple simultaneous positions and orders.
# TODO: Later align every field with exact Propr production schemas.
# TODO: Later add websocket-based sync.


def _get_first(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _normalize_side(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"buy", "long"}:
        return "long"
    if normalized in {"sell", "short"}:
        return "short"
    return None


def _normalize_order_type(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized in {"stop", "stop_order", "buy_stop", "sell_stop"}:
        return "stop"
    if normalized in {"limit", "limit_order", "buy_limit", "sell_limit"}:
        return "limit"
    return None


def _map_order_status(value: Any) -> OrderStatus | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"pending", "open", "new"}:
        return OrderStatus.PENDING
    if normalized in {"filled", "executed"}:
        return OrderStatus.FILLED
    if normalized in {"cancelled", "canceled"}:
        return OrderStatus.CANCELLED
    return None


def map_propr_order_to_internal(order_payload: dict) -> Order | None:
    side = _normalize_side(_get_first(order_payload, ["side", "direction"]))
    order_type = _normalize_order_type(_get_first(order_payload, ["order_type", "type"]))
    entry = _get_first(order_payload, ["entry", "price", "entry_price"])
    stop_loss = _get_first(order_payload, ["stop_loss", "stopLoss", "sl"])
    take_profit = _get_first(order_payload, ["take_profit", "takeProfit", "tp"])
    status = _map_order_status(_get_first(order_payload, ["status"]))

    if side is None or order_type is None or status is None:
        return None
    if entry is None or stop_loss is None or take_profit is None:
        return None

    if side == "long" and order_type == "stop":
        internal_order_type = OrderType.BUY_STOP
    elif side == "short" and order_type == "stop":
        internal_order_type = OrderType.SELL_STOP
    elif side == "long" and order_type == "limit":
        internal_order_type = OrderType.BUY_LIMIT
    elif side == "short" and order_type == "limit":
        internal_order_type = OrderType.SELL_LIMIT
    else:
        return None

    return Order(
        order_type=internal_order_type,
        status=status,
        entry=float(entry),
        stop_loss=float(stop_loss),
        take_profit=float(take_profit),
        signal_source=str(order_payload.get("signal_source") or "external_unknown"),
        created_at=_get_first(order_payload, ["created_at", "createdAt"]),
    )


def map_propr_position_to_internal(position_payload: dict) -> Trade | None:
    status = _get_first(position_payload, ["status"])
    if str(status).strip().lower() != "open":
        return None

    side = _normalize_side(_get_first(position_payload, ["side", "direction"]))
    entry = _get_first(position_payload, ["entry", "entry_price", "price"])
    stop_loss = _get_first(position_payload, ["stop_loss", "stopLoss", "sl"])
    take_profit = _get_first(position_payload, ["take_profit", "takeProfit", "tp"])

    if side is None or entry is None or stop_loss is None or take_profit is None:
        return None

    signal_source = str(position_payload.get("signal_source") or "")
    trade_type = (
        TradeType.COUNTERTREND
        if signal_source.startswith("countertrend")
        else TradeType.TREND
    )
    direction = TradeDirection.LONG if side == "long" else TradeDirection.SHORT

    return Trade(
        trade_type=trade_type,
        direction=direction,
        entry=float(entry),
        stop_loss=float(stop_loss),
        take_profit=float(take_profit),
        is_active=True,
        break_even_activated=False,
        opened_at=_get_first(position_payload, ["opened_at", "openedAt"]),
    )


def build_agent_state_from_propr_data(
    orders_payload: dict,
    positions_payload: dict,
    previous_state: AgentState | None = None,
) -> AgentState:
    mapped_orders = [
        order
        for order in (
            map_propr_order_to_internal(item)
            for item in orders_payload.get("data", [])
        )
        if order is not None and order.status == OrderStatus.PENDING
    ]
    mapped_positions = [
        position
        for position in (
            map_propr_position_to_internal(item)
            for item in positions_payload.get("data", [])
        )
        if position is not None
    ]

    if len(mapped_orders) > 1:
        raise ValueError("Multiple valid open orders found in Propr state")
    if len(mapped_positions) > 1:
        raise ValueError("Multiple valid open positions found in Propr state")

    pending_order = mapped_orders[0] if mapped_orders else None
    active_trade = mapped_positions[0] if mapped_positions else None

    if previous_state is None:
        return AgentState(active_trade=active_trade, pending_order=pending_order)

    return previous_state.copy(
        update={
            "active_trade": active_trade,
            "pending_order": pending_order,
        }
    )


def sync_agent_state_from_propr(
    client: ProprClient,
    account_id: str,
    previous_state: AgentState | None = None,
) -> AgentState:
    orders_payload = client.get_orders(account_id)
    positions_payload = client.get_positions(account_id)
    return build_agent_state_from_propr_data(
        orders_payload=orders_payload,
        positions_payload=positions_payload,
        previous_state=previous_state,
    )

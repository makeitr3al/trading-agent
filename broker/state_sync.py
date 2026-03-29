from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from broker.propr_client import ProprClient
from models.agent_state import AgentState
from models.order import Order, OrderStatus, OrderType
from models.trade import Trade, TradeDirection, TradeType

# TODO: Later add trade history handling.
# TODO: Later add closed-position handling.
# TODO: Later support multiple simultaneous positions and orders.
# TODO: Later align every field with exact Propr production schemas.
# TODO: Later add websocket-based sync.


def _get_items(payload: dict | list[dict]) -> list[dict]:
    if isinstance(payload, list):
        return payload
    data = payload.get("data", [])
    if isinstance(data, list):
        return data
    return []


def _get_first(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
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
    if normalized in {"stop", "stop_order", "buy_stop", "sell_stop", "stop_limit", "stop_market"}:
        return "stop"
    if normalized in {"limit", "limit_order", "buy_limit", "sell_limit", "take_profit_limit"}:
        return "limit"
    return None


def _map_order_status(value: Any) -> OrderStatus | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"pending", "open", "new", "partially_filled", "partial_fill", "partially-filled"}:
        return OrderStatus.PENDING
    if normalized in {"filled", "executed"}:
        return OrderStatus.FILLED
    if normalized in {"cancelled", "canceled"}:
        return OrderStatus.CANCELLED
    return None


def _extract_external_order_id(order_payload: dict[str, Any]) -> str | None:
    value = _get_first(order_payload, ["id", "orderId", "order_id"])
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _raw_order_type(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_")
    return normalized or None


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def _normalize_symbol(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _extract_payload_symbol(payload: dict[str, Any]) -> str | None:
    direct_symbol = _normalize_symbol(
        _get_first(payload, ["symbol", "asset", "market", "instrument"])
    )
    if direct_symbol is not None:
        return direct_symbol

    base = _normalize_symbol(_get_first(payload, ["base"]))
    quote = _normalize_symbol(_get_first(payload, ["quote"]))
    if base and quote:
        return f"{base}/{quote}"

    return _normalize_symbol(_get_first(payload, ["coin"]))


def _payload_matches_symbol(payload: dict[str, Any], symbol: str | None) -> bool:
    if symbol is None:
        return True
    payload_symbol = _extract_payload_symbol(payload)
    if payload_symbol is None:
        return True
    return payload_symbol == symbol.strip().upper()


def _classify_open_order_payload(order_payload: dict[str, Any]) -> str:
    raw_type = _raw_order_type(_get_first(order_payload, ["order_type", "type"]))
    normalized_type = _normalize_order_type(_get_first(order_payload, ["order_type", "type"]))
    reduce_only = _truthy_flag(_get_first(order_payload, ["reduceOnly", "reduce_only"]))
    position_id = _get_first(order_payload, ["positionId", "position_id"])

    if raw_type in {"take_profit_limit", "take_profit_market"}:
        return "take_profit_exit"
    if raw_type in {"stop_market", "stop_limit"} and (reduce_only or position_id is not None):
        return "stop_loss_exit"
    if normalized_type == "limit" and (reduce_only or position_id is not None):
        return "take_profit_exit"
    if normalized_type == "stop" and (reduce_only or position_id is not None):
        return "stop_loss_exit"
    return "pending_entry"


def map_propr_order_to_internal(order_payload: dict) -> Order | None:
    side = _normalize_side(_get_first(order_payload, ["side", "direction", "positionSide"]))
    order_type = _normalize_order_type(_get_first(order_payload, ["order_type", "type"]))
    entry = _to_decimal(_get_first(order_payload, ["entry", "price", "entry_price", "triggerPrice"]))
    stop_loss = _to_decimal(_get_first(order_payload, ["stop_loss", "stopLoss", "sl"]))
    take_profit = _to_decimal(_get_first(order_payload, ["take_profit", "takeProfit", "tp"]))
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
        signal_source=str(order_payload.get("signal_source") or order_payload.get("signalSource") or "external_unknown"),
        created_at=_get_first(order_payload, ["created_at", "createdAt"]),
    )


def map_propr_position_to_internal(position_payload: dict) -> Trade | None:
    status = _get_first(position_payload, ["status"])
    if str(status).strip().lower() != "open":
        return None

    quantity = _to_decimal(_get_first(position_payload, ["quantity"]))
    if quantity is not None and quantity == Decimal("0"):
        return None

    side = _normalize_side(_get_first(position_payload, ["side", "direction", "positionSide"]))
    entry = _to_decimal(_get_first(position_payload, ["entry", "entry_price", "entryPrice", "price"]))
    stop_loss = _to_decimal(_get_first(position_payload, ["stop_loss", "stopLoss", "sl"]))
    take_profit = _to_decimal(_get_first(position_payload, ["take_profit", "takeProfit", "tp"]))

    if side is None or entry is None or stop_loss is None or take_profit is None:
        return None

    signal_source = str(position_payload.get("signal_source") or position_payload.get("signalSource") or "")
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
        quantity=float(quantity) if quantity is not None else None,
        position_id=_get_first(position_payload, ["positionId", "position_id", "id"]),
        is_active=True,
        break_even_activated=False,
        opened_at=_get_first(position_payload, ["opened_at", "openedAt"]),
    )


def build_agent_state_from_propr_data(
    orders_payload: dict | list[dict],
    positions_payload: dict | list[dict],
    previous_state: AgentState | None = None,
    symbol: str | None = None,
) -> AgentState:
    normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None

    all_valid_order_entries: list[tuple[Order, str | None]] = []
    valid_order_entries: list[tuple[Order, str | None]] = []
    stop_loss_order_ids: list[str] = []
    take_profit_order_ids: list[str] = []
    for item in _get_items(orders_payload):
        order_classification = _classify_open_order_payload(item)
        external_order_id = _extract_external_order_id(item)

        if order_classification == "pending_entry":
            mapped_order = map_propr_order_to_internal(item)
            if mapped_order is not None and mapped_order.status == OrderStatus.PENDING:
                all_valid_order_entries.append((mapped_order, external_order_id))
                if _payload_matches_symbol(item, normalized_symbol):
                    valid_order_entries.append((mapped_order, external_order_id))
            continue

        if not _payload_matches_symbol(item, normalized_symbol):
            continue

        if order_classification == "stop_loss_exit":
            if external_order_id is not None:
                stop_loss_order_ids.append(external_order_id)
            continue
        if order_classification == "take_profit_exit":
            if external_order_id is not None:
                take_profit_order_ids.append(external_order_id)
            continue

    all_mapped_positions = [
        position
        for position in (
            map_propr_position_to_internal(item)
            for item in _get_items(positions_payload)
        )
        if position is not None
    ]
    mapped_positions = [
        position
        for item, position in (
            (item, map_propr_position_to_internal(item))
            for item in _get_items(positions_payload)
        )
        if position is not None and _payload_matches_symbol(item, normalized_symbol)
    ]

    if len(valid_order_entries) > 1:
        raise ValueError("Multiple valid open orders found in Propr state")
    if len(mapped_positions) > 1:
        raise ValueError("Multiple valid open positions found in Propr state")
    if len(stop_loss_order_ids) > 1:
        raise ValueError("Multiple active stop-loss exit orders found in Propr state")
    if len(take_profit_order_ids) > 1:
        raise ValueError("Multiple active take-profit exit orders found in Propr state")

    pending_order: Order | None = None
    pending_order_id: str | None = None
    stop_loss_order_id: str | None = stop_loss_order_ids[0] if stop_loss_order_ids else None
    take_profit_order_id: str | None = take_profit_order_ids[0] if take_profit_order_ids else None
    if valid_order_entries:
        pending_order, pending_order_id = valid_order_entries[0]

    active_trade = mapped_positions[0] if mapped_positions else None

    if previous_state is None:
        return AgentState(
            active_trade=active_trade,
            pending_order=pending_order,
            pending_order_id=pending_order_id,
            stop_loss_order_id=stop_loss_order_id,
            take_profit_order_id=take_profit_order_id,
            account_open_entry_orders_count=len(all_valid_order_entries),
            account_open_positions_count=len(all_mapped_positions),
        )

    return previous_state.model_copy(
        update={
            "active_trade": active_trade,
            "pending_order": pending_order,
            "pending_order_id": pending_order_id,
            "stop_loss_order_id": stop_loss_order_id,
            "take_profit_order_id": take_profit_order_id,
            "account_open_entry_orders_count": len(all_valid_order_entries),
            "account_open_positions_count": len(all_mapped_positions),
        }
    )


def sync_agent_state_from_propr(
    client: ProprClient,
    account_id: str,
    previous_state: AgentState | None = None,
    symbol: str | None = None,
) -> AgentState:
    orders_payload = client.get_orders(account_id)
    positions_payload = client.get_positions(account_id)
    return build_agent_state_from_propr_data(
        orders_payload=orders_payload,
        positions_payload=positions_payload,
        previous_state=previous_state,
        symbol=symbol,
    )


__all__ = [
    "map_propr_order_to_internal",
    "map_propr_position_to_internal",
    "build_agent_state_from_propr_data",
    "sync_agent_state_from_propr",
]


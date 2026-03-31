from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from broker.propr_client import ProprClient

logger = logging.getLogger(__name__)
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



def _extract_decimal(payload: dict[str, Any], keys: list[str]) -> Decimal | None:
    return _to_decimal(_get_first(payload, keys))



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



def _normalize_status(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower().replace("-", "_")
    return normalized or None



def _map_order_status(value: Any) -> OrderStatus | None:
    normalized = _normalize_status(value)
    if normalized is None:
        return None
    if normalized in {
        "pending",
        "open",
        "new",
        "partially_filled",
        "partial_fill",
        "working",
        "accepted",
        "active",
        "live",
        "triggered",
    }:
        return OrderStatus.PENDING
    if normalized in {"filled", "executed", "closed"}:
        return OrderStatus.FILLED
    if normalized in {"cancelled", "canceled", "rejected", "expired"}:
        return OrderStatus.CANCELLED
    return None



def _is_open_position_status(value: Any) -> bool:
    return _normalize_status(value) in {"open", "active", "live"}



def _extract_external_order_id(order_payload: dict[str, Any]) -> str | None:
    value = _get_first(order_payload, ["id", "orderId", "order_id"])
    if value is None:
        return None
    text = str(value).strip()
    return text or None



def _raw_order_type(value: Any) -> str | None:
    normalized = _normalize_status(value)
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



def map_propr_order_to_internal(order_payload: dict, *, strict: bool = False) -> Order | None:
    side = _normalize_side(_get_first(order_payload, ["side", "direction", "positionSide"]))
    order_type = _normalize_order_type(_get_first(order_payload, ["order_type", "type"]))
    entry = _to_decimal(
        _get_first(order_payload, ["entry", "price", "entry_price", "entryPrice", "triggerPrice", "trigger_price"])
    )
    stop_loss = _to_decimal(_get_first(order_payload, ["stop_loss", "stopLoss", "sl", "internal_stop_loss"]))
    take_profit = _to_decimal(_get_first(order_payload, ["take_profit", "takeProfit", "tp", "internal_take_profit"]))
    quantity = _to_decimal(_get_first(order_payload, ["quantity", "qty", "size", "position_size", "positionSize"]))
    status = _map_order_status(_get_first(order_payload, ["status"]))

    if side is None or order_type is None or status is None:
        missing = [f for f, v in [("side", side), ("order_type", order_type), ("status", status)] if v is None]
        logger.warning(
            "map_propr_order_to_internal: missing required fields %s — payload keys: %s",
            missing,
            list(order_payload.keys()),
        )
        if strict:
            raise ValueError(f"Missing required order fields: {missing}")
        return None
    if entry is None or stop_loss is None or take_profit is None:
        missing = [f for f, v in [("entry", entry), ("stop_loss", stop_loss), ("take_profit", take_profit)] if v is None]
        logger.warning(
            "map_propr_order_to_internal: missing required price fields %s — payload keys: %s",
            missing,
            list(order_payload.keys()),
        )
        if strict:
            raise ValueError(f"Missing required price fields: {missing}")
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
        logger.warning(
            "map_propr_order_to_internal: unrecognized side/type combination side=%r order_type=%r — payload keys: %s",
            side,
            order_type,
            list(order_payload.keys()),
        )
        if strict:
            raise ValueError(f"Unrecognized side/type combination: side={side!r}, order_type={order_type!r}")
        return None

    return Order(
        order_type=internal_order_type,
        status=status,
        entry=float(entry),
        stop_loss=float(stop_loss),
        take_profit=float(take_profit),
        position_size=float(quantity) if quantity is not None else None,
        signal_source=str(order_payload.get("signal_source") or order_payload.get("signalSource") or "external_unknown"),
        created_at=_get_first(order_payload, ["created_at", "createdAt", "submittedAt", "updatedAt", "timestamp"]),
    )



def map_propr_position_to_internal(position_payload: dict, *, strict: bool = False) -> Trade | None:
    status = _get_first(position_payload, ["status"])
    if not _is_open_position_status(status):
        return None

    quantity = _to_decimal(_get_first(position_payload, ["quantity", "qty", "size", "positionSize"]))
    if quantity is not None and quantity == Decimal("0"):
        return None

    side = _normalize_side(_get_first(position_payload, ["side", "direction", "positionSide"]))
    entry = _to_decimal(
        _get_first(position_payload, ["entry", "entry_price", "entryPrice", "avgEntryPrice", "averageEntryPrice", "price"])
    )
    stop_loss = _to_decimal(_get_first(position_payload, ["stop_loss", "stopLoss", "sl", "internal_stop_loss"]))
    take_profit = _to_decimal(_get_first(position_payload, ["take_profit", "takeProfit", "tp", "internal_take_profit"]))

    if side is None or entry is None or stop_loss is None or take_profit is None:
        missing = [
            f for f, v in [("side", side), ("entry", entry), ("stop_loss", stop_loss), ("take_profit", take_profit)]
            if v is None
        ]
        logger.warning(
            "map_propr_position_to_internal: missing required fields %s — payload keys: %s",
            missing,
            list(position_payload.keys()),
        )
        if strict:
            raise ValueError(f"Missing required position fields: {missing}")
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
        opened_at=_get_first(position_payload, ["opened_at", "openedAt", "createdAt", "updatedAt", "timestamp"]),
    )



def _extract_account_unrealized_pnl_from_payload(positions_payload: dict | list[dict]) -> float | None:
    top_level_keys = [
        "accountUnrealizedPnl",
        "account_unrealized_pnl",
        "totalUnrealizedPnl",
        "total_unrealized_pnl",
        "totalOpenPnl",
        "total_open_pnl",
        "unrealizedPnl",
        "unrealized_pnl",
    ]
    if isinstance(positions_payload, dict):
        direct_value = _extract_decimal(positions_payload, top_level_keys)
        if direct_value is not None:
            return float(direct_value)

        for nested_key in ["account", "summary", "totals", "meta"]:
            nested_payload = positions_payload.get(nested_key)
            if isinstance(nested_payload, dict):
                nested_value = _extract_decimal(nested_payload, top_level_keys)
                if nested_value is not None:
                    return float(nested_value)

    per_position_keys = [
        "unrealizedPnl",
        "unrealized_pnl",
        "unrealisedPnl",
        "unrealised_pnl",
        "openPnl",
        "open_pnl",
        "upl",
        "pnl",
        "profitLoss",
        "profit_loss",
    ]
    total = Decimal("0")
    found_component = False
    for item in _get_items(positions_payload):
        if map_propr_position_to_internal(item) is None:
            continue
        pnl_value = _extract_decimal(item, per_position_keys)
        if pnl_value is None:
            continue
        total += pnl_value
        found_component = True

    if found_component:
        return float(total)
    return None



def _extract_account_open_positions_count_from_payload(positions_payload: dict | list[dict]) -> int:
    return sum(1 for item in _get_items(positions_payload) if map_propr_position_to_internal(item) is not None)



def _format_conflict_ids(values: list[str | None]) -> str:
    normalized = [str(value).strip() for value in values if value is not None and str(value).strip()]
    if not normalized:
        return "n/a"
    return ", ".join(normalized)



def _resolve_exit_order_ids_for_active_position(
    exit_kind: str,
    exit_entries: list[tuple[str, str | None]],
    active_position_id: str | None,
) -> list[str]:
    if not exit_entries:
        return []

    label = "stop-loss" if exit_kind == "stop_loss" else "take-profit"
    bound_entries = [(order_id, position_id) for order_id, position_id in exit_entries if position_id is not None]
    unbound_ids = [order_id for order_id, position_id in exit_entries if position_id is None]

    if active_position_id is None:
        if bound_entries:
            raise ValueError(
                f"{label.capitalize()} exit orders found without active position in Propr state: "
                f"order_ids=[{_format_conflict_ids([order_id for order_id, _ in bound_entries])}], "
                f"position_ids=[{_format_conflict_ids([position_id for _, position_id in bound_entries])}]"
            )
        if len(unbound_ids) > 1:
            raise ValueError(
                f"Multiple unbound active {label} exit orders found in Propr state: "
                f"order_ids=[{_format_conflict_ids(unbound_ids)}]"
            )
        return unbound_ids

    exact_ids = [order_id for order_id, position_id in bound_entries if position_id == active_position_id]
    foreign_entries = [(order_id, position_id) for order_id, position_id in bound_entries if position_id != active_position_id]

    if len(exact_ids) > 1:
        raise ValueError(
            f"Multiple active {label} exit orders found for position '{active_position_id}' in Propr state: "
            f"order_ids=[{_format_conflict_ids(exact_ids)}]"
        )
    if exact_ids and unbound_ids:
        raise ValueError(
            f"Conflicting {label} exit orders found for position '{active_position_id}' in Propr state: "
            f"exact_order_ids=[{_format_conflict_ids(exact_ids)}], "
            f"unbound_order_ids=[{_format_conflict_ids(unbound_ids)}]"
        )
    if exact_ids:
        return exact_ids
    if len(unbound_ids) > 1:
        raise ValueError(
            f"Multiple unbound active {label} exit orders found in Propr state: "
            f"order_ids=[{_format_conflict_ids(unbound_ids)}]"
        )
    if unbound_ids:
        return unbound_ids
    if foreign_entries:
        raise ValueError(
            f"{label.capitalize()} exit orders found for unrelated positions in Propr state: "
            f"active_position_id='{active_position_id}', "
            f"order_ids=[{_format_conflict_ids([order_id for order_id, _ in foreign_entries])}], "
            f"position_ids=[{_format_conflict_ids([position_id for _, position_id in foreign_entries])}]"
        )
    return []



def build_agent_state_from_propr_data(
    orders_payload: dict | list[dict],
    positions_payload: dict | list[dict],
    previous_state: AgentState | None = None,
    symbol: str | None = None,
) -> AgentState:
    normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None

    all_valid_order_entries: list[tuple[Order, str | None]] = []
    valid_order_entries: list[tuple[Order, str | None]] = []
    stop_loss_exit_entries: list[tuple[str, str | None]] = []
    take_profit_exit_entries: list[tuple[str, str | None]] = []
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
        if external_order_id is None:
            continue

        linked_position_id = _get_first(item, ["positionId", "position_id"])
        if order_classification == "stop_loss_exit":
            stop_loss_exit_entries.append((external_order_id, linked_position_id))
            continue
        if order_classification == "take_profit_exit":
            take_profit_exit_entries.append((external_order_id, linked_position_id))
            continue

    mapped_position_entries = [
        (item, position)
        for item, position in (
            (item, map_propr_position_to_internal(item))
            for item in _get_items(positions_payload)
        )
        if position is not None
    ]
    mapped_positions = [
        position
        for item, position in mapped_position_entries
        if _payload_matches_symbol(item, normalized_symbol)
    ]

    if len(valid_order_entries) > 1:
        raise ValueError(
            f"Multiple pending entry orders found in Propr state: "
            f"order_ids=[{_format_conflict_ids([order_id for _, order_id in valid_order_entries])}]"
        )
    if len(mapped_positions) > 1:
        raise ValueError(
            f"Multiple open positions found in Propr state: "
            f"position_ids=[{_format_conflict_ids([position.position_id for position in mapped_positions])}]"
        )

    active_trade = mapped_positions[0] if mapped_positions else None
    active_position_id = active_trade.position_id if active_trade is not None else None

    stop_loss_order_ids = _resolve_exit_order_ids_for_active_position("stop_loss", stop_loss_exit_entries, active_position_id)
    take_profit_order_ids = _resolve_exit_order_ids_for_active_position("take_profit", take_profit_exit_entries, active_position_id)

    pending_order: Order | None = None
    pending_order_id: str | None = None
    stop_loss_order_id: str | None = stop_loss_order_ids[0] if stop_loss_order_ids else None
    take_profit_order_id: str | None = take_profit_order_ids[0] if take_profit_order_ids else None
    if valid_order_entries:
        pending_order, pending_order_id = valid_order_entries[0]

    account_open_positions_count = _extract_account_open_positions_count_from_payload(positions_payload)
    account_unrealized_pnl = _extract_account_unrealized_pnl_from_payload(positions_payload)

    if previous_state is None:
        return AgentState(
            active_trade=active_trade,
            pending_order=pending_order,
            pending_order_id=pending_order_id,
            stop_loss_order_id=stop_loss_order_id,
            take_profit_order_id=take_profit_order_id,
            account_open_entry_orders_count=len(all_valid_order_entries),
            account_open_positions_count=account_open_positions_count,
            account_unrealized_pnl=account_unrealized_pnl,
        )

    return previous_state.model_copy(
        update={
            "active_trade": active_trade,
            "pending_order": pending_order,
            "pending_order_id": pending_order_id,
            "stop_loss_order_id": stop_loss_order_id,
            "take_profit_order_id": take_profit_order_id,
            "account_open_entry_orders_count": len(all_valid_order_entries),
            "account_open_positions_count": account_open_positions_count,
            "account_unrealized_pnl": account_unrealized_pnl,
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
    "_extract_account_open_positions_count_from_payload",
    "_extract_account_unrealized_pnl_from_payload",
    "build_agent_state_from_propr_data",
    "sync_agent_state_from_propr",
]



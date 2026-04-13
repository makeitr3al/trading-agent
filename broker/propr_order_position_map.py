from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from broker.propr_payload_parse import (
    _is_open_position_status,
    _map_order_status,
    _normalize_order_type,
    _normalize_side,
    _raw_order_type,
    _to_decimal,
    _truthy_flag,
)
from models.order import Order, OrderType
from models.trade import Trade, TradeDirection, TradeType
from utils.propr_response import get_first_key

logger = logging.getLogger(__name__)


def _classify_open_order_payload(order_payload: dict[str, Any]) -> str:
    type_value = get_first_key(order_payload, ["order_type", "type"])
    raw_type = _raw_order_type(type_value)
    normalized_type = _normalize_order_type(type_value)
    reduce_only = _truthy_flag(get_first_key(order_payload, ["reduceOnly", "reduce_only"]))
    position_id = get_first_key(order_payload, ["positionId", "position_id"])

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
    side = _normalize_side(get_first_key(order_payload, ["side", "direction", "positionSide"]))
    order_type = _normalize_order_type(get_first_key(order_payload, ["order_type", "type"]))
    entry = _to_decimal(
        get_first_key(
            order_payload,
            ["entry", "price", "entry_price", "entryPrice", "triggerPrice", "trigger_price"],
        )
    )
    stop_loss = _to_decimal(get_first_key(order_payload, ["stop_loss", "stopLoss", "sl", "internal_stop_loss"]))
    take_profit = _to_decimal(get_first_key(order_payload, ["take_profit", "takeProfit", "tp", "internal_take_profit"]))
    quantity = _to_decimal(get_first_key(order_payload, ["quantity", "qty", "size", "position_size", "positionSize"]))
    status = _map_order_status(get_first_key(order_payload, ["status"]))

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
        logger.debug(
            "map_propr_order_to_internal: incomplete bracket prices %s — payload keys: %s",
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
        created_at=get_first_key(order_payload, ["created_at", "createdAt", "submittedAt", "updatedAt", "timestamp"]),
    )


def map_propr_position_to_internal(position_payload: dict, *, strict: bool = False) -> Trade | None:
    status = get_first_key(position_payload, ["status"])
    if not _is_open_position_status(status):
        return None

    quantity = _to_decimal(get_first_key(position_payload, ["quantity", "qty", "size", "positionSize"]))
    if quantity is not None and quantity == Decimal("0"):
        return None

    side = _normalize_side(get_first_key(position_payload, ["side", "direction", "positionSide"]))
    entry = _to_decimal(
        get_first_key(
            position_payload,
            ["entry", "entry_price", "entryPrice", "avgEntryPrice", "averageEntryPrice", "price"],
        )
    )
    stop_loss = _to_decimal(get_first_key(position_payload, ["stop_loss", "stopLoss", "sl", "internal_stop_loss"]))
    take_profit = _to_decimal(get_first_key(position_payload, ["take_profit", "takeProfit", "tp", "internal_take_profit"]))

    if side is None or entry is None or stop_loss is None:
        missing = [f for f, v in [("side", side), ("entry", entry), ("stop_loss", stop_loss)] if v is None]
        logger.warning(
            "map_propr_position_to_internal: missing required fields %s — payload keys: %s",
            missing,
            list(position_payload.keys()),
        )
        if strict:
            raise ValueError(f"Missing required position fields: {missing}")
        return None

    if take_profit is None:
        logger.debug(
            "map_propr_position_to_internal: take_profit absent on open position — payload keys: %s",
            list(position_payload.keys()),
        )

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
        take_profit=float(take_profit) if take_profit is not None else None,
        quantity=float(quantity) if quantity is not None else None,
        position_id=get_first_key(position_payload, ["positionId", "position_id", "id"]),
        is_active=True,
        break_even_activated=False,
        opened_at=get_first_key(position_payload, ["opened_at", "openedAt", "createdAt", "updatedAt", "timestamp"]),
    )

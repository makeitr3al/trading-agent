from __future__ import annotations

from decimal import Decimal
from typing import Any

from broker.propr_client import ProprClient
from broker.propr_order_position_map import (
    _classify_open_order_payload,
    map_propr_order_to_internal,
    map_propr_position_to_internal,
)
from broker.propr_payload_parse import (
    _extract_decimal,
    _get_items,
    _map_order_status,
    _normalize_status,
    _normalize_order_type,
    _payload_matches_symbol,
)
from models.agent_state import AgentState
from models.order import Order, OrderStatus, OrderType
from models.trade import Trade, TradeDirection, TradeType
from utils.propr_response import extract_external_order_id, get_first_key

# TODO: Later add trade history handling.
# TODO: Later add closed-position handling.
# TODO: Later support multiple simultaneous positions and orders.
# TODO: Later align every field with exact Propr production schemas.
# TODO: Later add websocket-based sync.

_POSITION_SUMMARY_ROW_PNL_KEYS = [
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

# Exit-order fields used when REST positions omit SL/TP (exits live on orders only).
_ORDER_SL_VALUE_KEYS = [
    "internal_stop_loss",
    "stopLoss",
    "stop_loss",
    "triggerPrice",
    "trigger_price",
    "stopPrice",
    "stop_price",
    "price",
]
_ORDER_TP_VALUE_KEYS = [
    "internal_take_profit",
    "takeProfit",
    "take_profit",
    "limitPrice",
    "limit_price",
    "price",
]


def _is_open_position_row_lenient(item: Any) -> bool:
    """
    Lenient predicate for whether a Propr position row represents an open position.

    Propr `/positions` payloads can omit stopLoss/takeProfit; for UI and account-level
    telemetry we still want to count/summarize open positions without requiring exits.
    """
    if not isinstance(item, dict):
        return False

    status = get_first_key(item, ["status"])
    if _normalize_status(status) not in {"open", "active", "live"}:
        return False

    qty = _extract_decimal(item, ["quantity", "qty", "size", "positionSize"])
    if qty is not None and qty == Decimal("0"):
        return False

    side = get_first_key(item, ["side", "direction", "positionSide"])
    entry = _extract_decimal(
        item,
        ["entry", "entry_price", "entryPrice", "avgEntryPrice", "averageEntryPrice", "price"],
    )
    if side is None or entry is None:
        return False

    return True


def _position_row_is_long(row: dict[str, Any]) -> bool | None:
    s = str(get_first_key(row, ["positionSide", "side", "direction"]) or "").lower()
    if "long" in s or s == "buy":
        return True
    if "short" in s or s == "sell":
        return False
    return None


def _trade_type_from_previous_state(previous_state: AgentState) -> TradeType:
    po = previous_state.pending_order
    if po is not None and "countertrend" in (po.signal_source or ""):
        return TradeType.COUNTERTREND
    at = previous_state.active_trade
    if at is not None and at.trade_type == TradeType.COUNTERTREND:
        return TradeType.COUNTERTREND
    return TradeType.TREND


def _synthetic_trade_from_raw_position_row(
    row: dict[str, Any],
    *,
    stop_loss: float,
    take_profit: float | None,
    trade_type: TradeType,
    normalized_symbol: str,
) -> Trade | None:
    if not _is_open_position_row_lenient(row) or not _payload_matches_symbol(row, normalized_symbol):
        return None
    plong = _position_row_is_long(row)
    if plong is None:
        return None
    direction = TradeDirection.LONG if plong else TradeDirection.SHORT
    entry_raw = get_first_key(row, ["entryPrice", "entry_price", "entry", "avgEntryPrice", "averageEntryPrice", "price"])
    if entry_raw is None:
        return None
    try:
        entry = float(entry_raw)
    except (TypeError, ValueError):
        return None
    pos_id = get_first_key(row, ["positionId", "position_id", "id"])
    qty_raw = get_first_key(row, ["quantity", "qty", "size", "positionSize"])
    try:
        qty = float(qty_raw) if qty_raw is not None else None
    except (TypeError, ValueError):
        qty = None
    opened = get_first_key(row, ["openedAt", "opened_at", "createdAt", "updatedAt", "timestamp"])
    return Trade(
        trade_type=trade_type,
        direction=direction,
        entry=entry,
        stop_loss=float(stop_loss),
        take_profit=float(take_profit) if take_profit is not None else None,
        quantity=qty,
        position_id=str(pos_id).strip() if pos_id else None,
        is_active=True,
        break_even_activated=False,
        opened_at=str(opened) if opened is not None else None,
    )


def _resolve_active_trade_with_previous_fallback(
    mapped_positions: list[Trade],
    positions_payload: dict | list[dict],
    previous_state: AgentState | None,
    normalized_symbol: str | None,
) -> Trade | None:
    """When ``map_propr_position_to_internal`` yields nothing, rebuild ``Trade`` from raw row + prior agent levels."""
    if mapped_positions:
        return mapped_positions[0]
    if previous_state is None or not normalized_symbol:
        return None
    candidates = [
        row
        for row in _get_items(positions_payload)
        if isinstance(row, dict)
        and _is_open_position_row_lenient(row)
        and _payload_matches_symbol(row, normalized_symbol)
    ]
    if len(candidates) != 1:
        return None
    row = candidates[0]
    plong = _position_row_is_long(row)
    if plong is None:
        return None

    stop_loss: float | None = None
    take_profit: float | None = None
    po = previous_state.pending_order
    if po is not None:
        po_long = po.order_type in {OrderType.BUY_LIMIT, OrderType.BUY_STOP}
        if po_long == plong:
            stop_loss = float(po.stop_loss)
            take_profit = float(po.take_profit)

    if stop_loss is None:
        at = previous_state.active_trade
        if at is not None and (at.direction == TradeDirection.LONG) == plong:
            stop_loss = float(at.stop_loss)
            take_profit = float(at.take_profit) if at.take_profit is not None else None

    if stop_loss is None:
        import logging

        logging.getLogger(__name__).warning(
            "Open position for symbol %s has no mappable stop_loss on broker payload and no recoverable "
            "levels in previous_state (pending_order / active_trade). Agent will treat as no active_trade.",
            normalized_symbol,
        )
        return None

    tt = _trade_type_from_previous_state(previous_state)
    return _synthetic_trade_from_raw_position_row(
        row,
        stop_loss=stop_loss,
        take_profit=take_profit,
        trade_type=tt,
        normalized_symbol=normalized_symbol,
    )


def enrich_positions_payload_with_exit_levels_from_orders(
    orders_payload: dict | list[dict],
    positions_payload: dict | list[dict],
) -> dict[str, Any]:
    """Copy position rows and fill missing stopLoss/takeProfit from linked open exit orders (same positionId)."""
    items: list[dict[str, Any]] = [dict(x) for x in _get_items(positions_payload) if isinstance(x, dict)]
    exit_sl: dict[str, Any] = {}
    exit_tp: dict[str, Any] = {}
    for order in _get_items(orders_payload):
        if not isinstance(order, dict):
            continue
        pos_id_raw = get_first_key(order, ["positionId", "position_id"])
        if pos_id_raw is None:
            continue
        pos_key = str(pos_id_raw).strip()
        if not pos_key:
            continue
        kind = _classify_open_order_payload(order)
        if kind == "stop_loss_exit":
            price = get_first_key(order, _ORDER_SL_VALUE_KEYS)
            if price is not None and pos_key not in exit_sl:
                exit_sl[pos_key] = price
        elif kind == "take_profit_exit":
            price = get_first_key(order, _ORDER_TP_VALUE_KEYS)
            if price is not None and pos_key not in exit_tp:
                exit_tp[pos_key] = price
    for row in items:
        pos_key_raw = get_first_key(row, ["positionId", "position_id", "id"])
        if pos_key_raw is None:
            continue
        pos_key = str(pos_key_raw).strip()
        if not pos_key:
            continue
        existing_sl = get_first_key(row, ["stop_loss", "stopLoss", "sl", "internal_stop_loss"])
        existing_tp = get_first_key(row, ["take_profit", "takeProfit", "tp", "internal_take_profit"])
        if existing_sl is None and pos_key in exit_sl:
            row["stopLoss"] = exit_sl[pos_key]
        if existing_tp is None and pos_key in exit_tp:
            row["takeProfit"] = exit_tp[pos_key]
    if isinstance(positions_payload, dict):
        merged = dict(positions_payload)
        merged["data"] = items
        return merged
    return {"data": items}


def summarize_open_position_rows(items: list[dict]) -> list[dict[str, Any]]:
    """Build display rows for open positions (REST or WebSocket payloads)."""
    rows: list[dict[str, Any]] = []
    for item in items:
        if not _is_open_position_row_lenient(item):
            continue
        trade = map_propr_position_to_internal(item)
        pnl_dec = _extract_decimal(item, _POSITION_SUMMARY_ROW_PNL_KEYS)
        symbol = get_first_key(item, ["asset", "symbol", "pair", "base", "market"])
        qty = _extract_decimal(item, ["quantity", "qty", "size", "positionSize"])
        entry = _extract_decimal(
            item,
            ["entry", "entry_price", "entryPrice", "avgEntryPrice", "averageEntryPrice", "price"],
        )
        side_raw = get_first_key(item, ["side", "direction", "positionSide"])
        side = str(side_raw or "").lower()
        direction = trade.direction.value.lower() if trade is not None else ("long" if side == "long" else "short" if side == "short" else None)
        sl_dec = _extract_decimal(item, ["stop_loss", "stopLoss", "sl", "internal_stop_loss"])
        tp_dec = _extract_decimal(item, ["take_profit", "takeProfit", "tp", "internal_take_profit"])
        stop_loss = trade.stop_loss if trade is not None else (float(sl_dec) if sl_dec is not None else None)
        take_profit = trade.take_profit if trade is not None else (float(tp_dec) if tp_dec is not None else None)
        rows.append(
            {
                "symbol": str(symbol) if symbol is not None else None,
                "direction": direction,
                "position_size": float(qty) if qty is not None else (trade.quantity if trade is not None else None),
                "entry_price": float(entry) if entry is not None else (trade.entry if trade is not None else None),
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "unrealized_pnl": float(pnl_dec) if pnl_dec is not None else None,
                "position_id": trade.position_id if trade is not None else get_first_key(item, ["positionId", "position_id", "id"]),
            }
        )
    return rows


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
        if not _is_open_position_row_lenient(item):
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
    return sum(1 for item in _get_items(positions_payload) if _is_open_position_row_lenient(item))


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


def _mapped_positions_for_symbol(
    positions_payload: dict | list[dict],
    normalized_symbol: str | None,
) -> list[Trade]:
    mapped_position_entries = [
        (item, position)
        for item, position in (
            (item, map_propr_position_to_internal(item))
            for item in _get_items(positions_payload)
        )
        if position is not None
    ]
    return [
        position
        for item, position in mapped_position_entries
        if _payload_matches_symbol(item, normalized_symbol)
    ]


def build_agent_state_from_propr_data(
    orders_payload: dict | list[dict],
    positions_payload: dict | list[dict],
    previous_state: AgentState | None = None,
    symbol: str | None = None,
) -> AgentState:
    normalized_symbol = symbol.strip().upper() if isinstance(symbol, str) and symbol.strip() else None

    mapped_positions = _mapped_positions_for_symbol(positions_payload, normalized_symbol)

    all_valid_order_entries: list[tuple[Order, str | None]] = []
    valid_order_entries: list[tuple[Order, str | None]] = []
    stop_loss_exit_entries: list[tuple[str, str | None]] = []
    take_profit_exit_entries: list[tuple[str, str | None]] = []
    stop_loss_exit_meta: dict[str, dict[str, Any]] = {}
    take_profit_exit_meta: dict[str, dict[str, Any]] = {}
    for item in _get_items(orders_payload):
        order_classification = _classify_open_order_payload(item)
        external_order_id = extract_external_order_id(item)

        if order_classification == "pending_entry":
            status = _map_order_status(get_first_key(item, ["status"]))
            if status != OrderStatus.PENDING:
                continue
            if _normalize_order_type(get_first_key(item, ["order_type", "type"])) is None:
                # e.g. market orders returned by the API; not a bracketed pending entry.
                continue

            mapped_order = map_propr_order_to_internal(item)
            if mapped_order is not None and mapped_order.status == OrderStatus.PENDING:
                all_valid_order_entries.append((mapped_order, external_order_id))
                if _payload_matches_symbol(item, normalized_symbol):
                    raw_status = _normalize_status(get_first_key(item, ["status"]))
                    partial_entry = raw_status in {"partially_filled", "partial_fill"}
                    if normalized_symbol is not None and mapped_positions and partial_entry:
                        pass
                    else:
                        valid_order_entries.append((mapped_order, external_order_id))
            continue

        if not _payload_matches_symbol(item, normalized_symbol):
            continue
        if external_order_id is None:
            continue

        linked_position_id = get_first_key(item, ["positionId", "position_id"])
        if order_classification == "stop_loss_exit":
            status = _map_order_status(get_first_key(item, ["status"]))
            if status == OrderStatus.PENDING:
                stop_loss_exit_entries.append((external_order_id, linked_position_id))
                stop_loss_exit_meta[external_order_id] = {
                    "order_id": external_order_id,
                    "position_id": linked_position_id,
                    "status": get_first_key(item, ["status"]),
                    "type": get_first_key(item, ["type", "order_type"]),
                    "reduceOnly": get_first_key(item, ["reduceOnly", "reduce_only"]),
                    "updatedAt": get_first_key(item, ["updatedAt", "updated_at"]),
                    "createdAt": get_first_key(item, ["createdAt", "created_at"]),
                }
            continue
        if order_classification == "take_profit_exit":
            status = _map_order_status(get_first_key(item, ["status"]))
            if status == OrderStatus.PENDING:
                take_profit_exit_entries.append((external_order_id, linked_position_id))
                take_profit_exit_meta[external_order_id] = {
                    "order_id": external_order_id,
                    "position_id": linked_position_id,
                    "status": get_first_key(item, ["status"]),
                    "type": get_first_key(item, ["type", "order_type"]),
                    "reduceOnly": get_first_key(item, ["reduceOnly", "reduce_only"]),
                    "updatedAt": get_first_key(item, ["updatedAt", "updated_at"]),
                    "createdAt": get_first_key(item, ["createdAt", "created_at"]),
                }
            continue

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

    active_trade = _resolve_active_trade_with_previous_fallback(
        mapped_positions,
        positions_payload,
        previous_state,
        normalized_symbol,
    )
    active_position_id = active_trade.position_id if active_trade is not None else None

    account_open_positions_count = _extract_account_open_positions_count_from_payload(positions_payload)
    account_unrealized_pnl = _extract_account_unrealized_pnl_from_payload(positions_payload)

    try:
        stop_loss_order_ids = _resolve_exit_order_ids_for_active_position("stop_loss", stop_loss_exit_entries, active_position_id)
        take_profit_order_ids = _resolve_exit_order_ids_for_active_position("take_profit", take_profit_exit_entries, active_position_id)
    except ValueError as exc:
        print(f"Warning: {exc}")
        if stop_loss_exit_meta or take_profit_exit_meta:
            print("Exit order diagnostics (pending only):")
            if stop_loss_exit_meta:
                print(f"  stop_loss: {list(stop_loss_exit_meta.values())}")
            if take_profit_exit_meta:
                print(f"  take_profit: {list(take_profit_exit_meta.values())}")
        stop_loss_order_ids = []
        take_profit_order_ids = []

    pending_order: Order | None = None
    pending_order_id: str | None = None
    stop_loss_order_id: str | None = stop_loss_order_ids[0] if stop_loss_order_ids else None
    take_profit_order_id: str | None = take_profit_order_ids[0] if take_profit_order_ids else None
    if valid_order_entries:
        pending_order, pending_order_id = valid_order_entries[0]

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


def _load_orders_and_enriched_positions(
    client: ProprClient,
    account_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    orders_payload = client.get_orders(account_id)
    positions_payload = client.get_positions(account_id)
    enriched_positions = enrich_positions_payload_with_exit_levels_from_orders(orders_payload, positions_payload)
    return orders_payload, enriched_positions


def sync_agent_state_from_propr(
    client: ProprClient,
    account_id: str,
    previous_state: AgentState | None = None,
    symbol: str | None = None,
) -> AgentState:
    orders_payload, enriched_positions = _load_orders_and_enriched_positions(client, account_id)
    return build_agent_state_from_propr_data(
        orders_payload=orders_payload,
        positions_payload=enriched_positions,
        previous_state=previous_state,
        symbol=symbol,
    )


def sync_agent_state_from_propr_with_position_summary(
    client: ProprClient,
    account_id: str,
    previous_state: AgentState | None = None,
    symbol: str | None = None,
) -> tuple[AgentState, list[dict[str, Any]]]:
    """Like ``sync_agent_state_from_propr`` but also returns ``summarize_open_position_rows`` using enriched payloads."""
    orders_payload, enriched_positions = _load_orders_and_enriched_positions(client, account_id)
    state = build_agent_state_from_propr_data(
        orders_payload=orders_payload,
        positions_payload=enriched_positions,
        previous_state=previous_state,
        symbol=symbol,
    )
    summary = summarize_open_position_rows(_get_items(enriched_positions))
    return state, summary


__all__ = [
    "map_propr_order_to_internal",
    "map_propr_position_to_internal",
    "_extract_account_open_positions_count_from_payload",
    "_extract_account_unrealized_pnl_from_payload",
    "build_agent_state_from_propr_data",
    "enrich_positions_payload_with_exit_levels_from_orders",
    "sync_agent_state_from_propr",
    "sync_agent_state_from_propr_with_position_summary",
    "summarize_open_position_rows",
    "_get_items",
]

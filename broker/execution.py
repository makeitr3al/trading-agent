from dataclasses import dataclass
from typing import Any, Callable

from models.agent_state import AgentState
from models.order import Order, OrderStatus
from models.trade import Trade
from broker.order_service import (
    ProprOrderService,
    build_stop_loss_submission_preview,
    build_take_profit_submission_preview,
    extract_order_id_from_submit_response,
)
from broker.state_sync import map_propr_order_to_internal

# TODO: Later add real idempotency.
# TODO: Later add duplicate detection based on external order ids.
# TODO: Later sync with Propr open orders before submit.
# TODO: Later handle partial fills.


FLOAT_TOLERANCE = 1e-9



def _extract_first(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None



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



def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower().replace("-", "_")
    return text or None



def _extract_payload_symbol(payload: dict[str, Any]) -> str | None:
    direct_symbol = _normalize_symbol(
        _extract_first(payload, ["symbol", "asset", "market", "instrument"])
    )
    if direct_symbol is not None:
        return direct_symbol

    base = _normalize_symbol(_extract_first(payload, ["base"]))
    quote = _normalize_symbol(_extract_first(payload, ["quote"]))
    if base and quote:
        return f"{base}/{quote}"

    return _normalize_symbol(_extract_first(payload, ["coin"]))



def _payload_matches_symbol(payload: dict[str, Any], symbol: str) -> bool:
    payload_symbol = _extract_payload_symbol(payload)
    if payload_symbol is None:
        return True
    return payload_symbol == symbol.strip().upper()



def _extract_external_order_id(order_payload: dict[str, Any]) -> str | None:
    value = _extract_first(order_payload, ["id", "orderId", "order_id"])
    if value is None:
        return None
    text = str(value).strip()
    return text or None



def _supports_open_orders_lookup(order_service: ProprOrderService) -> bool:
    client = getattr(order_service, "client", None)
    return client is not None and hasattr(client, "get_orders")



def _get_open_orders_payload(order_service: ProprOrderService, account_id: str) -> list[dict[str, Any]]:
    if not _supports_open_orders_lookup(order_service):
        return []

    client = getattr(order_service, "client", None)
    try:
        payload = client.get_orders(account_id)
    except Exception:
        return []

    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        data = payload.get("data", [])
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    return []



def _is_pending_entry_order_payload(order_payload: dict[str, Any]) -> bool:
    if _truthy_flag(_extract_first(order_payload, ["reduceOnly", "reduce_only"])):
        return False
    if _extract_first(order_payload, ["positionId", "position_id"]) is not None:
        return False

    mapped_order = map_propr_order_to_internal(order_payload)
    return mapped_order is not None and mapped_order.status == OrderStatus.PENDING



def _classify_exit_order_payload(order_payload: dict[str, Any]) -> str | None:
    reduce_only = _truthy_flag(_extract_first(order_payload, ["reduceOnly", "reduce_only"]))
    position_id = _extract_first(order_payload, ["positionId", "position_id"])
    if not reduce_only and position_id is None:
        return None

    order_type = _normalize_text(_extract_first(order_payload, ["order_type", "type"]))
    if order_type in {"take_profit_limit", "take_profit_market", "limit"}:
        return "take_profit"
    if order_type in {"stop_market", "stop_limit", "stop"}:
        return "stop_loss"
    return None



def _iter_matching_pending_entry_order_payloads(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
) -> list[dict[str, Any]]:
    matching_items: list[dict[str, Any]] = []
    for item in _get_open_orders_payload(order_service, account_id):
        if not _payload_matches_symbol(item, symbol):
            continue
        if not _is_pending_entry_order_payload(item):
            continue
        matching_items.append(item)
    return matching_items



def _iter_matching_exit_order_payloads(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    exit_kind: str,
) -> list[dict[str, Any]]:
    matching_items: list[dict[str, Any]] = []
    for item in _get_open_orders_payload(order_service, account_id):
        if not _payload_matches_symbol(item, symbol):
            continue
        if _classify_exit_order_payload(item) != exit_kind:
            continue
        matching_items.append(item)
    return matching_items



def _find_external_pending_order_payload_by_id(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    order_id: str | None,
) -> dict[str, Any] | None:
    if order_id is None or not order_id.strip():
        return None

    for item in _iter_matching_pending_entry_order_payloads(order_service, account_id, symbol):
        if _extract_external_order_id(item) == order_id.strip():
            return item
    return None



def _find_external_exit_order_payload_by_id(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    exit_kind: str,
    order_id: str | None,
) -> dict[str, Any] | None:
    if order_id is None or not order_id.strip():
        return None

    for item in _iter_matching_exit_order_payloads(order_service, account_id, symbol, exit_kind):
        if _extract_external_order_id(item) == order_id.strip():
            return item
    return None



def _values_close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(left - right) <= FLOAT_TOLERANCE



def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None



def _orders_are_equivalent(left: Order, right: Order) -> bool:
    if left.order_type != right.order_type:
        return False
    if not _values_close(left.entry, right.entry):
        return False
    if not _values_close(left.stop_loss, right.stop_loss):
        return False
    if not _values_close(left.take_profit, right.take_profit):
        return False
    if left.position_size is not None and right.position_size is not None:
        if not _values_close(left.position_size, right.position_size):
            return False
    return True



def _payload_matches_exit_preview(
    order_payload: dict[str, Any],
    symbol: str,
    desired_preview: dict[str, Any],
    exit_kind: str,
) -> bool:
    if not _payload_matches_symbol(order_payload, symbol):
        return False
    if _classify_exit_order_payload(order_payload) != exit_kind:
        return False

    if _normalize_text(_extract_first(order_payload, ["side", "direction"])) != _normalize_text(desired_preview.get("side")):
        return False
    if _normalize_text(_extract_first(order_payload, ["positionSide", "position_side"])) != _normalize_text(desired_preview.get("position_side")):
        return False
    if str(_extract_first(order_payload, ["positionId", "position_id"]) or "") != str(desired_preview.get("position_id") or ""):
        return False
    if _truthy_flag(_extract_first(order_payload, ["reduceOnly", "reduce_only"])) != _truthy_flag(desired_preview.get("reduce_only")):
        return False

    if not _values_close(
        _to_optional_float(_extract_first(order_payload, ["quantity", "qty", "size"])),
        _to_optional_float(desired_preview.get("quantity")),
    ):
        return False

    desired_price = _to_optional_float(desired_preview.get("price"))
    if desired_price is not None and not _values_close(
        _to_optional_float(_extract_first(order_payload, ["price"])),
        desired_price,
    ):
        return False

    desired_trigger = _to_optional_float(desired_preview.get("trigger_price"))
    if desired_trigger is not None and not _values_close(
        _to_optional_float(_extract_first(order_payload, ["triggerPrice", "trigger_price", "trigger"])),
        desired_trigger,
    ):
        return False

    return True



def _build_reused_pending_order_response(order_id: str) -> dict[str, Any]:
    return {
        "cancel": None,
        "submit": {"id": order_id, "status": "unchanged"},
        "reused_existing": True,
    }



def _build_reused_exit_order_response(order_id: str) -> dict[str, Any]:
    return {
        "cancel": None,
        "submit": None,
        "order_id": order_id,
        "reused_existing": True,
    }



def find_equivalent_external_pending_order_id(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    order: Order,
) -> str | None:
    for item in _iter_matching_pending_entry_order_payloads(order_service, account_id, symbol):
        mapped_order = map_propr_order_to_internal(item)
        if mapped_order is None:
            continue
        if _orders_are_equivalent(mapped_order, order):
            return _extract_external_order_id(item)
    return None



def _find_equivalent_external_exit_order_payload(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    exit_kind: str,
    desired_preview: dict[str, Any],
) -> dict[str, Any] | None:
    for item in _iter_matching_exit_order_payloads(order_service, account_id, symbol, exit_kind):
        if _payload_matches_exit_preview(item, symbol, desired_preview, exit_kind):
            return item
    return None



def _submit_agent_order_skip_reason(state: AgentState, order: Order | None) -> str | None:
    if order is None:
        return "submit blocked: order is None"
    if state.active_trade is not None:
        return "submit blocked: active trade present"
    if state.pending_order is not None:
        return "submit blocked: pending order already in agent state"
    return None


def should_submit_order(
    state: AgentState,
    order: Order | None,
) -> bool:
    return _submit_agent_order_skip_reason(state, order) is None


@dataclass(frozen=True)
class SubmitAgentOrderResult:
    """Outcome of ``submit_agent_order_if_allowed`` (response body and optional skip explanation)."""

    response: dict | None
    skip_reason: str | None


def submit_agent_order_if_allowed(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    state: AgentState,
    order: Order | None,
) -> SubmitAgentOrderResult:
    blocked = _submit_agent_order_skip_reason(state, order)
    if blocked is not None:
        return SubmitAgentOrderResult(None, blocked)

    existing_order_id = find_equivalent_external_pending_order_id(
        order_service=order_service,
        account_id=account_id,
        symbol=symbol,
        order=order,
    )
    if existing_order_id is not None:
        return SubmitAgentOrderResult(
            None,
            "submit skipped: equivalent pending order already exists at broker",
        )

    broker_response = order_service.submit_pending_order(account_id, order, symbol)
    if broker_response is None:
        return SubmitAgentOrderResult(None, "pending order submit returned no confirmation")
    return SubmitAgentOrderResult(broker_response, None)



def should_close_active_trade(
    state: AgentState,
    close_active_trade: bool,
) -> bool:
    return close_active_trade and state.active_trade is not None



def submit_active_trade_close_if_allowed(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    state: AgentState,
    close_active_trade: bool,
) -> dict | None:
    if not should_close_active_trade(state, close_active_trade):
        return None
    return order_service.submit_market_close(account_id, state.active_trade, symbol)



def has_external_pending_order_id(state: AgentState) -> bool:
    return state.pending_order_id is not None and bool(state.pending_order_id.strip())



def should_cancel_existing_pending_order(
    state: AgentState,
    new_order: Order | None,
) -> bool:
    return state.pending_order is not None and new_order is not None



def safe_replace_pending_order(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    state: AgentState,
    new_order: Order | None,
) -> dict | None:
    if not should_cancel_existing_pending_order(state, new_order):
        if new_order is not None and should_submit_order(state, new_order):
            return order_service.submit_pending_order(account_id, new_order, symbol)
        return None

    if new_order is None:
        return None

    current_external_order_payload = _find_external_pending_order_payload_by_id(
        order_service=order_service,
        account_id=account_id,
        symbol=symbol,
        order_id=state.pending_order_id,
    )
    if current_external_order_payload is not None:
        mapped_current_order = map_propr_order_to_internal(current_external_order_payload)
        if mapped_current_order is not None and _orders_are_equivalent(mapped_current_order, new_order):
            existing_order_id = _extract_external_order_id(current_external_order_payload)
            if existing_order_id is not None:
                return _build_reused_pending_order_response(existing_order_id)

        cancel_response = order_service.cancel_order(account_id, state.pending_order_id)
        submit_response = order_service.submit_pending_order(account_id, new_order, symbol)
        return {
            "cancel": cancel_response,
            "submit": submit_response,
        }

    equivalent_order_id = find_equivalent_external_pending_order_id(
        order_service=order_service,
        account_id=account_id,
        symbol=symbol,
        order=new_order,
    )
    if equivalent_order_id is not None:
        return _build_reused_pending_order_response(equivalent_order_id)

    submit_response = order_service.submit_pending_order(account_id, new_order, symbol)
    return {
        "cancel": None,
        "submit": submit_response,
    }



def _has_external_order_id(order_id: str | None) -> bool:
    return order_id is not None and bool(order_id.strip())



def _prepare_updated_trade_for_exit_orders(state: AgentState, updated_trade: Trade) -> Trade:
    updates: dict[str, object] = {}
    if updated_trade.quantity is None and state.active_trade is not None:
        updates["quantity"] = state.active_trade.quantity
    if updated_trade.position_id is None and state.active_trade is not None:
        updates["position_id"] = state.active_trade.position_id
    if not updates:
        return updated_trade
    return updated_trade.model_copy(update=updates)



def _resolve_exit_order_request(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    exit_kind: str,
    current_order_id: str | None,
    desired_preview: dict[str, Any],
    submit_fn: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    if not _supports_open_orders_lookup(order_service):
        cancel_response = None
        if _has_external_order_id(current_order_id):
            cancel_response = order_service.cancel_order(account_id, current_order_id)
        submit_response = submit_fn()
        return {
            "cancel": cancel_response,
            "submit": submit_response,
            "order_id": extract_order_id_from_submit_response(submit_response),
        }

    current_payload = _find_external_exit_order_payload_by_id(
        order_service=order_service,
        account_id=account_id,
        symbol=symbol,
        exit_kind=exit_kind,
        order_id=current_order_id,
    )
    if current_payload is not None:
        current_payload_id = _extract_external_order_id(current_payload)
        if current_payload_id is not None and _payload_matches_exit_preview(current_payload, symbol, desired_preview, exit_kind):
            return _build_reused_exit_order_response(current_payload_id)

        equivalent_payload = _find_equivalent_external_exit_order_payload(
            order_service=order_service,
            account_id=account_id,
            symbol=symbol,
            exit_kind=exit_kind,
            desired_preview=desired_preview,
        )
        equivalent_order_id = _extract_external_order_id(equivalent_payload) if equivalent_payload is not None else None
        if equivalent_order_id is not None and equivalent_order_id != current_payload_id:
            cancel_response = order_service.cancel_order(account_id, current_payload_id)
            return {
                "cancel": cancel_response,
                "submit": None,
                "order_id": equivalent_order_id,
                "reused_existing": True,
            }

        cancel_response = order_service.cancel_order(account_id, current_payload_id)
        submit_response = submit_fn()
        return {
            "cancel": cancel_response,
            "submit": submit_response,
            "order_id": extract_order_id_from_submit_response(submit_response),
        }

    equivalent_payload = _find_equivalent_external_exit_order_payload(
        order_service=order_service,
        account_id=account_id,
        symbol=symbol,
        exit_kind=exit_kind,
        desired_preview=desired_preview,
    )
    equivalent_order_id = _extract_external_order_id(equivalent_payload) if equivalent_payload is not None else None
    if equivalent_order_id is not None:
        return _build_reused_exit_order_response(equivalent_order_id)

    submit_response = submit_fn()
    return {
        "cancel": None,
        "submit": submit_response,
        "order_id": extract_order_id_from_submit_response(submit_response),
    }



def should_manage_exit_orders(
    state: AgentState,
    updated_trade: Trade | None,
) -> bool:
    if state.active_trade is None or updated_trade is None:
        return False

    normalized_trade = _prepare_updated_trade_for_exit_orders(state, updated_trade)
    if normalized_trade.quantity is None or normalized_trade.position_id is None:
        return False

    stop_changed = state.active_trade.stop_loss != normalized_trade.stop_loss
    take_profit_changed = state.active_trade.take_profit != normalized_trade.take_profit
    missing_stop_order = not _has_external_order_id(state.stop_loss_order_id)
    missing_take_profit_order = not _has_external_order_id(state.take_profit_order_id)
    return stop_changed or take_profit_changed or missing_stop_order or missing_take_profit_order



def manage_active_trade_exit_orders(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    state: AgentState,
    updated_trade: Trade | None,
    buy_spread: float = 0.0,
) -> dict | None:
    if not should_manage_exit_orders(state, updated_trade):
        return None

    normalized_trade = _prepare_updated_trade_for_exit_orders(state, updated_trade)
    response: dict[str, dict] = {}

    if state.active_trade is None:
        return None

    if (
        state.active_trade.stop_loss != normalized_trade.stop_loss
        or not _has_external_order_id(state.stop_loss_order_id)
    ):
        desired_stop_loss_preview = build_stop_loss_submission_preview(
            normalized_trade,
            symbol,
            buy_spread=buy_spread,
        )
        response["stop_loss"] = _resolve_exit_order_request(
            order_service=order_service,
            account_id=account_id,
            symbol=symbol,
            exit_kind="stop_loss",
            current_order_id=state.stop_loss_order_id,
            desired_preview=desired_stop_loss_preview,
            submit_fn=lambda: order_service.submit_stop_loss_exit(
                account_id,
                normalized_trade,
                symbol,
                buy_spread=buy_spread,
            ),
        )

    if (
        state.active_trade.take_profit != normalized_trade.take_profit
        or not _has_external_order_id(state.take_profit_order_id)
    ):
        desired_take_profit_preview = build_take_profit_submission_preview(
            normalized_trade,
            symbol,
            buy_spread=buy_spread,
        )
        response["take_profit"] = _resolve_exit_order_request(
            order_service=order_service,
            account_id=account_id,
            symbol=symbol,
            exit_kind="take_profit",
            current_order_id=state.take_profit_order_id,
            desired_preview=desired_take_profit_preview,
            submit_fn=lambda: order_service.submit_take_profit_exit(
                account_id,
                normalized_trade,
                symbol,
                buy_spread=buy_spread,
            ),
        )

    return response or None


__all__ = [
    "find_equivalent_external_pending_order_id",
    "should_submit_order",
    "SubmitAgentOrderResult",
    "submit_agent_order_if_allowed",
    "should_close_active_trade",
    "submit_active_trade_close_if_allowed",
    "has_external_pending_order_id",
    "should_cancel_existing_pending_order",
    "safe_replace_pending_order",
    "should_manage_exit_orders",
    "manage_active_trade_exit_orders",
]

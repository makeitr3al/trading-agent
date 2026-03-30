from typing import Any

from models.agent_state import AgentState
from models.order import Order, OrderStatus
from models.trade import Trade
from broker.order_service import ProprOrderService, extract_order_id_from_submit_response
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


def _get_open_orders_payload(order_service: ProprOrderService, account_id: str) -> list[dict[str, Any]]:
    client = getattr(order_service, "client", None)
    if client is None or not hasattr(client, "get_orders"):
        return []

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


def _values_close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(left - right) <= FLOAT_TOLERANCE


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


def _build_reused_pending_order_response(order_id: str) -> dict[str, Any]:
    return {
        "cancel": None,
        "submit": {"id": order_id, "status": "unchanged"},
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


def should_submit_order(
    state: AgentState,
    order: Order | None,
) -> bool:
    if order is None:
        return False
    if state.active_trade is not None:
        return False
    if state.pending_order is not None:
        return False
    return True



def submit_agent_order_if_allowed(
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    state: AgentState,
    order: Order | None,
) -> dict | None:
    if not should_submit_order(state, order):
        return None

    if order is None:
        return None

    existing_order_id = find_equivalent_external_pending_order_id(
        order_service=order_service,
        account_id=account_id,
        symbol=symbol,
        order=order,
    )
    if existing_order_id is not None:
        return None

    return order_service.submit_pending_order(account_id, order, symbol)



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
        stop_loss_cancel = None
        if _has_external_order_id(state.stop_loss_order_id):
            stop_loss_cancel = order_service.cancel_order(account_id, state.stop_loss_order_id)
        stop_loss_submit = order_service.submit_stop_loss_exit(
            account_id,
            normalized_trade,
            symbol,
            buy_spread=buy_spread,
        )
        response["stop_loss"] = {
            "cancel": stop_loss_cancel,
            "submit": stop_loss_submit,
            "order_id": extract_order_id_from_submit_response(stop_loss_submit),
        }

    if (
        state.active_trade.take_profit != normalized_trade.take_profit
        or not _has_external_order_id(state.take_profit_order_id)
    ):
        take_profit_cancel = None
        if _has_external_order_id(state.take_profit_order_id):
            take_profit_cancel = order_service.cancel_order(account_id, state.take_profit_order_id)
        take_profit_submit = order_service.submit_take_profit_exit(
            account_id,
            normalized_trade,
            symbol,
            buy_spread=buy_spread,
        )
        response["take_profit"] = {
            "cancel": take_profit_cancel,
            "submit": take_profit_submit,
            "order_id": extract_order_id_from_submit_response(take_profit_submit),
        }

    return response or None


__all__ = [
    "find_equivalent_external_pending_order_id",
    "should_submit_order",
    "submit_agent_order_if_allowed",
    "should_close_active_trade",
    "submit_active_trade_close_if_allowed",
    "has_external_pending_order_id",
    "should_cancel_existing_pending_order",
    "safe_replace_pending_order",
    "should_manage_exit_orders",
    "manage_active_trade_exit_orders",
]

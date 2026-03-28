from models.agent_state import AgentState
from models.order import Order
from models.trade import Trade
from broker.order_service import ProprOrderService, extract_order_id_from_submit_response

# TODO: Later add real idempotency.
# TODO: Later add duplicate detection based on external order ids.
# TODO: Later sync with Propr open orders before submit.
# TODO: Later handle partial fills.


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

    if not has_external_pending_order_id(state):
        raise ValueError("Missing external pending order id for replacement")

    cancel_response = order_service.cancel_order(account_id, state.pending_order_id)
    submit_response = order_service.submit_pending_order(account_id, new_order, symbol)
    return {
        "cancel": cancel_response,
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
    return updated_trade.copy(update=updates)



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

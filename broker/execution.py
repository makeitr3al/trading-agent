from models.agent_state import AgentState
from models.order import Order
from broker.order_service import ProprOrderService

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


__all__ = [
    "should_submit_order",
    "submit_agent_order_if_allowed",
    "has_external_pending_order_id",
    "should_cancel_existing_pending_order",
    "safe_replace_pending_order",
]

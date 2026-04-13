from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.execution import (
    manage_active_trade_exit_orders,
    has_external_pending_order_id,
    safe_replace_pending_order,
    should_manage_exit_orders,
    should_cancel_existing_pending_order,
    should_close_active_trade,
    should_submit_order,
    submit_active_trade_close_if_allowed,
    SubmitAgentOrderResult,
    submit_agent_order_if_allowed,
)
from models.agent_state import AgentState
from models.order import Order, OrderType
from models.trade import Trade, TradeDirection, TradeType
import pytest


class FakeProprClient:
    def __init__(self, orders_payload: dict | list[dict]) -> None:
        self.orders_payload = orders_payload
        self.get_orders_calls: list[str] = []

    def get_orders(self, account_id: str) -> dict | list[dict]:
        self.get_orders_calls.append(account_id)
        return self.orders_payload


class FakeProprOrderService:
    def __init__(self, orders_payload: dict | list[dict] | None = None) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.client = FakeProprClient(orders_payload) if orders_payload is not None else None

    def submit_pending_order(self, account_id: str, order: Order, symbol: str, **kwargs: object) -> dict:
        self.calls.append(("submit", account_id, {"order": order, "symbol": symbol, **kwargs}))
        return {"id": "external-new-order", "status": "submitted"}

    def submit_market_close(self, account_id: str, active_trade: Trade, symbol: str) -> dict:
        self.calls.append(("close", account_id, {"trade": active_trade, "symbol": symbol}))
        return {"id": "external-close-order", "status": "submitted"}

    def cancel_order(self, account_id: str, order_id: str) -> dict:
        self.calls.append(("cancel", account_id, order_id))
        return {"id": order_id, "status": "cancelled"}

    def submit_stop_loss_exit(self, account_id: str, active_trade: Trade, symbol: str, buy_spread: float = 0.0) -> dict:
        self.calls.append(("stop_loss", account_id, {"trade": active_trade, "symbol": symbol, "buy_spread": buy_spread}))
        return {"data": [{"orderId": "external-stop-order"}]}

    def submit_take_profit_exit(self, account_id: str, active_trade: Trade, symbol: str, buy_spread: float = 0.0) -> dict:
        self.calls.append(("take_profit", account_id, {"trade": active_trade, "symbol": symbol, "buy_spread": buy_spread}))
        return {"data": [{"orderId": "external-tp-order"}]}



def _make_order() -> Order:
    return Order(
        order_type=OrderType.BUY_STOP,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
        position_size=10.0,
        signal_source="trend_long",
    )



def _make_trade() -> Trade:
    return Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        quantity=1.25,
        position_id="position-1",
    )



def _make_external_pending_entry_order(symbol: str = "EURUSD", order_id: str = "external-existing-order") -> dict:
    return {
        "id": order_id,
        "symbol": symbol,
        "side": "buy",
        "type": "stop",
        "status": "open",
        "price": 110.0,
        "stopLoss": 100.0,
        "takeProfit": 130.0,
    }



def _make_external_changed_pending_entry_order(symbol: str = "EURUSD", order_id: str = "external-existing-order") -> dict:
    payload = _make_external_pending_entry_order(symbol=symbol, order_id=order_id)
    payload["price"] = 111.0
    return payload



def _make_external_stop_loss_exit_order(
    order_id: str = "external-stop-order",
    symbol: str = "BTC/USDC",
    trigger_price: float = 95.0,
) -> dict:
    return {
        "id": order_id,
        "symbol": symbol,
        "side": "sell",
        "positionSide": "long",
        "type": "stop_market",
        "status": "open",
        "quantity": 1.25,
        "triggerPrice": trigger_price,
        "reduceOnly": True,
        "positionId": "position-1",
    }



def _make_external_take_profit_exit_order(
    order_id: str = "external-tp-order",
    symbol: str = "BTC/USDC",
    take_profit_price: float = 110.0,
) -> dict:
    return {
        "id": order_id,
        "symbol": symbol,
        "side": "sell",
        "positionSide": "long",
        "type": "take_profit_limit",
        "status": "open",
        "quantity": 1.25,
        "price": take_profit_price,
        "triggerPrice": take_profit_price,
        "reduceOnly": True,
        "positionId": "position-1",
    }



def test_should_submit_order_returns_false_when_order_is_none() -> None:
    assert should_submit_order(AgentState(), None) is False



def test_should_submit_order_returns_false_when_active_trade_exists() -> None:
    assert should_submit_order(AgentState(active_trade=_make_trade()), _make_order()) is False



def test_should_submit_order_returns_false_when_pending_order_exists() -> None:
    assert should_submit_order(AgentState(pending_order=_make_order()), _make_order()) is False



def test_should_submit_order_returns_true_when_no_active_trade_and_no_pending_order_and_order_exists() -> None:
    assert should_submit_order(AgentState(), _make_order()) is True



def test_submit_agent_order_if_allowed_returns_none_when_blocked() -> None:
    service = FakeProprOrderService()

    result = submit_agent_order_if_allowed(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=AgentState(pending_order=_make_order()),
        order=_make_order(),
    )

    assert result == SubmitAgentOrderResult(None, "submit blocked: pending order already in agent state", None)
    assert service.calls == []



def test_submit_agent_order_if_allowed_submits_when_allowed() -> None:
    service = FakeProprOrderService()

    result = submit_agent_order_if_allowed(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=AgentState(),
        order=_make_order(),
    )

    assert result == SubmitAgentOrderResult({"id": "external-new-order", "status": "submitted"}, None, None)
    assert service.calls[0][0] == "submit"


def test_submit_agent_order_if_allowed_passes_stable_intent_seed_to_submit_pending_order() -> None:
    captured: dict[str, object] = {}

    class TrackingService(FakeProprOrderService):
        def submit_pending_order(self, account_id: str, order: Order, symbol: str, **kwargs: object) -> dict:
            captured.update(kwargs)
            return super().submit_pending_order(account_id, order, symbol, **kwargs)

    service = TrackingService()
    submit_agent_order_if_allowed(
        service,
        "account-1",
        "EURUSD",
        AgentState(),
        _make_order(),
        stable_intent_seed="cycle-seed-1",
    )
    assert captured.get("stable_intent_seed") == "cycle-seed-1"


def test_submit_agent_order_if_allowed_skips_submit_when_equivalent_external_pending_order_exists() -> None:
    service = FakeProprOrderService(orders_payload={"data": [_make_external_pending_entry_order()]})

    result = submit_agent_order_if_allowed(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=AgentState(),
        order=_make_order(),
    )

    assert result == SubmitAgentOrderResult(
        None,
        None,
        "external-existing-order",
    )
    assert service.calls == []
    assert service.client is not None
    assert service.client.get_orders_calls == ["account-1"]



def test_submit_agent_order_if_allowed_ignores_equivalent_order_on_other_symbol() -> None:
    service = FakeProprOrderService(
        orders_payload={"data": [_make_external_pending_entry_order(symbol="BTC/USDC")]}
    )

    result = submit_agent_order_if_allowed(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=AgentState(),
        order=_make_order(),
    )

    assert result == SubmitAgentOrderResult({"id": "external-new-order", "status": "submitted"}, None, None)
    assert service.calls[0][0] == "submit"



def test_submit_agent_order_if_allowed_ignores_reduce_only_exit_orders_when_deduplicating() -> None:
    exit_order_payload = _make_external_pending_entry_order()
    exit_order_payload["reduceOnly"] = True
    exit_order_payload["positionId"] = "position-1"

    service = FakeProprOrderService(orders_payload={"data": [exit_order_payload]})

    result = submit_agent_order_if_allowed(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=AgentState(),
        order=_make_order(),
    )

    assert result == SubmitAgentOrderResult({"id": "external-new-order", "status": "submitted"}, None, None)
    assert service.calls[0][0] == "submit"



class FakeProprOrderServiceSubmitReturnsNone(FakeProprOrderService):
    def submit_pending_order(self, account_id: str, order: Order, symbol: str, **kwargs: object) -> dict | None:
        self.calls.append(("submit", account_id, {"order": order, "symbol": symbol, **kwargs}))
        return None


def test_submit_agent_order_if_allowed_records_skip_when_broker_returns_no_response() -> None:
    service = FakeProprOrderServiceSubmitReturnsNone()

    result = submit_agent_order_if_allowed(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=AgentState(),
        order=_make_order(),
    )

    assert result == SubmitAgentOrderResult(None, "pending order submit returned no confirmation", None)
    assert service.calls[0][0] == "submit"



def test_should_close_active_trade_returns_true_only_when_requested_and_active_trade_exists() -> None:
    assert should_close_active_trade(AgentState(active_trade=_make_trade()), True) is True
    assert should_close_active_trade(AgentState(active_trade=_make_trade()), False) is False
    assert should_close_active_trade(AgentState(), True) is False



def test_submit_active_trade_close_if_allowed_submits_market_close_when_allowed() -> None:
    service = FakeProprOrderService()

    result = submit_active_trade_close_if_allowed(
        order_service=service,
        account_id="account-1",
        symbol="BTC/USDC",
        state=AgentState(active_trade=_make_trade()),
        close_active_trade=True,
    )

    assert result == {"id": "external-close-order", "status": "submitted"}
    assert service.calls[0][0] == "close"



def test_submit_active_trade_close_if_allowed_returns_none_when_not_allowed() -> None:
    service = FakeProprOrderService()

    result = submit_active_trade_close_if_allowed(
        order_service=service,
        account_id="account-1",
        symbol="BTC/USDC",
        state=AgentState(),
        close_active_trade=True,
    )

    assert result is None
    assert service.calls == []



def test_should_cancel_existing_pending_order_returns_true_when_pending_order_exists_and_new_order_exists() -> None:
    assert should_cancel_existing_pending_order(AgentState(pending_order=_make_order()), _make_order()) is True



def test_should_cancel_existing_pending_order_returns_false_when_no_pending_order_exists() -> None:
    assert should_cancel_existing_pending_order(AgentState(), _make_order()) is False



def test_safe_replace_pending_order_submits_directly_when_no_replacement_is_needed_and_allowed() -> None:
    service = FakeProprOrderService()

    result = safe_replace_pending_order(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=AgentState(),
        new_order=_make_order(),
    )

    assert result == {"id": "external-new-order", "status": "submitted"}
    assert service.calls == [
        ("submit", "account-1", {"order": _make_order(), "symbol": "EURUSD", "stable_intent_seed": None}),
    ]



def test_safe_replace_pending_order_reuses_existing_equivalent_order_when_pending_order_id_is_missing() -> None:
    service = FakeProprOrderService(orders_payload={"data": [_make_external_pending_entry_order()]})
    state = AgentState(pending_order=_make_order(), pending_order_id=None)

    result = safe_replace_pending_order(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=state,
        new_order=_make_order(),
    )

    assert result == {
        "cancel": None,
        "submit": {"id": "external-existing-order", "status": "unchanged"},
        "reused_existing": True,
    }
    assert service.calls == []



def test_safe_replace_pending_order_submits_fresh_when_pending_order_id_is_missing_and_no_external_order_exists() -> None:
    service = FakeProprOrderService(orders_payload={"data": []})
    state = AgentState(pending_order=_make_order(), pending_order_id=None)

    result = safe_replace_pending_order(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=state,
        new_order=_make_order(),
    )

    assert result == {
        "cancel": None,
        "submit": {"id": "external-new-order", "status": "submitted"},
    }
    assert service.calls == [
        ("submit", "account-1", {"order": _make_order(), "symbol": "EURUSD", "stable_intent_seed": None}),
    ]



def test_safe_replace_pending_order_reuses_equivalent_external_order_when_local_pending_order_id_is_stale() -> None:
    service = FakeProprOrderService(orders_payload={"data": [_make_external_pending_entry_order(order_id="external-live-order")]})
    state = AgentState(pending_order=_make_order(), pending_order_id="external-stale-order")

    result = safe_replace_pending_order(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=state,
        new_order=_make_order(),
    )

    assert result == {
        "cancel": None,
        "submit": {"id": "external-live-order", "status": "unchanged"},
        "reused_existing": True,
    }
    assert service.calls == []



def test_safe_replace_pending_order_submits_fresh_when_local_pending_order_id_is_stale_and_no_external_order_exists() -> None:
    service = FakeProprOrderService(orders_payload={"data": []})
    state = AgentState(pending_order=_make_order(), pending_order_id="external-stale-order")

    result = safe_replace_pending_order(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=state,
        new_order=_make_order(),
    )

    assert result == {
        "cancel": None,
        "submit": {"id": "external-new-order", "status": "submitted"},
    }
    assert service.calls == [
        ("submit", "account-1", {"order": _make_order(), "symbol": "EURUSD", "stable_intent_seed": None}),
    ]



def test_safe_replace_pending_order_uses_state_pending_order_id_when_external_order_still_exists_and_changed() -> None:
    service = FakeProprOrderService(
        orders_payload={"data": [_make_external_changed_pending_entry_order(order_id="external-old-order")]}
    )
    state = AgentState(pending_order=_make_order(), pending_order_id="external-old-order")

    result = safe_replace_pending_order(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=state,
        new_order=_make_order(),
    )

    assert result == {
        "cancel": {"id": "external-old-order", "status": "cancelled"},
        "submit": {"id": "external-new-order", "status": "submitted"},
    }
    assert service.calls[0] == ("cancel", "account-1", "external-old-order")
    assert service.calls[1][0] == "submit"



def test_safe_replace_pending_order_reuses_state_pending_order_id_when_external_order_still_exists_and_is_unchanged() -> None:
    service = FakeProprOrderService(
        orders_payload={"data": [_make_external_pending_entry_order(order_id="external-old-order")]}
    )
    state = AgentState(pending_order=_make_order(), pending_order_id="external-old-order")

    result = safe_replace_pending_order(
        order_service=service,
        account_id="account-1",
        symbol="EURUSD",
        state=state,
        new_order=_make_order(),
    )

    assert result == {
        "cancel": None,
        "submit": {"id": "external-old-order", "status": "unchanged"},
        "reused_existing": True,
    }
    assert service.calls == []



def test_helper_detects_external_pending_order_id_correctly() -> None:
    assert has_external_pending_order_id(AgentState(pending_order_id="external-1")) is True
    assert has_external_pending_order_id(AgentState(pending_order_id="   ")) is False
    assert has_external_pending_order_id(AgentState(pending_order_id=None)) is False



def test_should_manage_exit_orders_returns_true_when_active_trade_levels_changed() -> None:
    state = AgentState(
        active_trade=_make_trade(),
        stop_loss_order_id="external-stop-order",
        take_profit_order_id="external-tp-order",
    )
    updated_trade = _make_trade().model_copy(update={"stop_loss": 96.0})

    assert should_manage_exit_orders(state, updated_trade) is True



def test_manage_active_trade_exit_orders_reuses_existing_stop_loss_order_when_local_id_is_missing() -> None:
    service = FakeProprOrderService(orders_payload={"data": [_make_external_stop_loss_exit_order()]})
    state = AgentState(active_trade=_make_trade(), stop_loss_order_id=None, take_profit_order_id="external-tp-order")

    result = manage_active_trade_exit_orders(
        order_service=service,
        account_id="account-1",
        symbol="BTC/USDC",
        state=state,
        updated_trade=_make_trade(),
    )

    assert result == {
        "stop_loss": {
            "cancel": None,
            "submit": None,
            "order_id": "external-stop-order",
            "reused_existing": True,
        }
    }
    assert service.calls == []



def test_manage_active_trade_exit_orders_reuses_existing_take_profit_order_when_update_is_requested_but_local_id_is_stale() -> None:
    service = FakeProprOrderService(
        orders_payload={"data": [_make_external_take_profit_exit_order(order_id="external-live-tp", take_profit_price=111.0)]}
    )
    state = AgentState(active_trade=_make_trade(), stop_loss_order_id="external-stop-order", take_profit_order_id="external-stale-tp")
    updated_trade = _make_trade().model_copy(update={"take_profit": 111.0})

    result = manage_active_trade_exit_orders(
        order_service=service,
        account_id="account-1",
        symbol="BTC/USDC",
        state=state,
        updated_trade=updated_trade,
    )

    assert result == {
        "take_profit": {
            "cancel": None,
            "submit": None,
            "order_id": "external-live-tp",
            "reused_existing": True,
        }
    }
    assert service.calls == []



def test_manage_active_trade_exit_orders_reuses_state_stop_loss_order_id_when_external_order_already_matches_desired_levels() -> None:
    service = FakeProprOrderService(orders_payload={"data": [_make_external_stop_loss_exit_order(order_id="external-old-stop")]})
    state = AgentState(active_trade=_make_trade(), stop_loss_order_id="external-old-stop", take_profit_order_id="external-tp-order")
    updated_trade = _make_trade().model_copy(update={"stop_loss": 96.0})
    matching_external_payload = _make_external_stop_loss_exit_order(order_id="external-old-stop", trigger_price=96.0)
    service.client = FakeProprClient({"data": [matching_external_payload]})

    result = manage_active_trade_exit_orders(
        order_service=service,
        account_id="account-1",
        symbol="BTC/USDC",
        state=state,
        updated_trade=updated_trade,
    )

    assert result == {
        "stop_loss": {
            "cancel": None,
            "submit": None,
            "order_id": "external-old-stop",
            "reused_existing": True,
        }
    }
    assert service.calls == []



def test_manage_active_trade_exit_orders_replaces_existing_exit_orders_without_broker_lookup_support() -> None:
    service = FakeProprOrderService()
    state = AgentState(
        active_trade=_make_trade(),
        stop_loss_order_id="external-old-stop",
        take_profit_order_id="external-old-tp",
    )
    updated_trade = _make_trade().model_copy(update={"stop_loss": 96.0, "take_profit": 111.0})

    result = manage_active_trade_exit_orders(
        order_service=service,
        account_id="account-1",
        symbol="BTC/USDC",
        state=state,
        updated_trade=updated_trade,
        buy_spread=1.5,
    )

    assert result is not None
    assert result["stop_loss"]["order_id"] == "external-stop-order"
    assert result["take_profit"]["order_id"] == "external-tp-order"
    assert service.calls[0] == ("cancel", "account-1", "external-old-stop")
    assert service.calls[1][0] == "stop_loss"
    assert service.calls[2] == ("cancel", "account-1", "external-old-tp")
    assert service.calls[3][0] == "take_profit"


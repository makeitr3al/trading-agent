from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.execution import (
    has_external_pending_order_id,
    safe_replace_pending_order,
    should_cancel_existing_pending_order,
    should_submit_order,
    submit_agent_order_if_allowed,
)
from models.agent_state import AgentState
from models.order import Order, OrderType
from models.trade import Trade, TradeDirection, TradeType
import pytest


class FakeProprOrderService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def submit_pending_order(self, account_id: str, order: Order, symbol: str) -> dict:
        self.calls.append(("submit", account_id, {"order": order, "symbol": symbol}))
        return {"id": "external-new-order", "status": "submitted"}

    def cancel_order(self, account_id: str, order_id: str) -> dict:
        self.calls.append(("cancel", account_id, order_id))
        return {"id": order_id, "status": "cancelled"}


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
    )


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

    assert result is None
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

    assert result == {"id": "external-new-order", "status": "submitted"}
    assert service.calls[0][0] == "submit"


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
    assert service.calls == [("submit", "account-1", {"order": _make_order(), "symbol": "EURUSD"})]


def test_safe_replace_pending_order_uses_state_pending_order_id() -> None:
    service = FakeProprOrderService()
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


def test_safe_replace_pending_order_raises_value_error_when_replacement_is_needed_but_pending_order_id_is_missing() -> None:
    service = FakeProprOrderService()
    state = AgentState(pending_order=_make_order(), pending_order_id=None)

    with pytest.raises(ValueError, match="Missing external pending order id for replacement"):
        safe_replace_pending_order(
            order_service=service,
            account_id="account-1",
            symbol="EURUSD",
            state=state,
            new_order=_make_order(),
        )


def test_helper_detects_external_pending_order_id_correctly() -> None:
    assert has_external_pending_order_id(AgentState(pending_order_id="external-1")) is True
    assert has_external_pending_order_id(AgentState(pending_order_id="   ")) is False
    assert has_external_pending_order_id(AgentState(pending_order_id=None)) is False

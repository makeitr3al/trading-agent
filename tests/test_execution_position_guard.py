"""Tests for open-position guards blocking new entry brackets (pyramiding prevention)."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from broker.execution import (
    SUBMIT_BLOCKED_OPEN_POSITION_AT_BROKER,
    open_position_probe_for_symbol,
    safe_replace_pending_order,
    submit_agent_order_if_allowed,
)
from models.agent_state import AgentState
from models.order import Order, OrderType
from models.trade import Trade, TradeDirection, TradeType


class FakeProprClient:
    def __init__(
        self,
        orders_payload: dict | list[dict],
        positions_payload: dict | list[dict] | None = None,
    ) -> None:
        self.orders_payload = orders_payload
        self.positions_payload = positions_payload or {"data": []}
        self.get_orders_calls: list[str] = []
        self.get_positions_calls: list[str] = []

    def get_orders(self, account_id: str) -> dict | list[dict]:
        self.get_orders_calls.append(account_id)
        return self.orders_payload

    def get_positions(self, account_id: str) -> dict | list[dict]:
        self.get_positions_calls.append(account_id)
        return self.positions_payload


class FakeProprOrderService:
    def __init__(
        self,
        orders_payload: dict | list[dict] | None = None,
        positions_payload: dict | list[dict] | None = None,
        *,
        client: FakeProprClient | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, object]] = []
        if client is not None:
            self.client = client
        else:
            self.client = FakeProprClient(orders_payload or {"data": []}, positions_payload)

    def submit_bracket_entry_with_exits(self, account_id: str, order: Order, symbol: str, **kwargs: object) -> dict:
        self.calls.append(("submit_bracket", account_id, {"order": order, "symbol": symbol, **kwargs}))
        return {"status": 201, "data": [{"orderId": "external-new-order"}]}

    def cancel_order(self, account_id: str, order_id: str) -> dict:
        self.calls.append(("cancel", account_id, order_id))
        return {"id": order_id, "status": "cancelled"}


def _limit_entry_order() -> Order:
    return Order(
        order_type=OrderType.BUY_LIMIT,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
        position_size=10.0,
        signal_source="trend_long",
    )


def test_open_position_probe_counts_matching_lenient_rows() -> None:
    positions = {
        "data": [
            {
                "asset": "BTC",
                "status": "open",
                "positionSide": "long",
                "entryPrice": "100",
                "quantity": "1",
            }
        ]
    }
    svc = FakeProprOrderService(positions_payload=positions)
    assert open_position_probe_for_symbol(svc, "acc", "BTC") == 1
    assert open_position_probe_for_symbol(svc, "acc", "ETH") == 0


def test_submit_agent_order_if_allowed_blocked_when_flag_set() -> None:
    order = _limit_entry_order()
    state = AgentState(has_open_broker_position_for_symbol=True)
    svc = FakeProprOrderService()
    out = submit_agent_order_if_allowed(
        svc,
        "acc-1",
        "BTC/USDC",
        state,
        order,
    )
    assert out.skip_reason == SUBMIT_BLOCKED_OPEN_POSITION_AT_BROKER
    assert out.response is None
    assert svc.calls == []


def test_submit_agent_order_if_allowed_blocked_by_fresh_positions_probe() -> None:
    order = _limit_entry_order()
    state = AgentState()
    positions = {
        "data": [
            {
                "symbol": "BTC/USDC",
                "status": "open",
                "positionSide": "long",
                "entryPrice": "100",
                "stopLoss": "90",
                "takeProfit": "120",
                "quantity": "1",
                "positionId": "p1",
            }
        ]
    }
    svc = FakeProprOrderService(positions_payload=positions)
    out = submit_agent_order_if_allowed(svc, "acc-1", "BTC/USDC", state, order)
    assert out.skip_reason == SUBMIT_BLOCKED_OPEN_POSITION_AT_BROKER
    assert out.response is None
    assert svc.calls == []


def test_submit_agent_order_if_allowed_prefers_active_trade_skip_reason() -> None:
    order = _limit_entry_order()
    trade = Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        quantity=1.0,
        position_id="p1",
    )
    positions = {"data": [{"symbol": "BTC/USDC", "status": "open", "positionSide": "long", "entryPrice": "100", "quantity": "1", "positionId": "p1"}]}
    state = AgentState(active_trade=trade, has_open_broker_position_for_symbol=True)
    svc = FakeProprOrderService(positions_payload=positions)
    out = submit_agent_order_if_allowed(svc, "acc-1", "BTC/USDC", state, order)
    assert out.skip_reason == "submit blocked: active trade present"


def test_safe_replace_pending_order_blocked_when_flag_set() -> None:
    order = _limit_entry_order()
    state = AgentState(has_open_broker_position_for_symbol=True)
    svc = FakeProprOrderService()
    out = safe_replace_pending_order(svc, "acc-1", "BTC/USDC", state, order)
    assert out is not None
    assert out["submit"]["status"] == "skipped"
    assert out["submit"]["reason"] == SUBMIT_BLOCKED_OPEN_POSITION_AT_BROKER
    assert svc.calls == []


def test_safe_replace_pending_order_blocked_by_probe_before_bracket() -> None:
    order = _limit_entry_order()
    state = AgentState()
    positions = {
        "data": [
            {
                "symbol": "EURUSD",
                "status": "open",
                "positionSide": "short",
                "entryPrice": "1.1",
                "stopLoss": "1.2",
                "takeProfit": "1.0",
                "quantity": "100",
                "positionId": "x",
            }
        ]
    }
    svc = FakeProprOrderService(positions_payload=positions)
    out = safe_replace_pending_order(svc, "acc-1", "EURUSD", state, order)
    assert out is not None
    assert out["submit"]["status"] == "skipped"
    assert svc.calls == []

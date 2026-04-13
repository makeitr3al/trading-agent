"""Tests for ``sync_agent_state_from_propr`` and REST client interaction."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from broker.state_sync import sync_agent_state_from_propr
from models.agent_state import AgentState
from tests.fixtures.state_sync_fixtures import FakeProprClient


def test_sync_agent_state_from_propr_uses_client_orders_and_positions_endpoints() -> None:
    client = FakeProprClient(
        orders_payload={"data": []},
        positions_payload={"data": []},
    )

    state = sync_agent_state_from_propr(client, "account-1")

    assert isinstance(state, AgentState)
    assert client.calls == [("orders", "account-1"), ("positions", "account-1")]


def test_sync_sets_pending_order_id_when_external_order_id_exists() -> None:
    client = FakeProprClient(
        orders_payload={
            "data": [
                {
                    "orderId": "external-123",
                    "side": "buy",
                    "type": "stop_limit",
                    "price": 110,
                    "stopLoss": 100,
                    "takeProfit": 130,
                    "status": "open",
                }
            ]
        },
        positions_payload={"data": []},
    )

    state = sync_agent_state_from_propr(client, "account-1")

    assert state.pending_order is not None
    assert state.pending_order_id == "external-123"


def test_sync_clears_pending_order_id_when_no_external_order_exists() -> None:
    previous_state = AgentState(
        pending_order_id="external-123",
        last_decision_action="NO_ACTION",
    )
    client = FakeProprClient(
        orders_payload={"data": []},
        positions_payload={"data": []},
    )

    state = sync_agent_state_from_propr(client, "account-1", previous_state)

    assert state.pending_order is None
    assert state.pending_order_id is None
    assert state.last_decision_action == "NO_ACTION"


def test_sync_preserves_strategic_memory_fields_while_replacing_pending_order_and_pending_order_id() -> None:
    previous_state = AgentState(
        pending_order_id="old-order-id",
        last_decision_action="PREPARE_TREND_ORDER",
        last_signal_type="trend_long",
        last_regime="bullish",
        trend_signal_consumed_in_regime=True,
        last_cycle_timestamp="2026-01-01T10:00:00",
    )
    client = FakeProprClient(
        orders_payload={
            "data": [
                {
                    "orderId": "new-order-id",
                    "side": "sell",
                    "type": "limit",
                    "price": 120,
                    "stopLoss": 130,
                    "takeProfit": 100,
                    "status": "open",
                    "signalSource": "trend_short",
                }
            ]
        },
        positions_payload={"data": []},
    )

    state = sync_agent_state_from_propr(client, "account-1", previous_state)

    assert state.pending_order is not None
    assert state.pending_order.signal_source == "trend_short"
    assert state.pending_order_id == "new-order-id"
    assert state.last_decision_action == "PREPARE_TREND_ORDER"
    assert state.last_signal_type == "trend_long"
    assert state.last_regime == "bullish"
    assert state.trend_signal_consumed_in_regime is True
    assert state.last_cycle_timestamp == "2026-01-01T10:00:00"


def test_sync_agent_state_from_propr_allows_multiple_account_positions_when_symbol_filter_is_used() -> None:
    client = FakeProprClient(
        orders_payload={"data": []},
        positions_payload={
            "data": [
                {
                    "symbol": "BTC/USDC",
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100.5",
                    "stopLoss": "95.0",
                    "takeProfit": "110.0",
                    "quantity": "1.25",
                    "positionId": "btc-position",
                },
                {
                    "symbol": "ETH/USDC",
                    "status": "open",
                    "positionSide": "short",
                    "entry": 100,
                    "stopLoss": 105,
                    "takeProfit": 90,
                    "quantity": "2",
                    "positionId": "eth-position",
                },
            ]
        },
    )

    state = sync_agent_state_from_propr(client, "account-1", symbol="BTC/USDC")

    assert state.active_trade is not None
    assert state.active_trade.position_id == "btc-position"
    assert state.account_open_positions_count == 2

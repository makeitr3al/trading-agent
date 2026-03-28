from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from broker.state_sync import (
    build_agent_state_from_propr_data,
    map_propr_order_to_internal,
    map_propr_position_to_internal,
    sync_agent_state_from_propr,
)
from models.agent_state import AgentState
from models.order import OrderStatus, OrderType
from models.trade import TradeDirection, TradeType


class FakeProprClient:
    def __init__(self, orders_payload: dict, positions_payload: dict) -> None:
        self.orders_payload = orders_payload
        self.positions_payload = positions_payload
        self.calls: list[tuple[str, str]] = []

    def get_orders(self, account_id: str) -> dict:
        self.calls.append(("orders", account_id))
        return self.orders_payload

    def get_positions(self, account_id: str) -> dict:
        self.calls.append(("positions", account_id))
        return self.positions_payload


def test_maps_buy_stop_order_to_internal_order() -> None:
    order = map_propr_order_to_internal(
        {
            "side": "buy",
            "type": "stop_limit",
            "price": 110,
            "stopLoss": 100,
            "takeProfit": 130,
            "status": "open",
            "signalSource": "trend_long",
        }
    )

    assert order is not None
    assert order.order_type == OrderType.BUY_STOP
    assert order.signal_source == "trend_long"


def test_maps_sell_limit_order_to_internal_order() -> None:
    order = map_propr_order_to_internal(
        {
            "side": "sell",
            "type": "limit",
            "price": 110,
            "stopLoss": 120,
            "takeProfit": 100,
            "status": "pending",
        }
    )

    assert order is not None
    assert order.order_type == OrderType.SELL_LIMIT


def test_returns_none_when_propr_order_payload_is_incomplete() -> None:
    order = map_propr_order_to_internal(
        {
            "side": "buy",
            "type": "stop_limit",
            "status": "open",
        }
    )

    assert order is None


def test_maps_open_long_position_to_internal_trade() -> None:
    trade = map_propr_position_to_internal(
        {
            "status": "open",
            "positionSide": "long",
            "entryPrice": "100.5",
            "stopLoss": "95.0",
            "takeProfit": "110.0",
            "quantity": "1.25",
            "positionId": "position-123",
        }
    )

    assert trade is not None
    assert trade.direction == TradeDirection.LONG
    assert trade.trade_type == TradeType.TREND
    assert trade.entry == 100.5
    assert trade.quantity == 1.25
    assert trade.position_id == "position-123"


def test_maps_open_short_countertrend_position_to_internal_trade() -> None:
    trade = map_propr_position_to_internal(
        {
            "status": "open",
            "positionSide": "short",
            "entry": 100,
            "stopLoss": 110,
            "takeProfit": 90,
            "quantity": "2",
            "signalSource": "countertrend_short",
        }
    )

    assert trade is not None
    assert trade.direction == TradeDirection.SHORT
    assert trade.trade_type == TradeType.COUNTERTREND


def test_returns_none_when_propr_position_is_not_open() -> None:
    trade = map_propr_position_to_internal(
        {
            "status": "closed",
            "positionSide": "long",
            "entry": 100,
            "stopLoss": 95,
            "takeProfit": 110,
            "quantity": "1",
        }
    )

    assert trade is None


def test_position_with_quantity_zero_is_not_taken_as_active_trade() -> None:
    trade = map_propr_position_to_internal(
        {
            "status": "open",
            "positionSide": "long",
            "entryPrice": "100.5",
            "stopLoss": "95.0",
            "takeProfit": "110.0",
            "quantity": "0",
        }
    )

    assert trade is None


def test_build_agent_state_from_propr_data_returns_state_with_pending_order_only() -> None:
    state = build_agent_state_from_propr_data(
        orders_payload={
            "data": [
                {
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

    assert state.pending_order is not None
    assert state.active_trade is None


def test_build_agent_state_from_propr_data_returns_state_with_active_trade_only() -> None:
    state = build_agent_state_from_propr_data(
        orders_payload={"data": []},
        positions_payload={
            "data": [
                {
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100.5",
                    "stopLoss": "95.0",
                    "takeProfit": "110.0",
                    "quantity": "1.25",
            "positionId": "position-123",
                }
            ]
        },
    )

    assert state.active_trade is not None
    assert state.active_trade.quantity == 1.25
    assert state.active_trade.position_id == "position-123"
    assert state.pending_order is None


def test_build_agent_state_from_propr_data_tracks_exit_order_ids_separately() -> None:
    state = build_agent_state_from_propr_data(
        orders_payload={
            "data": [
                {
                    "orderId": "tp-order-1",
                    "type": "take_profit_limit",
                    "side": "sell",
                    "positionId": "position-123",
                    "reduceOnly": True,
                    "status": "open",
                },
                {
                    "orderId": "sl-order-1",
                    "type": "stop_market",
                    "side": "sell",
                    "positionId": "position-123",
                    "reduceOnly": True,
                    "status": "open",
                },
            ]
        },
        positions_payload={
            "data": [
                {
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100.5",
                    "stopLoss": "95.0",
                    "takeProfit": "110.0",
                    "quantity": "1.25",
                    "positionId": "position-123",
                }
            ]
        },
    )

    assert state.pending_order is None
    assert state.pending_order_id is None
    assert state.stop_loss_order_id == "sl-order-1"
    assert state.take_profit_order_id == "tp-order-1"


def test_build_agent_state_from_propr_data_preserves_strategic_memory_fields_from_previous_state() -> None:
    previous_state = AgentState(
        last_decision_action="NO_ACTION",
        last_signal_type="TREND_LONG",
        last_regime="bullish",
        trend_signal_consumed_in_regime=True,
        last_cycle_timestamp="2026-01-01T10:00:00",
    )

    state = build_agent_state_from_propr_data(
        orders_payload={"data": []},
        positions_payload={"data": []},
        previous_state=previous_state,
    )

    assert state.last_decision_action == "NO_ACTION"
    assert state.last_signal_type == "TREND_LONG"
    assert state.last_regime == "bullish"
    assert state.trend_signal_consumed_in_regime is True
    assert state.last_cycle_timestamp == "2026-01-01T10:00:00"


def test_build_agent_state_from_propr_data_raises_value_error_when_multiple_valid_orders_exist() -> None:
    with pytest.raises(ValueError, match="Multiple valid open orders found in Propr state"):
        build_agent_state_from_propr_data(
            orders_payload={
                "data": [
                    {
                        "side": "buy",
                        "type": "stop_limit",
                        "price": 110,
                        "stopLoss": 100,
                        "takeProfit": 130,
                        "status": "open",
                    },
                    {
                        "side": "sell",
                        "type": "limit",
                        "price": 120,
                        "stopLoss": 130,
                        "takeProfit": 100,
                        "status": "open",
                    },
                ]
            },
            positions_payload={"data": []},
        )


def test_build_agent_state_from_propr_data_raises_value_error_when_multiple_valid_positions_exist() -> None:
    with pytest.raises(ValueError, match="Multiple valid open positions found in Propr state"):
        build_agent_state_from_propr_data(
            orders_payload={"data": []},
            positions_payload={
                "data": [
                    {
                        "status": "open",
                        "positionSide": "long",
                        "entryPrice": "100.5",
                        "stopLoss": "95.0",
                        "takeProfit": "110.0",
                        "quantity": "1.25",
            "positionId": "position-123",
                    },
                    {
                        "status": "open",
                        "positionSide": "short",
                        "entry": 100,
                        "stopLoss": 105,
                        "takeProfit": 90,
                        "quantity": "2",
                    },
                ]
            },
        )


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


def test_position_with_decimal_string_values_is_correctly_read() -> None:
    trade = map_propr_position_to_internal(
        {
            "status": "open",
            "positionSide": "long",
            "entryPrice": "100.125",
            "stopLoss": "95.500",
            "takeProfit": "110.875",
            "quantity": "0.250",
        }
    )

    assert trade is not None
    assert trade.entry == 100.125
    assert trade.stop_loss == 95.5
    assert trade.take_profit == 110.875


def test_open_relevant_order_statuses_are_recognized_as_pending() -> None:
    pending_order = map_propr_order_to_internal(
        {
            "side": "buy",
            "type": "stop_limit",
            "price": "110.0",
            "stopLoss": "100.0",
            "takeProfit": "130.0",
            "status": "partially_filled",
        }
    )

    assert pending_order is not None
    assert pending_order.status == OrderStatus.PENDING



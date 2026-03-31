from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from broker.state_sync import (
    _extract_account_unrealized_pnl_from_payload,
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
    with pytest.raises(ValueError, match="Multiple pending entry orders found in Propr state"):
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
    with pytest.raises(ValueError, match="Multiple open positions found in Propr state"):
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




def test_build_agent_state_from_propr_data_filters_to_requested_symbol_and_tracks_account_totals() -> None:
    state = build_agent_state_from_propr_data(
        orders_payload={
            "data": [
                {
                    "symbol": "BTC/USDC",
                    "orderId": "btc-order",
                    "side": "buy",
                    "type": "stop_limit",
                    "price": 110,
                    "stopLoss": 100,
                    "takeProfit": 130,
                    "status": "open",
                },
                {
                    "symbol": "ETH/USDC",
                    "orderId": "eth-order",
                    "side": "sell",
                    "type": "limit",
                    "price": 120,
                    "stopLoss": 130,
                    "takeProfit": 100,
                    "status": "open",
                },
            ]
        },
        positions_payload={
            "data": [
                {
                    "symbol": "ETH/USDC",
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100.5",
                    "stopLoss": "95.0",
                    "takeProfit": "110.0",
                    "quantity": "1.25",
                    "positionId": "eth-position",
                }
            ]
        },
        symbol="BTC/USDC",
    )

    assert state.pending_order is not None
    assert state.pending_order_id == "btc-order"
    assert state.active_trade is None
    assert state.account_open_entry_orders_count == 2
    assert state.account_open_positions_count == 1


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


def test_build_agent_state_from_propr_data_prefers_account_level_unrealized_pnl() -> None:
    state = build_agent_state_from_propr_data(
        orders_payload={"data": []},
        positions_payload={
            "accountUnrealizedPnl": "42.5",
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
                    "unrealizedPnl": "10.0",
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
                    "unrealizedPnl": "5.0",
                },
            ],
        },
        symbol="BTC/USDC",
    )

    assert state.account_open_positions_count == 2
    assert state.account_unrealized_pnl == 42.5


def test_extract_account_unrealized_pnl_from_payload_aggregates_open_positions_when_account_value_missing() -> None:
    pnl = _extract_account_unrealized_pnl_from_payload(
        {
            "data": [
                {
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100.5",
                    "stopLoss": "95.0",
                    "takeProfit": "110.0",
                    "quantity": "1.25",
                    "unrealizedPnl": "12.25",
                },
                {
                    "status": "open",
                    "positionSide": "short",
                    "entry": 100,
                    "stopLoss": 105,
                    "takeProfit": 90,
                    "quantity": "2",
                    "profitLoss": "-2.75",
                },
            ]
        }
    )

    assert pnl == 9.5


def test_extract_account_unrealized_pnl_from_payload_returns_none_when_payload_has_no_pnl() -> None:
    pnl = _extract_account_unrealized_pnl_from_payload(
        {
            "data": [
                {
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100.5",
                    "stopLoss": "95.0",
                    "takeProfit": "110.0",
                    "quantity": "1.25",
                }
            ]
        }
    )

    assert pnl is None



def test_map_propr_order_to_internal_reads_position_size_and_created_at_aliases() -> None:
    order = map_propr_order_to_internal(
        {
            "side": "buy",
            "type": "stop_limit",
            "entryPrice": "110.0",
            "internal_stop_loss": "100.0",
            "internal_take_profit": "130.0",
            "qty": "0.75",
            "status": "working",
            "submittedAt": "2026-03-30T07:00:00Z",
        }
    )

    assert order is not None
    assert order.status == OrderStatus.PENDING
    assert order.position_size == 0.75
    assert order.created_at == "2026-03-30T07:00:00Z"



def test_map_propr_position_to_internal_reads_alias_fields_and_active_status() -> None:
    trade = map_propr_position_to_internal(
        {
            "status": "active",
            "positionSide": "long",
            "avgEntryPrice": "100.25",
            "internal_stop_loss": "95.5",
            "internal_take_profit": "110.75",
            "size": "1.5",
            "createdAt": "2026-03-30T06:55:00Z",
            "positionId": "position-abc",
        }
    )

    assert trade is not None
    assert trade.entry == 100.25
    assert trade.stop_loss == 95.5
    assert trade.take_profit == 110.75
    assert trade.quantity == 1.5
    assert trade.position_id == "position-abc"
    assert trade.opened_at == "2026-03-30T06:55:00Z"



def test_build_agent_state_from_propr_data_prefers_exit_orders_linked_to_active_position() -> None:
    state = build_agent_state_from_propr_data(
        orders_payload={
            "data": [
                {
                    "orderId": "tp-old-position",
                    "symbol": "BTC/USDC",
                    "type": "take_profit_limit",
                    "side": "sell",
                    "positionId": "old-position",
                    "reduceOnly": True,
                    "status": "open",
                },
                {
                    "orderId": "tp-active-position",
                    "symbol": "BTC/USDC",
                    "type": "take_profit_limit",
                    "side": "sell",
                    "positionId": "active-position",
                    "reduceOnly": True,
                    "status": "open",
                },
                {
                    "orderId": "sl-old-position",
                    "symbol": "BTC/USDC",
                    "type": "stop_market",
                    "side": "sell",
                    "positionId": "old-position",
                    "reduceOnly": True,
                    "status": "open",
                },
                {
                    "orderId": "sl-active-position",
                    "symbol": "BTC/USDC",
                    "type": "stop_market",
                    "side": "sell",
                    "positionId": "active-position",
                    "reduceOnly": True,
                    "status": "open",
                },
            ]
        },
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
                    "positionId": "active-position",
                }
            ]
        },
        symbol="BTC/USDC",
    )

    assert state.active_trade is not None
    assert state.active_trade.position_id == "active-position"
    assert state.stop_loss_order_id == "sl-active-position"
    assert state.take_profit_order_id == "tp-active-position"



def test_build_agent_state_from_propr_data_tracks_unbound_exit_orders_when_no_active_trade_exists() -> None:
    state = build_agent_state_from_propr_data(
        orders_payload={
            "data": [
                {
                    "orderId": "tp-unbound",
                    "symbol": "BTC/USDC",
                    "type": "take_profit_limit",
                    "side": "sell",
                    "reduceOnly": True,
                    "status": "open",
                },
                {
                    "orderId": "sl-unbound",
                    "symbol": "BTC/USDC",
                    "type": "stop_market",
                    "side": "sell",
                    "reduceOnly": True,
                    "status": "open",
                },
            ]
        },
        positions_payload={"data": []},
        symbol="BTC/USDC",
    )

    assert state.active_trade is None
    assert state.stop_loss_order_id == "sl-unbound"
    assert state.take_profit_order_id == "tp-unbound"


def test_build_agent_state_from_propr_data_raises_value_error_when_multiple_stop_loss_exit_orders_exist_for_active_position() -> None:
    with pytest.raises(ValueError, match="Multiple active stop-loss exit orders found for position 'position-123'"):
        build_agent_state_from_propr_data(
            orders_payload={
                "data": [
                    {
                        "orderId": "sl-order-1",
                        "symbol": "BTC/USDC",
                        "type": "stop_market",
                        "side": "sell",
                        "positionId": "position-123",
                        "reduceOnly": True,
                        "status": "open",
                    },
                    {
                        "orderId": "sl-order-2",
                        "symbol": "BTC/USDC",
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
                        "symbol": "BTC/USDC",
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
            symbol="BTC/USDC",
        )



def test_build_agent_state_from_propr_data_raises_value_error_when_exit_orders_belong_to_unrelated_position() -> None:
    with pytest.raises(ValueError, match="Stop-loss exit orders found for unrelated positions in Propr state"):
        build_agent_state_from_propr_data(
            orders_payload={
                "data": [
                    {
                        "orderId": "sl-other-position",
                        "symbol": "BTC/USDC",
                        "type": "stop_market",
                        "side": "sell",
                        "positionId": "old-position",
                        "reduceOnly": True,
                        "status": "open",
                    }
                ]
            },
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
                        "positionId": "active-position",
                    }
                ]
            },
            symbol="BTC/USDC",
        )



def test_build_agent_state_from_propr_data_raises_value_error_when_bound_exit_orders_exist_without_active_position() -> None:
    with pytest.raises(ValueError, match="Take-profit exit orders found without active position in Propr state"):
        build_agent_state_from_propr_data(
            orders_payload={
                "data": [
                    {
                        "orderId": "tp-order-1",
                        "symbol": "BTC/USDC",
                        "type": "take_profit_limit",
                        "side": "sell",
                        "positionId": "position-123",
                        "reduceOnly": True,
                        "status": "open",
                    }
                ]
            },
            positions_payload={"data": []},
            symbol="BTC/USDC",
        )


# ---------------------------------------------------------------------------
# Schema-Logging tests
# ---------------------------------------------------------------------------


def test_map_propr_order_missing_core_fields_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="broker.state_sync"):
        result = map_propr_order_to_internal({"side": "buy", "type": "stop_limit", "status": "open"})

    assert result is None
    assert any("missing required price fields" in r.message for r in caplog.records)


def test_map_propr_order_missing_side_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="broker.state_sync"):
        result = map_propr_order_to_internal(
            {"price": 110, "stopLoss": 100, "takeProfit": 130, "status": "open"}
        )

    assert result is None
    assert any("missing required fields" in r.message for r in caplog.records)


def test_map_propr_order_strict_raises_on_missing_fields() -> None:
    with pytest.raises(ValueError, match="Missing required"):
        map_propr_order_to_internal(
            {"side": "buy", "type": "stop_limit", "status": "open"},
            strict=True,
        )


def test_map_propr_order_strict_raises_on_missing_price_fields() -> None:
    with pytest.raises(ValueError, match="Missing required price fields"):
        map_propr_order_to_internal(
            {
                "side": "buy",
                "type": "stop_limit",
                "status": "open",
                # entry/stop_loss/take_profit all missing
            },
            strict=True,
        )


def test_map_propr_position_missing_fields_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="broker.state_sync"):
        result = map_propr_position_to_internal(
            {"status": "open", "positionSide": "long", "entryPrice": "100.0"}
        )

    assert result is None
    assert any("missing required fields" in r.message for r in caplog.records)


def test_map_propr_position_strict_raises_on_missing_fields() -> None:
    with pytest.raises(ValueError, match="Missing required position fields"):
        map_propr_position_to_internal(
            {"status": "open", "positionSide": "long", "entryPrice": "100.0"},
            strict=True,
        )


def test_map_propr_order_empty_payload_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="broker.state_sync"):
        result = map_propr_order_to_internal({})

    assert result is None
    assert len(caplog.records) >= 1


def test_map_propr_order_unknown_keys_are_ignored() -> None:
    order = map_propr_order_to_internal(
        {
            "side": "buy",
            "type": "stop_limit",
            "price": 110,
            "stopLoss": 100,
            "takeProfit": 130,
            "status": "open",
            "unknownField1": "foo",
            "unknownField2": 42,
        }
    )
    assert order is not None


def test_map_propr_order_wrong_type_values_return_none(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="broker.state_sync"):
        result = map_propr_order_to_internal(
            {
                "side": [1, 2, 3],  # wrong type
                "type": {"nested": "dict"},  # wrong type
                "price": "not-a-number",
                "stopLoss": 100,
                "takeProfit": 130,
                "status": "open",
            }
        )

    assert result is None

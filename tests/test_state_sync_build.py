"""Tests for ``build_agent_state_from_propr_data`` and account PnL extraction."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from broker.state_sync import (
    _extract_account_unrealized_pnl_from_payload,
    build_agent_state_from_propr_data,
)
from models.agent_state import AgentState


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


def test_build_agent_state_from_propr_data_warns_when_multiple_stop_loss_exit_orders_exist_for_active_position(capsys: pytest.CaptureFixture[str]) -> None:
    state = build_agent_state_from_propr_data(
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
    assert state.stop_loss_order_id is None
    assert "Multiple active stop-loss exit orders" in capsys.readouterr().out


def test_build_agent_state_from_propr_data_warns_when_exit_orders_belong_to_unrelated_position(capsys: pytest.CaptureFixture[str]) -> None:
    state = build_agent_state_from_propr_data(
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
    assert state.stop_loss_order_id is None
    assert state.active_trade is not None
    assert "exit orders found for unrelated positions" in capsys.readouterr().out


def test_build_agent_state_from_propr_data_warns_when_bound_exit_orders_exist_without_active_position(capsys: pytest.CaptureFixture[str]) -> None:
    state = build_agent_state_from_propr_data(
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
    assert state.take_profit_order_id is None
    assert state.active_trade is None
    assert "exit orders found without active position" in capsys.readouterr().out


def test_build_agent_state_omits_partial_fill_pending_when_open_position_exists_for_symbol() -> None:
    state = build_agent_state_from_propr_data(
        orders_payload={
            "data": [
                {
                    "symbol": "BTC/USDC",
                    "orderId": "ord-partial",
                    "side": "buy",
                    "type": "stop_limit",
                    "price": 110,
                    "stopLoss": 100,
                    "takeProfit": 130,
                    "status": "partially_filled",
                }
            ]
        },
        positions_payload={
            "data": [
                {
                    "symbol": "BTC/USDC",
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100.0",
                    "stopLoss": "95.0",
                    "takeProfit": "110.0",
                    "quantity": "0.5",
                    "positionId": "pos-1",
                }
            ]
        },
        symbol="BTC/USDC",
    )

    assert state.active_trade is not None
    assert state.active_trade.position_id == "pos-1"
    assert state.pending_order is None
    assert state.pending_order_id is None
    assert state.account_open_entry_orders_count == 1

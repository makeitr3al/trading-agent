"""Unit tests for ``map_propr_order_to_internal`` / ``map_propr_position_to_internal``."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import logging

import pytest

from broker.state_sync import map_propr_order_to_internal, map_propr_position_to_internal
from models.order import OrderStatus, OrderType
from models.trade import TradeDirection, TradeType


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


def test_map_propr_order_missing_core_fields_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="broker.state_sync"):
        result = map_propr_order_to_internal({"side": "buy", "type": "stop_limit", "status": "open"})

    assert result is None
    assert any("missing required price fields" in r.message for r in caplog.records)


def test_map_propr_order_missing_side_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
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
            },
            strict=True,
        )


def test_map_propr_position_missing_fields_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
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
    with caplog.at_level(logging.WARNING, logger="broker.state_sync"):
        result = map_propr_order_to_internal(
            {
                "side": [1, 2, 3],
                "type": {"nested": "dict"},
                "price": "not-a-number",
                "stopLoss": 100,
                "takeProfit": 130,
                "status": "open",
            }
        )

    assert result is None

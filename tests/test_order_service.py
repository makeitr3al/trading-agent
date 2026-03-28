from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from broker.order_service import (
    ProprOrderService,
    build_manual_order_submission_preview,
    build_market_close_submission_preview,
    build_stop_loss_submission_preview,
    build_take_profit_submission_preview,
    build_sdk_create_order_params,
    extract_order_id_from_submit_response,
    generate_intent_id,
    map_internal_order_to_propr_payload,
)
from models.order import Order, OrderType
from models.trade import Trade, TradeDirection, TradeType


class FakeConfig:
    def __init__(self, environment: str = "beta") -> None:
        self.environment = environment


class FakeProprClient:
    def __init__(self, create_status: int = 200, cancel_status: int = 200, environment: str = "beta") -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.create_status = create_status
        self.cancel_status = cancel_status
        self.config = FakeConfig(environment)

    def create_order(self, account_id: str, **order_params: object) -> dict:
        self.calls.append(("create_order", account_id, order_params))
        return {"status": self.create_status, "data": [{"orderId": "urn:prp-order:123"}]}

    def cancel_order(self, account_id: str, order_id: str) -> dict:
        self.calls.append(("cancel_order", account_id, order_id))
        return {"status": self.cancel_status, "orderId": order_id}



def _make_order(order_type: OrderType, position_size: float | None = 10.0) -> Order:
    return Order(
        order_type=order_type,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
        position_size=position_size,
        signal_source="trend_long",
    )



def _make_trade() -> Trade:
    return Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        quantity=0.001,
        position_id="position-123",
    )


def _make_short_trade() -> Trade:
    return Trade(
        trade_type=TradeType.COUNTERTREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=105.0,
        take_profit=95.0,
        quantity=0.001,
        position_id="position-456",
    )



def test_ulid_is_generated_per_order(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = {"value": 0}

    class FakeULID:
        def __str__(self) -> str:
            counter["value"] += 1
            return f"ulid-{counter['value']}"

    monkeypatch.setitem(sys.modules, "ulid", types.SimpleNamespace(ULID=FakeULID))

    first = generate_intent_id()
    second = generate_intent_id()

    assert first == "ulid-1"
    assert second == "ulid-2"
    assert first != second



def test_maps_buy_limit_order_to_documented_create_order_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = map_internal_order_to_propr_payload(_make_order(OrderType.BUY_LIMIT), "BTC/USDC")

    assert params["side"] == "buy"
    assert params["position_side"] == "long"
    assert params["order_type"] == "limit"
    assert params["price"] == "110.0"
    assert params["asset"] == "BTC/USDC"
    assert params["intent_id"] == "ulid-fixed"



def test_maps_buy_stop_order_to_documented_stop_limit_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = map_internal_order_to_propr_payload(_make_order(OrderType.BUY_STOP), "BTC/USDC")

    assert params["order_type"] == "stop_limit"
    assert params["trigger_price"] == "110.0"
    assert params["asset"] == "BTC/USDC"



def test_maps_sell_stop_order_to_documented_stop_limit_parameters_with_short_position_side(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = map_internal_order_to_propr_payload(_make_order(OrderType.SELL_STOP), "BTC/USDC")

    assert params["side"] == "sell"
    assert params["position_side"] == "short"
    assert params["order_type"] == "stop_limit"



def test_includes_documented_asset_base_quote_time_in_force_and_execution_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = map_internal_order_to_propr_payload(_make_order(OrderType.BUY_LIMIT), "BTC/USDC")

    assert params["asset"] == "BTC/USDC"
    assert params["base"] == "BTC"
    assert params["quote"] == "USDC"
    assert params["time_in_force"] == "GTC"
    assert params["reduce_only"] is False
    assert params["close_position"] is False



def test_quantity_price_and_trigger_price_are_decimal_safe_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = map_internal_order_to_propr_payload(_make_order(OrderType.BUY_STOP, position_size=12.5), "BTC/USDC")

    assert params["quantity"] == "12.5"
    assert params["price"] == "110.0"
    assert params["trigger_price"] == "110.0"



def test_build_manual_order_submission_preview_supports_market_and_exit_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = build_manual_order_submission_preview(
        symbol="BTC/USDC",
        side="sell",
        position_side="long",
        order_type="market",
        quantity="0.001",
        reduce_only=True,
        close_position=True,
    )

    assert params["asset"] == "BTC/USDC"
    assert params["side"] == "sell"
    assert params["position_side"] == "long"
    assert params["order_type"] == "market"
    assert params["time_in_force"] == "IOC"
    assert params["quantity"] == "0.001"
    assert params["reduce_only"] is True
    assert params["close_position"] is True
    assert params["intent_id"] == "ulid-fixed"



def test_build_manual_order_submission_preview_includes_position_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = build_manual_order_submission_preview(
        symbol="BTC/USDC",
        side="sell",
        position_side="long",
        order_type="take_profit_limit",
        quantity="0.001",
        price="120000",
        trigger_price="119000",
        reduce_only=True,
        position_id="position-123",
    )

    assert params["position_id"] == "position-123"
    assert params["order_group_id"] is None



def test_build_market_close_submission_preview_maps_long_trade_to_reduce_only_market_sell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = build_market_close_submission_preview(_make_trade(), "BTC/USDC")

    assert params["side"] == "sell"
    assert params["position_side"] == "long"
    assert params["order_type"] == "market"
    assert params["quantity"] == "0.001"
    assert params["reduce_only"] is True
    assert params["close_position"] is True
    assert params["position_id"] == "position-123"


def test_build_stop_loss_submission_preview_maps_short_trade_to_buy_stop_market_with_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = build_stop_loss_submission_preview(_make_short_trade(), "BTC/USDC", buy_spread=1.5)

    assert params["side"] == "buy"
    assert params["position_side"] == "short"
    assert params["order_type"] == "stop_market"
    assert params["trigger_price"] == "106.5"
    assert params["reduce_only"] is True
    assert params["position_id"] == "position-456"


def test_build_take_profit_submission_preview_maps_short_trade_to_buy_take_profit_limit_with_spread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = build_take_profit_submission_preview(_make_short_trade(), "BTC/USDC", buy_spread=1.5)

    assert params["side"] == "buy"
    assert params["position_side"] == "short"
    assert params["order_type"] == "take_profit_limit"
    assert params["price"] == "96.5"
    assert params["trigger_price"] == "96.5"
    assert params["reduce_only"] is True
    assert params["position_id"] == "position-456"



def test_extract_order_id_from_submit_response_reads_response_data_order_id() -> None:
    response = {"data": [{"orderId": "urn:prp-order:123"}]}

    order_id = extract_order_id_from_submit_response(response)

    assert order_id == "urn:prp-order:123"



def test_submit_pending_order_calls_sdk_adapter_with_documented_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeProprClient()
    service = ProprOrderService(client)
    order = _make_order(OrderType.BUY_STOP)
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")

    response = service.submit_pending_order("account-1", order, "BTC/USDC")

    assert client.calls[0][0] == "create_order"
    assert client.calls[0][1] == "account-1"
    params = client.calls[0][2]
    assert params["side"] == "buy"
    assert params["position_side"] == "long"
    assert params["order_type"] == "stop_limit"
    assert params["asset"] == "BTC/USDC"
    assert params["intent_id"] == "ulid-fixed"
    assert response["data"][0]["orderId"] == "urn:prp-order:123"



def test_submit_market_close_calls_sdk_adapter_with_market_exit_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeProprClient()
    service = ProprOrderService(client)
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")

    response = service.submit_market_close("account-1", _make_trade(), "BTC/USDC")

    assert client.calls[0][0] == "create_order"
    params = client.calls[0][2]
    assert params["side"] == "sell"
    assert params["position_side"] == "long"
    assert params["order_type"] == "market"
    assert params["reduce_only"] is True
    assert params["close_position"] is True
    assert params["position_id"] == "position-123"
    assert response["data"][0]["orderId"] == "urn:prp-order:123"



def test_submit_order_preview_calls_sdk_adapter_with_generic_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeProprClient()
    service = ProprOrderService(client)
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")

    preview = build_manual_order_submission_preview(
        symbol="BTC/USDC",
        side="sell",
        position_side="long",
        order_type="take_profit_limit",
        quantity="0.001",
        price="120000",
        trigger_price="119000",
        reduce_only=True,
    )
    response = service.submit_order_preview("account-1", preview)

    assert client.calls[0][0] == "create_order"
    assert client.calls[0][1] == "account-1"
    params = client.calls[0][2]
    assert params["order_type"] == "take_profit_limit"
    assert params["reduce_only"] is True
    assert params["trigger_price"] == "119000"
    assert params["intent_id"] == "ulid-fixed"
    assert response["data"][0]["orderId"] == "urn:prp-order:123"



def test_submit_order_preview_passes_position_id_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeProprClient()
    service = ProprOrderService(client)
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")

    preview = build_manual_order_submission_preview(
        symbol="BTC/USDC",
        side="sell",
        position_side="long",
        order_type="stop_market",
        quantity="0.001",
        trigger_price="50000",
        reduce_only=True,
        position_id="position-123",
    )
    response = service.submit_order_preview("account-1", preview)

    assert client.calls[0][0] == "create_order"
    params = client.calls[0][2]
    assert params["position_id"] == "position-123"
    assert params["intent_id"] == "ulid-fixed"
    assert response["data"][0]["orderId"] == "urn:prp-order:123"



def test_build_sdk_create_order_params_keeps_intent_id_and_position_id_for_documented_raw_call() -> None:
    params = build_sdk_create_order_params(
        {
            "intent_id": "ulid-fixed",
            "side": "buy",
            "asset": "BTC/USDC",
            "position_id": "position-123",
        }
    )

    assert params == {
        "intent_id": "ulid-fixed",
        "side": "buy",
        "asset": "BTC/USDC",
        "position_id": "position-123",
    }



def test_submit_accepts_201_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeProprClient(create_status=201)
    service = ProprOrderService(client)
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")

    response = service.submit_pending_order("account-1", _make_order(OrderType.BUY_LIMIT), "BTC/USDC")

    assert response["status"] == 201



def test_cancel_order_calls_sdk_adapter_cancel_endpoint() -> None:
    client = FakeProprClient()
    service = ProprOrderService(client)

    service.cancel_order("account-1", "order-1")

    assert client.calls[0] == ("cancel_order", "account-1", "order-1")



def test_cancel_accepts_201_as_success() -> None:
    client = FakeProprClient(cancel_status=201)
    service = ProprOrderService(client)

    response = service.cancel_order("account-1", "order-1")

    assert response is not None
    assert response["status"] == 201



def test_reduce_only_and_close_position_are_correctly_mapped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    params = map_internal_order_to_propr_payload(
        _make_order(OrderType.BUY_LIMIT),
        "BTC/USDC",
        reduce_only=True,
        close_position=True,
    )

    assert params["reduce_only"] is True
    assert params["close_position"] is True



def test_raises_value_error_for_invalid_symbol_format() -> None:
    with pytest.raises(ValueError, match="symbol must be in BASE/QUOTE format"):
        map_internal_order_to_propr_payload(_make_order(OrderType.BUY_LIMIT), "BTCUSDC")



def test_raises_value_error_when_account_id_is_empty() -> None:
    service = ProprOrderService(FakeProprClient())

    with pytest.raises(ValueError, match="account_id is required"):
        service.submit_pending_order("", _make_order(OrderType.BUY_STOP), "BTC/USDC")



def test_raises_value_error_when_position_size_missing_or_non_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")
    with pytest.raises(ValueError, match="position_size is required"):
        map_internal_order_to_propr_payload(_make_order(OrderType.BUY_LIMIT, position_size=None), "BTC/USDC")

    with pytest.raises(ValueError, match="position_size must be positive"):
        map_internal_order_to_propr_payload(_make_order(OrderType.BUY_LIMIT, position_size=0.0), "BTC/USDC")



def test_market_close_preview_raises_value_error_when_quantity_missing() -> None:
    trade = _make_trade().copy(update={"quantity": None})

    with pytest.raises(ValueError, match="active trade quantity is required for market close"):
        build_market_close_submission_preview(trade, "BTC/USDC")



def test_manual_preview_raises_value_error_for_non_positive_quantity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")

    with pytest.raises(ValueError, match="quantity must be positive"):
        build_manual_order_submission_preview(
            symbol="BTC/USDC",
            side="buy",
            position_side="long",
            order_type="market",
            quantity="0",
        )


def test_submit_order_preview_retries_with_beta_base_asset_on_exchange_asset_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    class BetaFallbackClient(FakeProprClient):
        def create_order(self, account_id: str, **order_params: object) -> dict:
            self.calls.append(("create_order", account_id, order_params))
            if len(self.calls) == 1:
                raise ValueError("[404] 13450: exchange_asset_not_found")
            return {"status": 200, "data": [{"orderId": "urn:prp-order:beta-fallback"}]}

    client = BetaFallbackClient(environment="beta")
    service = ProprOrderService(client)
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")

    preview = build_manual_order_submission_preview(
        symbol="BTC/USDC",
        side="buy",
        position_side="long",
        order_type="limit",
        quantity="0.001",
        price="100000",
    )
    response = service.submit_order_preview("account-1", preview)

    assert len(client.calls) == 2
    assert client.calls[0][2]["asset"] == "BTC/USDC"
    assert client.calls[1][2]["asset"] == "BTC"
    assert response["data"][0]["orderId"] == "urn:prp-order:beta-fallback"


def test_submit_order_preview_does_not_retry_outside_beta(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoFallbackClient(FakeProprClient):
        def create_order(self, account_id: str, **order_params: object) -> dict:
            self.calls.append(("create_order", account_id, order_params))
            raise ValueError("[404] 13450: exchange_asset_not_found")

    client = NoFallbackClient(environment="prod")
    service = ProprOrderService(client)
    monkeypatch.setattr("broker.order_service.generate_intent_id", lambda: "ulid-fixed")

    preview = build_manual_order_submission_preview(
        symbol="BTC/USDC",
        side="buy",
        position_side="long",
        order_type="limit",
        quantity="0.001",
        price="100000",
    )

    with pytest.raises(ValueError, match="exchange_asset_not_found"):
        service.submit_order_preview("account-1", preview)

    assert len(client.calls) == 1

from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.propr_client import ProprClient
from config.propr_config import ProprConfig


class FakeSdkClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.account_id: str | None = None
        self.calls: list[tuple[str, object]] = []

    def setup(self, account_id: str | None = None) -> str:
        self.account_id = account_id
        self.calls.append(("setup", account_id))
        return account_id or ""

    def health(self) -> dict[str, Any]:
        self.calls.append(("health", None))
        return {"status": "OK"}

    def get_user(self) -> dict[str, Any]:
        self.calls.append(("get_user", None))
        return {"userId": "user-1"}

    def get_challenge_attempts(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("get_challenge_attempts", kwargs))
        return [{"attemptId": "attempt-1", "accountId": "account-1", "status": "active"}]

    def get_orders(self) -> list[dict[str, Any]]:
        self.calls.append(("get_orders", self.account_id))
        return [{"orderId": "order-1"}]

    def get_positions(self) -> list[dict[str, Any]]:
        self.calls.append(("get_positions", self.account_id))
        return [{"positionId": "position-1"}]

    def get_trades(self) -> list[dict[str, Any]]:
        self.calls.append(("get_trades", self.account_id))
        return [{"tradeId": "trade-1"}]

    def get_margin_config(self, asset: str) -> dict[str, Any]:
        self.calls.append(("get_margin_config", (self.account_id, asset)))
        return {"configId": "cfg-1", "asset": asset}

    def get_leverage_limits(self) -> dict[str, Any]:
        self.calls.append(("get_leverage_limits", None))
        return {"defaultMax": 2, "overrides": {"BTC": 5, "ETH": 5}}

    def create_order(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(("create_order", kwargs))
        return [{"orderId": "order-created-legacy-1"}]

    def create_orders(self, orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        self.calls.append(("create_orders", orders))
        return [{"orderId": "order-created-raw-1"}]

    def cancel_order(self, order_id: str) -> dict[str, Any] | None:
        self.calls.append(("cancel_order", order_id))
        return {"orderId": order_id, "status": "cancelled"}


def test_health_check_maps_to_sdk_health(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    result = client.health_check()

    assert result == {"status": "OK"}
    assert client.sdk_client.calls[0] == ("health", None)


def test_get_user_profile_maps_to_sdk_user(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    result = client.get_user_profile()

    assert result == {"userId": "user-1"}
    assert client.sdk_client.calls[0] == ("get_user", None)


def test_get_challenge_attempts_wraps_sdk_list_response(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    result = client.get_challenge_attempts(status="active")

    assert result == {"data": [{"attemptId": "attempt-1", "accountId": "account-1", "status": "active"}]}
    assert client.sdk_client.calls[0] == ("get_challenge_attempts", {"status": "active"})


def test_account_endpoints_set_sdk_account_id_before_calls(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    orders = client.get_orders("acc-1")
    positions = client.get_positions("acc-1")
    trades = client.get_trades("acc-1")

    assert orders == {"data": [{"orderId": "order-1"}]}
    assert positions == {"data": [{"positionId": "position-1"}]}
    assert trades == {"data": [{"tradeId": "trade-1"}]}
    assert client.sdk_client.calls[0] == ("setup", "acc-1")
    assert client.sdk_client.calls[1] == ("get_orders", "acc-1")
    assert client.sdk_client.calls[2] == ("setup", "acc-1")
    assert client.sdk_client.calls[3] == ("get_positions", "acc-1")
    assert client.sdk_client.calls[4] == ("setup", "acc-1")
    assert client.sdk_client.calls[5] == ("get_trades", "acc-1")


def test_get_margin_config_sets_account_and_calls_sdk(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    result = client.get_margin_config("acc-1", "BTC")

    assert result == {"configId": "cfg-1", "asset": "BTC"}
    assert client.sdk_client.calls[0] == ("setup", "acc-1")
    assert client.sdk_client.calls[1] == ("get_margin_config", ("acc-1", "BTC"))


def test_get_effective_leverage_limits_maps_to_sdk(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    result = client.get_effective_leverage_limits()

    assert result == {"defaultMax": 2, "overrides": {"BTC": 5, "ETH": 5}}
    assert client.sdk_client.calls[0] == ("get_leverage_limits", None)


def test_create_order_uses_raw_batch_path_with_documented_payload(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    result = client.create_order(
        "acc-1",
        intent_id="ulid-fixed",
        side="buy",
        position_side="long",
        order_type="limit",
        asset="BTC/USDC",
        base="BTC",
        quote="USDC",
        quantity="1",
        price="100000",
        trigger_price=None,
        time_in_force="GTC",
        reduce_only=False,
        close_position=False,
    )

    assert result == {"data": [{"orderId": "order-created-raw-1"}]}
    assert client.sdk_client.calls[0] == ("setup", "acc-1")
    assert client.sdk_client.calls[1][0] == "create_orders"
    raw_order = client.sdk_client.calls[1][1][0]
    assert raw_order["accountId"] == "acc-1"
    assert raw_order["intentId"] == "ulid-fixed"
    assert raw_order["asset"] == "BTC/USDC"
    assert raw_order["type"] == "limit"


def test_create_order_uses_raw_batch_path_when_position_id_is_present(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    result = client.create_order(
        "acc-1",
        intent_id="ulid-fixed",
        side="sell",
        position_side="long",
        order_type="take_profit_limit",
        asset="BTC/USDC",
        base="BTC",
        quote="USDC",
        quantity="0.001",
        price="120000",
        trigger_price="119000",
        time_in_force="GTC",
        reduce_only=True,
        close_position=False,
        position_id="position-123",
    )

    assert result == {"data": [{"orderId": "order-created-raw-1"}]}
    assert client.sdk_client.calls[0] == ("setup", "acc-1")
    assert client.sdk_client.calls[1][0] == "create_orders"
    raw_order = client.sdk_client.calls[1][1][0]
    assert raw_order["positionId"] == "position-123"
    assert raw_order["type"] == "take_profit_limit"
    assert raw_order["reduceOnly"] is True


def test_cancel_order_sets_account_and_uses_sdk_cancel(monkeypatch) -> None:
    monkeypatch.setattr("broker.propr_client.SDKProprClient", FakeSdkClient)
    client = ProprClient(ProprConfig(api_key="api-key-1"))

    result = client.cancel_order("acc-1", "order-1")

    assert result == {"orderId": "order-1", "status": "cancelled"}
    assert client.sdk_client.calls[0] == ("setup", "acc-1")
    assert client.sdk_client.calls[1] == ("cancel_order", "order-1")

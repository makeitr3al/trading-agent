from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.asset_guard import evaluate_asset_execution_guard, extract_base_asset, get_max_leverage_for_asset


class FakeClient:
    def __init__(self, tradeable: bool = True, limits: dict | None = None) -> None:
        self.tradeable = tradeable
        self.limits = limits or {"defaultMax": 2, "overrides": {"BTC": 5, "ETH": 5}}
        self.calls: list[tuple[str, object]] = []

    def get_margin_config(self, account_id: str, asset: str) -> dict:
        self.calls.append(("get_margin_config", (account_id, asset)))
        if not self.tradeable:
            raise ValueError("not found")
        return {"configId": "cfg-1", "asset": asset, "leverage": 1}

    def get_effective_leverage_limits(self) -> dict:
        self.calls.append(("get_effective_leverage_limits", None))
        return self.limits

    def update_margin_config(self, account_id: str, config_id: str, asset: str, leverage: int, margin_mode: str = "cross") -> dict:
        self.calls.append(("update_margin_config", (account_id, config_id, asset, leverage)))
        return {"configId": config_id, "asset": asset, "leverage": leverage}



def test_extract_base_asset_reads_base_from_symbol() -> None:
    assert extract_base_asset("BTC/USDC") == "BTC"



def test_get_max_leverage_for_asset_uses_override_when_present() -> None:
    limits = {"defaultMax": 2, "overrides": {"BTC": 5}}
    assert get_max_leverage_for_asset(limits, "BTC") == 5



def test_get_max_leverage_for_asset_falls_back_to_default() -> None:
    limits = {"defaultMax": 2, "overrides": {"BTC": 5}}
    assert get_max_leverage_for_asset(limits, "SOL") == 2



def test_asset_guard_blocks_when_asset_is_not_tradeable() -> None:
    result = evaluate_asset_execution_guard(
        client=FakeClient(tradeable=False),
        account_id="acc-1",
        symbol="BTC/USDC",
        desired_leverage=1,
    )

    assert result.allow_execution is False
    assert result.reason == "asset not tradeable"
    assert result.asset == "BTC"



def test_asset_guard_caps_leverage_when_desired_exceeds_max() -> None:
    result = evaluate_asset_execution_guard(
        client=FakeClient(),
        account_id="acc-1",
        symbol="BTC/USDC",
        desired_leverage=6,
    )

    assert result.allow_execution is True
    assert result.desired_leverage == 6
    assert result.max_leverage == 5
    assert result.effective_leverage == 5



def test_asset_guard_allows_when_asset_is_tradeable_and_leverage_within_limit() -> None:
    result = evaluate_asset_execution_guard(
        client=FakeClient(),
        account_id="acc-1",
        symbol="ETH/USDC",
        desired_leverage=3,
    )

    assert result.allow_execution is True
    assert result.reason is None
    assert result.asset == "ETH"
    assert result.max_leverage == 5
    assert result.effective_leverage == 3


def test_get_max_leverage_for_asset_new_format_crypto() -> None:
    limits = {"defaults": {"crypto": 2, "equity": 4, "commodity": 4}, "overrides": {"BTC": 5, "ETH": 5}}
    assert get_max_leverage_for_asset(limits, "BTC") == 5
    assert get_max_leverage_for_asset(limits, "SOL") == 2
    assert get_max_leverage_for_asset(limits, "XRP") == 2


def test_get_max_leverage_for_asset_new_format_hip3() -> None:
    limits = {"defaults": {"crypto": 2, "equity": 4, "commodity": 4}, "overrides": {"BTC": 5}}
    assert get_max_leverage_for_asset(limits, "AAPL", is_hip3=True) == 4


def test_asset_guard_sets_leverage_on_margin_config() -> None:
    client = FakeClient()
    result = evaluate_asset_execution_guard(
        client=client,
        account_id="acc-1",
        symbol="BTC",
        desired_leverage=3,
    )
    assert result.allow_execution is True
    assert result.effective_leverage == 3
    margin_calls = [c for c in client.calls if c[0] == "update_margin_config"]
    assert len(margin_calls) == 1
    assert margin_calls[0][1][3] == 3  # leverage parameter

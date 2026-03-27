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
        return {"configId": "cfg-1", "asset": asset}

    def get_effective_leverage_limits(self) -> dict:
        self.calls.append(("get_effective_leverage_limits", None))
        return self.limits



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



def test_asset_guard_blocks_when_desired_leverage_exceeds_max() -> None:
    result = evaluate_asset_execution_guard(
        client=FakeClient(),
        account_id="acc-1",
        symbol="BTC/USDC",
        desired_leverage=6,
    )

    assert result.allow_execution is False
    assert result.reason == "configured leverage exceeds max allowed"
    assert result.max_leverage == 5



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

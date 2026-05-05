from __future__ import annotations

from datetime import datetime

import pytest

from app.trading_app import run_app_cycle
from broker.asset_guard import AssetGuardResult
from broker.health_guard import HealthGuardResult
from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from models.order import OrderType
from tests.fixtures.trading_app_fixtures import (
    FakeClient,
    FakeOrderService,
    make_challenge_context,
    make_order,
    make_strategy_result,
)


def _touching_candle(entry: float) -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            open=100.0,
            high=max(101.0, entry + 0.01),
            low=99.0,
            close=100.5,
        )
    ]


def test_trend_stop_trigger_submits_market_bracket_when_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()
    assert order.order_type == OrderType.BUY_STOP

    captured: dict[str, object] = {}

    class TriggerOrderService(FakeOrderService):
        def submit_market_entry_bracket_with_exits(self, account_id, order, symbol, **kwargs):
            captured["account_id"] = account_id
            captured["order"] = order
            captured["symbol"] = symbol
            return {"data": [{"orderId": "urn:prp-order:trigger-1"}]}

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, reason=None, asset="BTC", desired_leverage=desired_leverage, max_leverage=5))

    result = run_app_cycle(
        client=FakeClient(environment="beta"),
        order_service=TriggerOrderService(),
        symbol="BTC/USDC",
        candles=_touching_candle(order.entry),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="live",
        symbol_spec=None,  # tests use FakeClient (not ProprClient), so symbol spec isn't required by preconditions
    )

    assert result.submitted_order is True
    assert result.execution_response is not None
    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order_id is not None
    assert captured["symbol"] == "BTC/USDC"


def test_trend_stop_trigger_does_nothing_when_not_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    class TriggerOrderService(FakeOrderService):
        def submit_market_entry_bracket_with_exits(self, *_args, **_kwargs):
            raise AssertionError("should not submit when trigger not touched")

    untouched = [
        Candle(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
        )
    ]

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(environment="beta"),
        order_service=TriggerOrderService(),
        symbol="BTC/USDC",
        candles=untouched,
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="live",
    )

    assert result.submitted_order is False


def test_trend_stop_trigger_respects_mode_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TREND_STOP_TRIGGER_MODE", "disabled")
    order = make_order()

    class TriggerOrderService(FakeOrderService):
        def submit_market_entry_bracket_with_exits(self, *_args, **_kwargs):
            raise AssertionError("should not submit when trigger mode disabled")

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(environment="beta"),
        order_service=TriggerOrderService(),
        symbol="BTC/USDC",
        candles=_touching_candle(order.entry),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="live",
    )

    assert result.submitted_order is False


"""Health, asset, and symbol-spec guards; live vs golden execution policy."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from app.trading_app import run_app_cycle
from broker.asset_guard import AssetGuardResult
from broker.execution import SubmitAgentOrderResult
from broker.health_guard import HealthGuardResult
from broker.propr_client import ProprClient
from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.order import Order, OrderType
from tests.fixtures.trading_app_fixtures import (
    FakeClient,
    FakeOrderService,
    make_candles,
    make_challenge_context,
    make_order,
    make_strategy_result,
)


def test_app_cycle_blocks_early_when_core_service_is_not_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.trading_app.fetch_and_check_core_service_health",
        lambda client: HealthGuardResult(allow_trading=False, reason="core service not healthy", core_status="ERROR"),
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.skipped_reason == "core service not healthy"
    assert result.challenge_context is None
    assert result.synced_state is None
    assert result.health_guard_result is not None
    assert result.health_guard_result.allow_trading is False


def test_app_cycle_continues_when_core_service_is_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    health_calls = {"count": 0}
    synced_state = AgentState()
    strategy_result = make_strategy_result()
    post_cycle_state = AgentState()

    def _healthy(client):
        health_calls["count"] += 1
        return HealthGuardResult(allow_trading=True, core_status="OK")

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", _healthy)
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert health_calls["count"] == 1
    assert result.challenge_context is not None
    assert result.health_guard_result is not None
    assert result.health_guard_result.allow_trading is True


def test_app_cycle_can_skip_health_check_when_require_healthy_core_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def _should_not_run(client):
        raise AssertionError("health check should have been skipped")

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", _should_not_run)
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: None)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        require_healthy_core=False,
    )

    assert result.skipped_reason == "no active challenge"
    assert result.health_guard_result is None


def test_blocks_execution_when_asset_is_not_tradeable(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=False, reason="asset not tradeable", asset="EUR", desired_leverage=desired_leverage, max_leverage=None))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        desired_leverage=1,
    )

    assert result.execution_response is None
    assert result.submitted_order is False
    assert result.replaced_order is False
    assert result.skipped_reason == "asset not tradeable"
    assert result.asset_guard_result is not None
    assert result.asset_guard_result.allow_execution is False


def test_blocks_execution_when_configured_leverage_exceeds_max(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=False, reason="configured leverage exceeds max allowed", asset="BTC", desired_leverage=desired_leverage, max_leverage=5))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        desired_leverage=6,
    )

    assert result.execution_response is None
    assert result.skipped_reason == "configured leverage exceeds max allowed"
    assert result.asset_guard_result is not None
    assert result.asset_guard_result.max_leverage == 5


def test_app_cycle_exposes_asset_guard_result_when_execution_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="BTC", desired_leverage=desired_leverage, max_leverage=5))
    monkeypatch.setattr(
        "app.trading_app.submit_agent_order_if_allowed",
        lambda *args, **kwargs: SubmitAgentOrderResult({"submitted": True}, None, None),
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        desired_leverage=3,
    )

    assert result.asset_guard_result is not None
    assert result.asset_guard_result.allow_execution is True
    assert result.asset_guard_result.desired_leverage == 3


def test_app_cycle_recalculates_pending_order_with_symbol_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    from models.symbol_spec import SymbolSpec

    order = Order(
        order_type=OrderType.BUY_STOP,
        entry=107.0,
        stop_loss=100.0,
        take_profit=121.0,
        position_size=999.0,
        signal_source="trend_long",
    )

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(risk_per_trade_pct=0.01),
        account_balance=10000.0,
        allow_execution=False,
        desired_leverage=2,
        symbol_spec=SymbolSpec(
            symbol="BTC/USDC",
            asset="BTC",
            base="BTC",
            quote="USDC",
            quantity_decimals=3,
            max_leverage=5,
            source_name="test",
        ),
    )

    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order is not None
    assert result.post_cycle_state.pending_order.position_size == pytest.approx(14.285, abs=1e-9)
    assert result.strategy_result is not None
    assert result.strategy_result.order is not None
    assert result.strategy_result.order.position_size == pytest.approx(14.285, abs=1e-9)


def test_live_execution_is_blocked_when_symbol_spec_is_missing_and_order_would_be_submitted(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    live_client = ProprClient.__new__(ProprClient)

    result = run_app_cycle(
        client=live_client,
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        symbol_spec=None,
        data_source="live",
    )

    assert result.execution_response is None
    assert result.submitted_order is False
    assert result.replaced_order is False
    assert result.skipped_reason == "missing symbol spec for live execution"
    assert result.symbol_spec_loaded is False


def test_live_dry_run_is_not_blocked_when_symbol_spec_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=False,
        symbol_spec=None,
        data_source="live",
    )

    assert result.skipped_reason == "execution disabled"
    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order is not None
    assert result.symbol_spec_loaded is False


def test_golden_mode_remains_blocked_from_submit_regardless(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="golden",
    )

    assert result.execution_response is None
    assert result.submitted_order is False
    assert result.replaced_order is False
    assert result.skipped_reason == "submit is not allowed with golden data source"


def test_execution_proceeds_when_symbol_spec_is_present_and_guards_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    from models.symbol_spec import SymbolSpec

    order = make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="BTC", desired_leverage=desired_leverage, max_leverage=5))
    monkeypatch.setattr(
        "app.trading_app.submit_agent_order_if_allowed",
        lambda *args, **kwargs: SubmitAgentOrderResult({"submitted": True}, None, None),
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        symbol_spec=SymbolSpec(
            symbol="BTC/USDC",
            asset="BTC",
            base="BTC",
            quote="USDC",
            quantity_decimals=3,
            price_decimals=None,
            max_leverage=5,
            source_name="test",
        ),
        data_source="live",
    )

    assert result.submitted_order is True
    assert result.skipped_reason is None
    assert result.symbol_spec_loaded is True

"""Challenge context, risk guard, pending order submit/replace, and order-id wiring."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from app.trading_app import AppCycleResult, run_app_cycle
from broker.asset_guard import AssetGuardResult
from broker.execution import SubmitAgentOrderResult
from broker.health_guard import HealthGuardResult
from models.agent_state import AgentState
from config.strategy_config import StrategyConfig
from tests.fixtures.trading_app_fixtures import (
    FakeClient,
    FakeOrderService,
    make_candles,
    make_challenge_context,
    make_order,
    make_strategy_result,
)


def test_returns_skipped_result_when_no_active_challenge_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: None)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.skipped_reason == "no active challenge"
    assert result.synced_state is None
    assert result.strategy_result is None
    assert result.post_cycle_state is None


def test_runs_full_app_cycle_when_active_challenge_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    synced_state = AgentState()
    strategy_result = make_strategy_result()
    post_cycle_state = AgentState()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
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

    assert isinstance(result, AppCycleResult)
    assert result.challenge_context is not None
    assert result.synced_state == synced_state
    assert result.strategy_result == strategy_result
    assert result.post_cycle_state == post_cycle_state


def test_submits_new_order_when_no_synced_pending_order_exists_and_post_cycle_state_has_pending_order(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))
    monkeypatch.setattr(
        "app.trading_app.submit_agent_order_if_allowed",
        lambda *args, **kwargs: SubmitAgentOrderResult({"submitted": True}, None, None),
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.submitted_order is True
    assert result.replaced_order is False
    assert result.execution_response is not None


def test_reconciles_pending_order_id_when_equivalent_broker_pending_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_execution import FakeProprOrderService, _make_external_pending_entry_order

    order = make_order()
    service = FakeProprOrderService(
        orders_payload={"data": [_make_external_pending_entry_order(symbol="EURUSD")]},
    )

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=service,
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="live",
    )

    assert result.submitted_order is False
    assert result.skipped_reason is None
    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order_id == "external-existing-order"
    assert service.calls == []


def test_replaces_existing_order_when_synced_pending_order_exists_and_post_cycle_state_has_pending_order(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    synced_state = AgentState(pending_order=order, pending_order_id="external-order-1")
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))
    monkeypatch.setattr(
        "app.trading_app.safe_replace_pending_order",
        lambda order_service, account_id, symbol, state, new_order, **kwargs: {"cancel": {"ok": True}, "submit": {"ok": True}},
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.replaced_order is True
    assert result.submitted_order is False
    assert result.execution_response is not None


def test_does_not_execute_when_post_cycle_state_has_no_pending_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(None), AgentState(pending_order=None)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.execution_response is None
    assert result.submitted_order is False
    assert result.replaced_order is False


def test_propagates_value_error_when_replace_is_needed_but_synced_pending_order_id_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState(pending_order=order, pending_order_id=None))
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))

    def _raise(*args, **kwargs):
        raise ValueError("Missing external pending order id for replacement")

    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", _raise)

    with pytest.raises(ValueError, match="Missing external pending order id for replacement"):
        run_app_cycle(
            client=FakeClient(),
            order_service=FakeOrderService(),
            symbol="EUR/USD",
            candles=make_candles(),
            config=StrategyConfig(),
            account_balance=10000.0,
        )


def test_blocks_execution_when_risk_guard_says_no_active_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: None)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.skipped_reason == "no active challenge"
    assert result.submitted_order is False
    assert result.replaced_order is False


def test_blocks_execution_when_challenge_has_failure_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context(failure_reason="breach"))
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.execution_response is None
    assert result.skipped_reason == "challenge has failure reason"


def test_blocks_execution_when_drawdown_threshold_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context(max_drawdown=100.0))
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        max_allowed_drawdown=100.0,
    )

    assert result.execution_response is None
    assert result.skipped_reason == "max drawdown threshold reached"


def test_still_allows_execution_when_guards_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context(max_drawdown=50.0))
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=5))
    monkeypatch.setattr(
        "app.trading_app.submit_agent_order_if_allowed",
        lambda *args, **kwargs: SubmitAgentOrderResult({"submitted": True}, None, None),
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        max_allowed_drawdown=100.0,
        desired_leverage=3,
    )

    assert result.submitted_order is True or result.replaced_order is True
    assert result.asset_guard_result is not None
    assert result.asset_guard_result.allow_execution is True


def test_app_cycle_exposes_risk_guard_result_in_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(None), AgentState(pending_order=None)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        max_allowed_drawdown=100.0,
    )

    assert result.risk_guard_result is not None


def test_app_cycle_replaces_using_synced_external_pending_order_id(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    synced_state = AgentState(pending_order=order, pending_order_id="external-order-42")
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))

    def _fake_replace(order_service, account_id, symbol, state, new_order, **kwargs):
        captured["pending_order_id"] = state.pending_order_id
        return {"cancel": {"id": state.pending_order_id}, "submit": {"data": [{"orderId": "urn:prp-order:456"}]}}

    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", _fake_replace)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert captured["pending_order_id"] == "external-order-42"
    assert result.replaced_order is True


def test_app_cycle_stores_new_pending_order_id_from_submit_response_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))
    monkeypatch.setattr(
        "app.trading_app.submit_agent_order_if_allowed",
        lambda *args, **kwargs: SubmitAgentOrderResult(
            {"data": [{"orderId": "urn:prp-order:123"}]},
            None,
            None,
        ),
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order_id == "urn:prp-order:123"


def test_app_cycle_stores_new_pending_order_id_from_replace_submit_response_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    synced_state = AgentState(pending_order=order, pending_order_id="external-order-42")
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))
    monkeypatch.setattr(
        "app.trading_app.safe_replace_pending_order",
        lambda order_service, account_id, symbol, state, new_order, **kwargs: {
            "cancel": {"id": "external-order-42"},
            "submit": {"data": [{"orderId": "urn:prp-order:456"}]},
        },
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order_id == "urn:prp-order:456"

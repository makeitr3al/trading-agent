from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.trading_app import AppCycleResult, run_app_cycle
from broker.health_guard import HealthGuardResult
from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.propr_challenge import ActiveChallengeContext, ProprChallengeAttempt
from models.runner_result import StrategyRunResult


class FakeClient:
    pass


class FakeOrderService:
    pass


def _make_candles() -> list[Candle]:
    return [
        Candle(
            timestamp=datetime(2026, 1, 1, 0, 0, 0),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
        )
    ]


def _make_challenge_context(
    status: str = "active",
    failure_reason: str | None = None,
    max_drawdown: float | None = None,
) -> ActiveChallengeContext:
    attempt = ProprChallengeAttempt(
        attempt_id="attempt-1",
        account_id="account-1",
        status=status,
        failure_reason=failure_reason,
        max_drawdown=max_drawdown,
    )
    return ActiveChallengeContext(attempt=attempt, account_id="account-1")


def _make_order() -> Order:
    return Order(
        order_type=OrderType.BUY_STOP,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
        position_size=10.0,
        signal_source="trend_long",
    )


def _make_strategy_result(order: Order | None = None) -> StrategyRunResult:
    return StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(action=DecisionAction.NO_ACTION, reason="test"),
        order=order,
        updated_trade=None,
    )


def test_returns_skipped_result_when_no_active_challenge_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: None)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.skipped_reason == "no active challenge"
    assert result.synced_state is None
    assert result.strategy_result is None
    assert result.post_cycle_state is None


def test_runs_full_app_cycle_when_active_challenge_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    synced_state = AgentState()
    strategy_result = _make_strategy_result()
    post_cycle_state = AgentState()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert isinstance(result, AppCycleResult)
    assert result.challenge_context is not None
    assert result.synced_state == synced_state
    assert result.strategy_result == strategy_result
    assert result.post_cycle_state == post_cycle_state


def test_submits_new_order_when_no_synced_pending_order_exists_and_post_cycle_state_has_pending_order(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.submit_agent_order_if_allowed", lambda order_service, account_id, symbol, state, order: {"submitted": True})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.submitted_order is True
    assert result.replaced_order is False
    assert result.execution_response is not None


def test_replaces_existing_order_when_synced_pending_order_exists_and_post_cycle_state_has_pending_order(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    synced_state = AgentState(pending_order=order, pending_order_id="external-order-1")
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", lambda order_service, account_id, symbol, state, new_order: {"cancel": {"ok": True}, "submit": {"ok": True}})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.replaced_order is True
    assert result.submitted_order is False
    assert result.execution_response is not None


def test_does_not_execute_when_post_cycle_state_has_no_pending_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(None), AgentState(pending_order=None)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.execution_response is None
    assert result.submitted_order is False
    assert result.replaced_order is False


def test_propagates_value_error_when_replace_is_needed_but_synced_pending_order_id_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState(pending_order=order, pending_order_id=None))
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))

    def _raise(*args, **kwargs):
        raise ValueError("Missing external pending order id for replacement")

    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", _raise)

    with pytest.raises(ValueError, match="Missing external pending order id for replacement"):
        run_app_cycle(
            client=FakeClient(),
            order_service=FakeOrderService(),
            symbol="EURUSD",
            candles=_make_candles(),
            config=StrategyConfig(),
            account_balance=10000.0,
        )


def test_blocks_execution_when_risk_guard_says_no_active_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: None)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.skipped_reason == "no active challenge"
    assert result.submitted_order is False
    assert result.replaced_order is False


def test_blocks_execution_when_challenge_has_failure_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context(failure_reason="breach"))
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.execution_response is None
    assert result.skipped_reason == "challenge has failure reason"


def test_blocks_execution_when_drawdown_threshold_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context(max_drawdown=100.0))
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        max_allowed_drawdown=100.0,
    )

    assert result.execution_response is None
    assert result.skipped_reason == "max drawdown threshold reached"


def test_still_allows_execution_when_guards_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context(max_drawdown=50.0))
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.submit_agent_order_if_allowed", lambda order_service, account_id, symbol, state, order: {"submitted": True})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        max_allowed_drawdown=100.0,
    )

    assert result.submitted_order is True or result.replaced_order is True


def test_app_cycle_exposes_risk_guard_result_in_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(None), AgentState(pending_order=None)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        max_allowed_drawdown=100.0,
    )

    assert result.risk_guard_result is not None


def test_app_cycle_replaces_using_synced_external_pending_order_id(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    synced_state = AgentState(pending_order=order, pending_order_id="external-order-42")
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))

    def _fake_replace(order_service, account_id, symbol, state, new_order):
        captured["pending_order_id"] = state.pending_order_id
        return {"cancel": {"id": state.pending_order_id}, "submit": {"data": [{"orderId": "urn:prp-order:456"}]}}

    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", _fake_replace)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert captured["pending_order_id"] == "external-order-42"
    assert result.replaced_order is True


def test_app_cycle_stores_new_pending_order_id_from_submit_response_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.submit_agent_order_if_allowed", lambda order_service, account_id, symbol, state, order: {"data": [{"orderId": "urn:prp-order:123"}]})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order_id == "urn:prp-order:123"


def test_app_cycle_stores_new_pending_order_id_from_replace_submit_response_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    synced_state = AgentState(pending_order=order, pending_order_id="external-order-42")
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", lambda order_service, account_id, symbol, state, new_order: {"cancel": {"id": "external-order-42"}, "submit": {"data": [{"orderId": "urn:prp-order:456"}]}})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
    )

    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order_id == "urn:prp-order:456"


def test_app_cycle_blocks_early_when_core_service_is_not_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.trading_app.fetch_and_check_core_service_health",
        lambda client: HealthGuardResult(allow_trading=False, reason="core service not healthy", core_status="ERROR"),
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
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
    strategy_result = _make_strategy_result()
    post_cycle_state = AgentState()

    def _healthy(client):
        health_calls["count"] += 1
        return HealthGuardResult(allow_trading=True, core_status="OK")

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", _healthy)
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
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
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: None)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EURUSD",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        require_healthy_core=False,
    )

    assert result.skipped_reason == "no active challenge"
    assert result.health_guard_result is None

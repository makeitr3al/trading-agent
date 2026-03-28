from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.trading_app import AppCycleResult, run_app_cycle
from broker.asset_guard import AssetGuardResult
from broker.health_guard import HealthGuardResult
from broker.propr_client import ProprClient
from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.propr_challenge import ActiveChallengeContext, ProprChallengeAttempt
from models.runner_result import StrategyRunResult
from models.trade import Trade, TradeDirection, TradeType


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



def _make_trade() -> Trade:
    return Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        quantity=0.5,
        position_id="position-1",
    )


def _make_strategy_result(order: Order | None = None, close_active_trade: bool = False) -> StrategyRunResult:
    return StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(action=DecisionAction.NO_ACTION, reason="test"),
        order=order,
        updated_trade=None,
        close_active_trade=close_active_trade,
    )
def _make_symbol_spec():
    from models.symbol_spec import SymbolSpec

    return SymbolSpec(
        symbol="BTC/USDC",
        asset="BTC",
        base="BTC",
        quote="USDC",
        quantity_decimals=3,
        price_decimals=None,
        max_leverage=5,
        source_name="test",
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
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))
    monkeypatch.setattr("app.trading_app.submit_agent_order_if_allowed", lambda order_service, account_id, symbol, state, order: {"submitted": True})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
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
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))
    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", lambda order_service, account_id, symbol, state, new_order: {"cancel": {"ok": True}, "submit": {"ok": True}})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
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
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))

    def _raise(*args, **kwargs):
        raise ValueError("Missing external pending order id for replacement")

    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", _raise)

    with pytest.raises(ValueError, match="Missing external pending order id for replacement"):
        run_app_cycle(
            client=FakeClient(),
            order_service=FakeOrderService(),
            symbol="EUR/USD",
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
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=5))
    monkeypatch.setattr("app.trading_app.submit_agent_order_if_allowed", lambda order_service, account_id, symbol, state, order: {"submitted": True})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=_make_candles(),
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
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))

    def _fake_replace(order_service, account_id, symbol, state, new_order):
        captured["pending_order_id"] = state.pending_order_id
        return {"cancel": {"id": state.pending_order_id}, "submit": {"data": [{"orderId": "urn:prp-order:456"}]}}

    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", _fake_replace)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
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
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))
    monkeypatch.setattr("app.trading_app.submit_agent_order_if_allowed", lambda order_service, account_id, symbol, state, order: {"data": [{"orderId": "urn:prp-order:123"}]})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
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
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="EUR", desired_leverage=desired_leverage, max_leverage=2))
    monkeypatch.setattr("app.trading_app.safe_replace_pending_order", lambda order_service, account_id, symbol, state, new_order: {"cancel": {"id": "external-order-42"}, "submit": {"data": [{"orderId": "urn:prp-order:456"}]}})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
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



def test_blocks_execution_when_asset_is_not_tradeable(monkeypatch: pytest.MonkeyPatch) -> None:

    order = _make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=False, reason="asset not tradeable", asset="EUR", desired_leverage=desired_leverage, max_leverage=None))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="EUR/USD",
        candles=_make_candles(),
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

    order = _make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=False, reason="configured leverage exceeds max allowed", asset="BTC", desired_leverage=desired_leverage, max_leverage=5))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        desired_leverage=6,
    )

    assert result.execution_response is None
    assert result.skipped_reason == "configured leverage exceeds max allowed"
    assert result.asset_guard_result is not None
    assert result.asset_guard_result.max_leverage == 5



def test_app_cycle_exposes_asset_guard_result_when_execution_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:

    order = _make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="BTC", desired_leverage=desired_leverage, max_leverage=5))
    monkeypatch.setattr("app.trading_app.submit_agent_order_if_allowed", lambda order_service, account_id, symbol, state, order: {"submitted": True})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
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
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
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
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))

    live_client = ProprClient.__new__(ProprClient)

    result = run_app_cycle(
        client=live_client,
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
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
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=False,
        symbol_spec=None,
        data_source="live",
    )

    assert result.skipped_reason is None
    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order is not None
    assert result.symbol_spec_loaded is False



def test_golden_mode_remains_blocked_from_submit_regardless(monkeypatch: pytest.MonkeyPatch) -> None:
    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
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

    order = _make_order()
    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (_make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="BTC", desired_leverage=desired_leverage, max_leverage=5))
    monkeypatch.setattr("app.trading_app.submit_agent_order_if_allowed", lambda order_service, account_id, symbol, state, order: {"submitted": True})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
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







def test_closes_active_trade_when_strategy_requests_market_close(monkeypatch: pytest.MonkeyPatch) -> None:
    synced_state = AgentState(active_trade=_make_trade())
    strategy_result = _make_strategy_result(close_active_trade=True)
    post_cycle_state = AgentState(active_trade=None)

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))
    monkeypatch.setattr("app.trading_app.submit_active_trade_close_if_allowed", lambda order_service, account_id, symbol, state, close_active_trade: {"data": [{"orderId": "urn:prp-order:close-1"}]})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="live",
    )

    assert result.closed_trade is True
    assert result.execution_response is not None
    assert result.submitted_order is False
    assert result.replaced_order is False



def test_golden_mode_blocks_active_trade_close_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    synced_state = AgentState(active_trade=_make_trade())
    strategy_result = _make_strategy_result(close_active_trade=True)
    post_cycle_state = AgentState(active_trade=None)

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="golden",
    )

    assert result.closed_trade is False
    assert result.execution_response is None
    assert result.skipped_reason == "submit is not allowed with golden data source"


def test_manages_exit_orders_for_active_trade_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    synced_state = AgentState(
        active_trade=_make_trade(),
        stop_loss_order_id="old-stop",
        take_profit_order_id="old-tp",
    )
    updated_trade = _make_trade().copy(update={"stop_loss": 96.0, "take_profit": 111.0})
    strategy_result = StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(action=DecisionAction.KEEP_EXISTING_TREND_TRADE, reason="update exits"),
        order=None,
        updated_trade=updated_trade,
        close_active_trade=False,
    )
    post_cycle_state = AgentState(active_trade=updated_trade)

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))
    monkeypatch.setattr(
        "app.trading_app.manage_active_trade_exit_orders",
        lambda order_service, account_id, symbol, state, updated_trade, buy_spread=0.0: {
            "stop_loss": {"order_id": "new-stop"},
            "take_profit": {"order_id": "new-tp"},
        },
    )

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="live",
    )

    assert result.managed_exit_orders is True
    assert result.execution_response is not None
    assert result.post_cycle_state is not None
    assert result.post_cycle_state.stop_loss_order_id == "new-stop"
    assert result.post_cycle_state.take_profit_order_id == "new-tp"


def test_golden_mode_blocks_active_trade_exit_order_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    synced_state = AgentState(active_trade=_make_trade())
    updated_trade = _make_trade().copy(update={"stop_loss": 96.0})
    strategy_result = StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(action=DecisionAction.KEEP_EXISTING_TREND_TRADE, reason="update exits"),
        order=None,
        updated_trade=updated_trade,
        close_active_trade=False,
    )
    post_cycle_state = AgentState(active_trade=updated_trade)

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client: _make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
        data_source="golden",
    )

    assert result.managed_exit_orders is False
    assert result.execution_response is None
    assert result.skipped_reason == "submit is not allowed with golden data source"





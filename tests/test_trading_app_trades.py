"""Active trade close, exit-order management, and golden-mode blocks for those paths."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import pytest

from app.trading_app import run_app_cycle
from broker.health_guard import HealthGuardResult
from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.decision import DecisionAction, DecisionResult
from models.runner_result import StrategyRunResult
from tests.fixtures.trading_app_fixtures import (
    FakeClient,
    FakeOrderService,
    make_candles,
    make_challenge_context,
    make_strategy_result,
    make_trade,
)


def test_closes_active_trade_when_strategy_requests_market_close(monkeypatch: pytest.MonkeyPatch) -> None:
    synced_state = AgentState(active_trade=make_trade())
    strategy_result = make_strategy_result(close_active_trade=True)
    post_cycle_state = AgentState(active_trade=None)

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))
    monkeypatch.setattr("app.trading_app.submit_active_trade_close_if_allowed", lambda order_service, account_id, symbol, state, close_active_trade: {"data": [{"orderId": "urn:prp-order:close-1"}]})

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
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
    synced_state = AgentState(active_trade=make_trade())
    strategy_result = make_strategy_result(close_active_trade=True)
    post_cycle_state = AgentState(active_trade=None)

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))

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

    assert result.closed_trade is False
    assert result.execution_response is None
    assert result.skipped_reason == "submit is not allowed with golden data source"


def test_manages_exit_orders_for_active_trade_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    synced_state = AgentState(
        active_trade=make_trade(),
        stop_loss_order_id="old-stop",
        take_profit_order_id="old-tp",
    )
    updated_trade = make_trade().model_copy(update={"stop_loss": 96.0, "take_profit": 111.0})
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
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
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
        candles=make_candles(),
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
    synced_state = AgentState(active_trade=make_trade())
    updated_trade = make_trade().model_copy(update={"stop_loss": 96.0})
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
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (strategy_result, post_cycle_state))

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

    assert result.managed_exit_orders is False
    assert result.execution_response is None
    assert result.skipped_reason == "submit is not allowed with golden data source"

"""Account slot limits, beta standalone-stop policy, and sizing vs leverage."""

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
    make_trade,
)


def test_blocks_new_entry_when_three_open_order_trade_slots_already_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()
    synced_state = AgentState(
        active_trade=make_trade(),
        account_open_entry_orders_count=1,
        account_open_positions_count=2,
    )

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: synced_state)
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

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

    assert result.execution_response is None
    assert result.submitted_order is False
    assert result.replaced_order is False
    assert result.skipped_reason == "max open orders/trades reached (3/3)"


def test_beta_blocks_standalone_stop_entry_execution_but_keeps_journalable_state(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))

    result = run_app_cycle(
        client=FakeClient(environment="beta"),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
    )

    assert result.submitted_order is False
    assert result.replaced_order is False
    assert result.skipped_reason == "beta does not support standalone stop entries"
    assert result.post_cycle_state is not None
    assert result.post_cycle_state.pending_order is not None


def test_prod_does_not_block_standalone_stop_entry_before_asset_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    order = make_order()

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="BTC", desired_leverage=desired_leverage, max_leverage=5))
    monkeypatch.setattr(
        "app.trading_app.submit_agent_order_if_allowed",
        lambda order_service, account_id, symbol, state, order: SubmitAgentOrderResult({"submitted": True}, None),
    )

    result = run_app_cycle(
        client=FakeClient(environment="prod"),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=True,
    )

    assert result.skipped_reason is None
    assert result.submitted_order is True


def test_app_cycle_blocks_pending_order_when_risk_based_size_exceeds_desired_leverage(monkeypatch: pytest.MonkeyPatch) -> None:
    from models.symbol_spec import SymbolSpec

    order = Order(
        order_type=OrderType.BUY_LIMIT,
        entry=1000.0,
        stop_loss=999.0,
        take_profit=1200.0,
        position_size=999.0,
        signal_source="manual_test",
    )

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(order), AgentState(pending_order=order)))
    monkeypatch.setattr("app.trading_app.evaluate_asset_execution_guard", lambda client, account_id, symbol, desired_leverage: AssetGuardResult(allow_execution=True, asset="BTC", desired_leverage=desired_leverage, max_leverage=5))

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=make_candles(),
        config=StrategyConfig(risk_per_trade_pct=0.01),
        account_balance=100.0,
        allow_execution=True,
        desired_leverage=1,
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

    assert result.submitted_order is False
    assert result.replaced_order is False
    assert result.execution_response is None
    assert result.skipped_reason == "risk based position size exceeds desired leverage"

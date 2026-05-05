from __future__ import annotations

from datetime import datetime

import pytest

from app.trading_app import run_app_cycle
from broker.health_guard import HealthGuardResult
from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from tests.fixtures.trading_app_fixtures import (
    FakeClient,
    FakeOrderService,
    make_challenge_context,
    make_strategy_result,
)


def _candles(ts: datetime) -> list[Candle]:
    return [
        Candle(
            timestamp=ts,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
        )
    ]


def test_journal_bar_dedupe_skips_second_poll_same_bar(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("JOURNAL_BAR_DEDUPE", "YES")
    journal_path = tmp_path / "journal.jsonl"

    monkeypatch.setattr("app.trading_app.fetch_and_check_core_service_health", lambda client: HealthGuardResult(allow_trading=True, core_status="OK"))
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: make_challenge_context())
    monkeypatch.setattr("app.trading_app.sync_agent_state_from_propr", lambda client, account_id, previous_state: AgentState())
    monkeypatch.setattr("app.trading_app.run_agent_cycle", lambda candles, config, account_balance, state: (make_strategy_result(None), AgentState(pending_order=None)))

    first = run_app_cycle(
        client=FakeClient(environment="beta"),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_candles(datetime(2026, 1, 1, 0, 0, 0)),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=False,
        data_source="live",
        journal_path=journal_path,
        previous_state=AgentState(last_journaled_signal_bar_ts=None),
    )
    assert first.journal_entries
    assert first.post_cycle_state is not None
    assert first.post_cycle_state.last_journaled_signal_bar_ts is not None

    # Same bar again: dedupe should skip journaling.
    second = run_app_cycle(
        client=FakeClient(environment="beta"),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        # Same bar timestamp (provider updates OHLC intrabar; timestamp stays at bar open).
        candles=_candles(datetime(2026, 1, 1, 0, 0, 0)),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=False,
        data_source="live",
        journal_path=journal_path,
        previous_state=first.post_cycle_state,
    )
    assert second.journal_entries == []


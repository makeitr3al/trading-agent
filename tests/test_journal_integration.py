from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from app.journal import append_journal_entries, build_journal_entries
from app.trading_app import run_app_cycle
from broker.health_guard import HealthGuardResult
from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from models.decision import DecisionAction, DecisionResult
from models.journal import JournalEntry
from models.order import Order, OrderType
from models.propr_challenge import ActiveChallengeContext, ProprChallengeAttempt
from models.runner_result import StrategyRunResult
from models.signal import SignalState, SignalType
from models.trade import Trade, TradeDirection, TradeType


class FakeConfig:
    environment = "beta"


class FakeClient:
    def __init__(self) -> None:
        self.config = FakeConfig()


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


def _make_challenge_context() -> ActiveChallengeContext:
    attempt = ProprChallengeAttempt(
        attempt_id="attempt-1",
        account_id="account-1",
        status="active",
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


def _make_trade(*, entry: float = 100.0, quantity: float = 0.5, opened_at: str | None = None) -> Trade:
    return Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=entry,
        stop_loss=95.0,
        take_profit=110.0,
        quantity=quantity,
        position_id="position-1",
        opened_at=opened_at,
    )


def _patch_common(monkeypatch: pytest.MonkeyPatch, synced_state: AgentState, strategy_result: StrategyRunResult, post_cycle_state: AgentState) -> None:
    monkeypatch.setattr(
        "app.trading_app.fetch_and_check_core_service_health",
        lambda client: HealthGuardResult(allow_trading=True, core_status="OK"),
    )
    monkeypatch.setattr("app.trading_app.get_active_challenge_context", lambda client, challenge_id=None: _make_challenge_context())
    monkeypatch.setattr(
        "app.trading_app.sync_agent_state_from_propr",
        lambda client, account_id, previous_state: synced_state,
    )
    monkeypatch.setattr(
        "app.trading_app.run_agent_cycle",
        lambda candles, config, account_balance, state: (strategy_result, post_cycle_state),
    )


def test_run_app_cycle_persists_cycle_and_order_journal_entries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    order = _make_order()
    strategy_result = StrategyRunResult(
        trend_signal=SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=True,
            reason="trend signal detected",
            entry=110.0,
            stop_loss=100.0,
            take_profit=130.0,
        ),
        countertrend_signal=SignalState(
            signal_type=SignalType.COUNTERTREND_SHORT,
            is_valid=True,
            reason="countertrend signal detected",
            entry=105.0,
            stop_loss=115.0,
            take_profit=95.0,
        ),
        decision=DecisionResult(
            action=DecisionAction.PREPARE_TREND_ORDER,
            reason="valid trend signal",
            selected_signal_type=SignalType.TREND_LONG.value,
        ),
        order=order,
        updated_trade=None,
    )
    post_cycle_state = AgentState(pending_order=order)
    _patch_common(monkeypatch, AgentState(), strategy_result, post_cycle_state)

    journal_path = tmp_path / "journal.jsonl"
    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=False,
        journal_path=journal_path,
    )

    assert len(result.journal_entries) == 2
    cycle_entry = result.journal_entries[0]
    order_entry = result.journal_entries[1]

    assert cycle_entry.entry_type == "cycle"
    assert cycle_entry.environment == "beta"
    assert cycle_entry.entry_date == "2026-01-01"
    assert [signal.signal_type for signal in cycle_entry.received_signals] == ["TREND_LONG", "COUNTERTREND_SHORT"]
    assert cycle_entry.used_signals == ["TREND_LONG"]
    assert len(cycle_entry.unused_signals) == 1
    assert cycle_entry.unused_signals[0].signal_type == "COUNTERTREND_SHORT"
    assert cycle_entry.unused_signals[0].reason == "not selected by decision: valid trend signal"

    assert order_entry.entry_type == "order"
    assert order_entry.environment == "beta"
    assert order_entry.direction == "LONG"
    assert order_entry.position_size == 10.0
    assert order_entry.status == "prepared"

    persisted = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert len(persisted) == 2
    assert persisted[0]["environment"] == "beta"
    assert persisted[0]["used_signals"] == ["TREND_LONG"]
    assert persisted[1]["position_size"] == 10.0
    assert result.journal_path == str(journal_path)


def test_run_app_cycle_adds_filled_trade_journal_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    filled_trade = _make_trade(quantity=0.75, opened_at="2026-01-01T00:00:00")
    strategy_result = StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason="pending order filled",
            selected_signal_type=SignalType.TREND_LONG.value,
        ),
        order=None,
        updated_trade=filled_trade,
        filled_trade=filled_trade,
    )
    post_cycle_state = AgentState(active_trade=filled_trade)
    _patch_common(monkeypatch, AgentState(), strategy_result, post_cycle_state)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=False,
    )

    assert len(result.journal_entries) == 2
    trade_entry = result.journal_entries[1]
    assert trade_entry.entry_type == "trade"
    assert trade_entry.environment == "beta"
    assert trade_entry.environment == "beta"
    assert trade_entry.status == "filled"
    assert trade_entry.fill_timestamp == "2026-01-01T00:00:00"
    assert trade_entry.position_size == 0.75
    assert trade_entry.pnl is None


def test_run_app_cycle_adds_closed_trade_journal_entry_with_pnl(monkeypatch: pytest.MonkeyPatch) -> None:
    active_trade = _make_trade(quantity=2.0, opened_at="2025-12-31T12:00:00")
    strategy_result = StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(
            action=DecisionAction.CLOSE_TREND_TRADE,
            reason="outer band exit trigger closes active trend trade",
        ),
        order=None,
        updated_trade=None,
        close_active_trade=True,
    )
    _patch_common(monkeypatch, AgentState(active_trade=active_trade), strategy_result, AgentState(active_trade=None))
    monkeypatch.setattr(
        "app.trading_app.submit_active_trade_close_if_allowed",
        lambda order_service, account_id, symbol, state, close_active_trade: {"data": [{"orderId": "close-1"}]},
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

    assert result.closed_trade is True
    assert len(result.journal_entries) == 2
    trade_entry = result.journal_entries[1]
    assert trade_entry.entry_type == "trade"
    assert trade_entry.status == "closed"
    assert trade_entry.fill_timestamp == "2025-12-31T12:00:00"
    assert trade_entry.close_timestamp == "2026-01-01T00:00:00"
    assert trade_entry.position_size == 2.0
    assert trade_entry.pnl == 1.0


def test_append_journal_entries_appends_to_existing_file(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    first_entry = JournalEntry(
        entry_type="cycle",
        entry_date="2026-01-01",
        entry_timestamp="2026-01-01T00:00:00",
        symbol="BTC/USDC",
        environment="beta",
    )
    second_entry = JournalEntry(
        entry_type="trade",
        entry_date="2026-01-02",
        entry_timestamp="2026-01-02T00:00:00",
        symbol="BTC/USDC",
        environment="beta",
        status="filled",
    )

    append_journal_entries(journal_path, [first_entry])
    append_journal_entries(journal_path, [second_entry])

    persisted = [json.loads(line) for line in journal_path.read_text(encoding="utf-8").splitlines()]
    assert len(persisted) == 2
    assert persisted[0]["entry_type"] == "cycle"
    assert persisted[1]["entry_type"] == "trade"


def test_build_journal_entries_order_status_resting_when_broker_has_pending_id() -> None:
    order = _make_order()
    strategy_result = StrategyRunResult(
        trend_signal=SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=True,
            reason="trend signal detected",
            entry=110.0,
            stop_loss=100.0,
            take_profit=130.0,
        ),
        countertrend_signal=None,
        decision=DecisionResult(
            action=DecisionAction.PREPARE_TREND_ORDER,
            reason="valid trend signal",
            selected_signal_type=SignalType.TREND_LONG.value,
        ),
        order=order,
        updated_trade=None,
    )
    post_cycle_state = AgentState(pending_order=order)
    synced_state = AgentState(pending_order_id="broker-pending-99")
    entries = build_journal_entries(
        symbol="BTC/USDC",
        environment="beta",
        cycle_timestamp="2026-01-01T00:00:00+00:00",
        strategy_result=strategy_result,
        synced_state=synced_state,
        post_cycle_state=post_cycle_state,
        previous_state=None,
        submitted_order=False,
        replaced_order=False,
        closed_trade=False,
        skipped_reason=None,
        exit_price=100.5,
        executed_at="2026-01-01T00:00:01+00:00",
    )
    assert entries[1].entry_type == "order"
    assert entries[1].status == "resting"
    assert entries[1].broker_pending_order_id == "broker-pending-99"
    assert entries[1].external_order_id == "broker-pending-99"
    assert entries[1].order_lifecycle_id == "broker-pending-99"


def test_build_journal_entries_broker_sync_fill_trade_without_simulated_filled_trade() -> None:
    pending = _make_order()
    previous_state = AgentState(pending_order=pending, pending_order_id="pending-legacy")
    active = _make_trade(
        entry=108.0,
        quantity=0.42,
        opened_at="2026-01-01T12:00:00+00:00",
    ).model_copy(update={"position_id": "pos-sync-1"})
    synced_state = AgentState(active_trade=active, pending_order=None, pending_order_id=None)
    strategy_result = StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason="holding",
            selected_signal_type=SignalType.TREND_LONG.value,
        ),
        order=None,
        updated_trade=None,
        filled_trade=None,
    )
    post_cycle_state = AgentState(active_trade=active)
    entries = build_journal_entries(
        symbol="BTC/USDC",
        environment="beta",
        cycle_timestamp="2026-01-01T12:05:00+00:00",
        strategy_result=strategy_result,
        synced_state=synced_state,
        post_cycle_state=post_cycle_state,
        previous_state=previous_state,
        submitted_order=False,
        replaced_order=False,
        closed_trade=False,
        skipped_reason=None,
        exit_price=109.0,
    )
    assert len(entries) == 2
    assert entries[0].entry_type == "cycle"
    trade_entry = entries[1]
    assert trade_entry.entry_type == "trade"
    assert trade_entry.status == "filled"
    assert trade_entry.position_size == 0.42
    assert trade_entry.external_order_id == "pos-sync-1"
    assert trade_entry.notes == "broker sync: pending entry cleared, active position opened"


def test_run_app_cycle_order_journal_resting_when_synced_has_pending_order_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order = _make_order()
    strategy_result = StrategyRunResult(
        trend_signal=SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=True,
            reason="trend signal detected",
            entry=110.0,
            stop_loss=100.0,
            take_profit=130.0,
        ),
        countertrend_signal=None,
        decision=DecisionResult(
            action=DecisionAction.PREPARE_TREND_ORDER,
            reason="valid trend signal",
            selected_signal_type=SignalType.TREND_LONG.value,
        ),
        order=order,
        updated_trade=None,
    )
    post_cycle_state = AgentState(pending_order=order)
    synced = AgentState(pending_order_id="resting-on-book")
    _patch_common(monkeypatch, synced, strategy_result, post_cycle_state)

    result = run_app_cycle(
        client=FakeClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=False,
        journal_path=None,
    )
    order_entry = result.journal_entries[1]
    assert order_entry.status == "resting"
    assert order_entry.broker_pending_order_id == "resting-on-book"


def test_run_app_cycle_uses_unknown_environment_when_client_has_no_config(monkeypatch: pytest.MonkeyPatch) -> None:
    strategy_result = StrategyRunResult(
        trend_signal=None,
        countertrend_signal=None,
        decision=DecisionResult(
            action=DecisionAction.NO_ACTION,
            reason="no valid signal",
        ),
        order=None,
        updated_trade=None,
    )
    _patch_common(monkeypatch, AgentState(), strategy_result, AgentState())

    class ConfiglessClient:
        pass

    result = run_app_cycle(
        client=ConfiglessClient(),
        order_service=FakeOrderService(),
        symbol="BTC/USDC",
        candles=_make_candles(),
        config=StrategyConfig(),
        account_balance=10000.0,
        allow_execution=False,
    )

    assert len(result.journal_entries) == 1
    assert result.journal_entries[0].environment is None

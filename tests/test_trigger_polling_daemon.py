from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from models.agent_state import AgentState
from models.order import Order, OrderType
from scripts.scan_core import ArmedMarketEntry
from scripts.trigger_polling_daemon import (
    ArmedMarketsSnapshot,
    _append_order_protocol_entry,
    _emit_arm_disarm_protocol_entries,
    _next_daily_scan_dt,
    poll_armed_markets,
    should_run_daily_scan,
)


def test_should_run_daily_scan() -> None:
    now = datetime(2026, 5, 5, 7, 0, tzinfo=timezone.utc)
    assert should_run_daily_scan(now, "07:00", last_scan_date=None) is True
    assert should_run_daily_scan(now, "07:00", last_scan_date=now.date()) is False


def test_next_daily_scan_dt_uses_tomorrow_after_scan_or_past_time() -> None:
    now = datetime(2026, 5, 5, 8, 0, tzinfo=timezone.utc)
    # If it's already past 07:00 today, next scan is tomorrow 07:00.
    assert _next_daily_scan_dt(now, "07:00", last_scan_date=None) == datetime(2026, 5, 6, 7, 0, tzinfo=timezone.utc)
    # If we already scanned today, next scan is tomorrow even if before 07:00.
    now2 = datetime(2026, 5, 5, 6, 0, tzinfo=timezone.utc)
    assert _next_daily_scan_dt(now2, "07:00", last_scan_date=now2.date()) == datetime(
        2026, 5, 6, 7, 0, tzinfo=timezone.utc
    )


def test_poll_armed_markets_removes_after_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    # Monkeypatch environment loader / clients to avoid real network calls.
    import scripts.trigger_polling_daemon as m

    monkeypatch.setattr(m, "load_propr_config_from_env", lambda: SimpleNamespace(environment="beta"))
    monkeypatch.setattr(m, "load_data_source_settings_from_env", lambda: SimpleNamespace(data_source="live"))
    monkeypatch.setattr(
        m,
        "load_multi_market_scan_settings_from_env",
        lambda: SimpleNamespace(
            assets=["BTC"],
            allow_submit=True,
            require_healthy_core=True,
            leverage=1,
            journal_path="",
            challenge_id=None,
            challenge_attempt_id=None,
        ),
    )
    monkeypatch.setattr(m, "ProprClient", lambda *_a, **_k: object())
    monkeypatch.setattr(m, "ProprOrderService", lambda *_a, **_k: object())

    class _FakeSymbolService:
        def get_symbol_spec(self, _symbol: str):
            return None

    monkeypatch.setattr(m, "HyperliquidSymbolService", lambda: _FakeSymbolService())
    monkeypatch.setattr(m, "AssetRegistry", lambda: object())

    monkeypatch.setattr(
        m,
        "build_data_batch_and_config",
        lambda **_k: (SimpleNamespace(candles=[], account_balance=10000.0), SimpleNamespace(), 0.0),
    )

    # run_app_cycle returns submitted_order=True and pending_order_id set -> should remove from armed.
    def _fake_run_app_cycle(**_kwargs: object):
        state = AgentState(
            pending_order=Order(
                order_type=OrderType.BUY_STOP,
                entry=100.0,
                stop_loss=90.0,
                take_profit=120.0,
                signal_source="trend_signal",
            ),
            pending_order_id="abc",
        )
        return SimpleNamespace(submitted_order=True, post_cycle_state=state)

    monkeypatch.setattr(m, "run_app_cycle", _fake_run_app_cycle)
    monkeypatch.setattr(m, "load_agent_state", lambda *_a, **_k: AgentState())
    monkeypatch.setattr(m, "save_agent_state", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "save_armed_markets", lambda **_k: None)

    snapshot = ArmedMarketsSnapshot(
        scan_ts="2026-05-05T00:00:00+00:00",
        ttl_hours=24,
        markets=[
            ArmedMarketEntry(
                symbol="BTC",
                coin="BTC",
                order_type="OrderType.BUY_STOP",
                entry=100.0,
                stop_loss=90.0,
                take_profit=120.0,
                signal_source="trend_signal",
                selected_signal_type="trend",
                scan_ts="2026-05-05T00:00:00+00:00",
            )
        ],
    )

    out = poll_armed_markets(snapshot, now_utc=datetime(2026, 5, 5, 8, 0, tzinfo=timezone.utc))
    assert out.markets == []


def test_poll_armed_markets_keeps_armed_when_state_temporarily_drops_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    # Monkeypatch environment loader / clients to avoid real network calls.
    import scripts.trigger_polling_daemon as m

    monkeypatch.setattr(m, "load_propr_config_from_env", lambda: SimpleNamespace(environment="beta"))
    monkeypatch.setattr(m, "load_data_source_settings_from_env", lambda: SimpleNamespace(data_source="live"))
    monkeypatch.setattr(
        m,
        "load_multi_market_scan_settings_from_env",
        lambda: SimpleNamespace(
            assets=["NEAR"],
            allow_submit=True,
            require_healthy_core=True,
            leverage=1,
            journal_path="",
            challenge_id=None,
            challenge_attempt_id=None,
        ),
    )
    monkeypatch.setattr(m, "ProprClient", lambda *_a, **_k: object())
    monkeypatch.setattr(m, "ProprOrderService", lambda *_a, **_k: object())

    class _FakeSymbolService:
        def get_symbol_spec(self, _symbol: str):
            return None

    monkeypatch.setattr(m, "HyperliquidSymbolService", lambda: _FakeSymbolService())
    monkeypatch.setattr(m, "AssetRegistry", lambda: object())

    monkeypatch.setattr(
        m,
        "build_data_batch_and_config",
        lambda **_k: (SimpleNamespace(candles=[], account_balance=10000.0), SimpleNamespace(), 0.0),
    )

    # previous_state has stop-pending; run_app_cycle returns a state that drops pending_order (submitted=false).
    prev_state = AgentState(
        pending_order=Order(
            order_type=OrderType.BUY_STOP,
            entry=10.0,
            stop_loss=9.0,
            take_profit=12.0,
            signal_source="trend_signal",
        )
    )

    def _fake_run_app_cycle(**_kwargs: object):
        return SimpleNamespace(submitted_order=False, post_cycle_state=AgentState())

    saved: dict[str, AgentState] = {}

    monkeypatch.setattr(m, "run_app_cycle", _fake_run_app_cycle)
    monkeypatch.setattr(m, "load_agent_state", lambda *_a, **_k: prev_state)
    monkeypatch.setattr(m, "save_agent_state", lambda symbol, state, **_k: saved.__setitem__(symbol, state))
    monkeypatch.setattr(m, "save_armed_markets", lambda **_k: None)

    snapshot = ArmedMarketsSnapshot(
        scan_ts="2026-05-05T00:00:00+00:00",
        ttl_hours=24,
        markets=[
            ArmedMarketEntry(
                symbol="NEAR",
                coin="NEAR",
                order_type="OrderType.BUY_STOP",
                entry=10.0,
                stop_loss=9.0,
                take_profit=12.0,
                signal_source="trend_signal",
                selected_signal_type="trend",
                scan_ts="2026-05-05T00:00:00+00:00",
            )
        ],
    )

    out = poll_armed_markets(snapshot, now_utc=datetime(2026, 5, 5, 8, 0, tzinfo=timezone.utc))
    assert [m.symbol for m in out.markets] == ["NEAR"]
    assert saved["NEAR"].pending_order is not None
    assert saved["NEAR"].pending_order.order_type == OrderType.BUY_STOP


def test_append_order_protocol_entry_writes_order_row(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.trigger_polling_daemon as m

    captured = {}

    def _fake_append(_path: str, entries: list[object]) -> None:
        captured["path"] = _path
        captured["entries"] = entries

    monkeypatch.setattr(m, "append_journal_entries", _fake_append)

    order = Order(
        order_type=OrderType.BUY_STOP,
        entry=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        signal_source="trend_signal",
    )

    _append_order_protocol_entry(
        journal_path="journal.jsonl",
        symbol="BTC",
        environment="beta",
        status="armed",
        executed_at="2026-05-06T00:00:00+00:00",
        signal_lifecycle_id="sid_1",
        order=order,
        notes="armed",
        source_signal_type="TREND_LONG",
        external_order_id=None,
    )

    assert captured["path"] == "journal.jsonl"
    entries = captured["entries"]
    assert len(entries) == 1
    e = entries[0]
    assert getattr(e, "entry_type") == "order"
    assert getattr(e, "status") == "armed"
    assert getattr(e, "signal_lifecycle_id") == "sid_1"


def test_emit_disarm_protocol_entries_emits_for_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.trigger_polling_daemon as m

    emitted: list[tuple[str, str]] = []

    def _fake_append(_path: str, entries: list[object]) -> None:
        for e in entries:
            emitted.append((getattr(e, "symbol"), getattr(e, "status")))

    monkeypatch.setattr(m, "append_journal_entries", _fake_append)
    monkeypatch.setattr(
        m,
        "load_agent_state",
        lambda symbol: AgentState(
            signal_lifecycle_id="sid_x",
            pending_order=Order(
                order_type=OrderType.SELL_STOP,
                entry=10.0,
                stop_loss=11.0,
                take_profit=8.0,
                signal_source="trend_signal",
            ),
        )
        if symbol == "NEAR"
        else None,
    )

    _emit_arm_disarm_protocol_entries(
        journal_path="journal.jsonl",
        environment="beta",
        executed_at="2026-05-06T00:00:00+00:00",
        prev_armed_symbols={"NEAR"},
        new_armed_symbols=set(),
    )

    assert ("NEAR", "disarmed") in emitted


from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from models.agent_state import AgentState
from models.order import Order, OrderType
from scripts.scan_core import ArmedMarketEntry
from scripts.trigger_polling_daemon import (
    ArmedMarketsSnapshot,
    poll_armed_markets,
    should_run_daily_scan,
)


def test_should_run_daily_scan() -> None:
    now = datetime(2026, 5, 5, 7, 0, tzinfo=timezone.utc)
    assert should_run_daily_scan(now, "07:00", last_scan_date=None) is True
    assert should_run_daily_scan(now, "07:00", last_scan_date=now.date()) is False


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


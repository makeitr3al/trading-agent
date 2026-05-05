from __future__ import annotations

import os

from models.agent_state import AgentState
from models.order import Order, OrderType
from scripts.scan_core import ArmedMarketEntry
from scripts.trigger_polling_store import (
    agent_state_path,
    armed_markets_path,
    load_agent_state,
    load_armed_markets,
    parse_armed_markets,
    sanitize_symbol_for_filename,
    save_agent_state,
    save_armed_markets,
)


def test_sanitize_symbol_for_filename() -> None:
    assert sanitize_symbol_for_filename("BTC/USDC") == "BTC_USDC"
    assert sanitize_symbol_for_filename("xyz:AAPL") == "xyz_AAPL"


def test_armed_markets_roundtrip(tmp_path) -> None:
    os.environ["TRADING_AGENT_DATA_PATH"] = str(tmp_path)
    scan_ts = "2026-05-05T00:00:00+00:00"
    markets = [
        ArmedMarketEntry(
            symbol="BTC",
            coin="BTC",
            order_type="OrderType.BUY_STOP",
            entry=100.0,
            stop_loss=90.0,
            take_profit=120.0,
            signal_source="trend_signal",
            selected_signal_type="trend",
            scan_ts=scan_ts,
        )
    ]
    out = save_armed_markets(scan_ts=scan_ts, ttl_hours=24, markets=markets)
    assert out == armed_markets_path(tmp_path)

    loaded_payload = load_armed_markets(data_dir=tmp_path)
    loaded_scan_ts, loaded_ttl, loaded_markets = parse_armed_markets(loaded_payload)
    assert loaded_scan_ts == scan_ts
    assert loaded_ttl == 24
    assert loaded_markets == markets


def test_agent_state_roundtrip(tmp_path) -> None:
    os.environ["TRADING_AGENT_DATA_PATH"] = str(tmp_path)
    state = AgentState(
        pending_order=Order(
            order_type=OrderType.SELL_STOP,
            entry=100.0,
            stop_loss=110.0,
            take_profit=80.0,
            signal_source="trend_signal",
        )
    )
    p = save_agent_state("BTC/USDC", state, data_dir=tmp_path)
    assert p == agent_state_path("BTC/USDC", tmp_path)
    loaded = load_agent_state("BTC/USDC", data_dir=tmp_path)
    assert loaded == state


from __future__ import annotations

from types import SimpleNamespace

from models.agent_state import AgentState
from models.order import Order, OrderType
from scripts.scan_core import ArmedMarketEntry, MarketScanResult, extract_armed_stop_markets


def _mk_result(pending: Order | None) -> SimpleNamespace:
    state = AgentState(pending_order=pending) if pending is not None else AgentState()
    return SimpleNamespace(post_cycle_state=state, strategy_result=None)


def test_extract_armed_stop_markets_includes_trend_and_countertrend_stop_intents() -> None:
    scan_ts = "2026-05-05T00:00:00+00:00"
    stop_order = Order(
        order_type=OrderType.BUY_STOP,
        entry=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        signal_source="trend_signal",
    )
    limit_order = Order(
        order_type=OrderType.BUY_LIMIT,
        entry=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        signal_source="countertrend_signal",
    )

    rows = [
        MarketScanResult(
            symbol="BTC",
            coin="BTC",
            data_batch=None,
            strategy_config=None,
            live_buy_spread=0.0,
            result=_mk_result(stop_order),
            summary={"selected_signal_type": "trend"},
        ),
        MarketScanResult(
            symbol="ETH",
            coin="ETH",
            data_batch=None,
            strategy_config=None,
            live_buy_spread=0.0,
            result=_mk_result(limit_order),
            summary={"selected_signal_type": "countertrend"},
        ),
    ]

    armed = extract_armed_stop_markets(rows, scan_ts=scan_ts)

    assert armed == [
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


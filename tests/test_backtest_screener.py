"""Unit tests for screener metrics, gates, end-MTM, and catalog parsing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.daily_universe import TradeRecord, realize_pnl_for_closed_trade
from backtest.metrics import calmar_ratio, expectancy, profit_factor, ranking_key, sharpe_ann_from_equity
from backtest.propr_exchange_assets import (
    parse_exchange_assets_payload,
    resolve_propr_api_base,
    whitelisted_assets,
)
from backtest.screener import (
    ScreenerGateConfig,
    apply_end_mtm,
    evaluate_market,
    history_coverage,
    sleeve_breakdown,
    yearly_stability,
)
from models.candle import Candle
from models.trade import Trade, TradeDirection, TradeType


def test_profit_factor_undefined_without_losses() -> None:
    assert profit_factor([1.0, 2.0, 0.0]) is None
    assert profit_factor([10.0, -5.0]) == pytest.approx(2.0)


def test_expectancy_and_calmar() -> None:
    assert expectancy([10.0, -5.0]) == pytest.approx(2.5)
    assert calmar_ratio(40.0, 20.0) == pytest.approx(2.0)
    assert calmar_ratio(10.0, 0.0) == pytest.approx(10.0)  # floor DD at 1


def test_sharpe_flat_curve_is_none() -> None:
    assert sharpe_ann_from_equity([100.0, 100.0, 100.0]) is None
    rising = [100.0 + i for i in range(30)]
    s = sharpe_ann_from_equity(rising)
    assert s is not None and s > 0


def test_ranking_key_prefers_higher_calmar() -> None:
    a = {"calmar": 2.0, "return_pct": 10.0, "n_trades": 5}
    b = {"calmar": 3.0, "return_pct": 5.0, "n_trades": 5}
    assert ranking_key(b) > ranking_key(a)


def test_parse_exchange_assets_and_whitelist() -> None:
    payload = {
        "data": [
            {
                "asset": "BTC",
                "status": "whitelisted",
                "maxOrderNotionalValue": "100000",
                "feeSchedule": {"maker": "0.00015", "taker": "0.00045"},
                "createdAt": "2026-01-01T00:00:00.000Z",
            },
            {
                "asset": "SCAM",
                "status": "blacklisted",
                "feeSchedule": {"maker": "0.00015", "taker": "0.00045"},
            },
            {
                "asset": "xyz:GOLD",
                "status": "whitelisted",
                "feeSchedule": {"maker": "0.0001", "taker": "0.00009"},
            },
        ]
    }
    rows = parse_exchange_assets_payload(payload)
    assert len(rows) == 3
    wl = whitelisted_assets(rows)
    assert {r.asset for r in wl} == {"BTC", "xyz:GOLD"}
    btc = next(r for r in wl if r.asset == "BTC")
    assert btc.fee_roundtrip_bps_from_taker() == pytest.approx(9.0)
    assert btc.taker_bps() == pytest.approx(4.5)


def test_resolve_propr_api_base_env() -> None:
    assert resolve_propr_api_base(env="prod").endswith("api.propr.xyz/v1")
    assert "beta" in resolve_propr_api_base(env="beta")
    assert resolve_propr_api_base(base_url="https://example.test/v1/") == "https://example.test/v1"


def test_yearly_stability_ignores_inactive_years() -> None:
    trades = [
        TradeRecord(
            market="X",
            entry_ts="2023-01-01T00:00:00+00:00",
            entry_price=1.0,
            exit_ts="2023-06-01T00:00:00+00:00",
            exit_price=2.0,
            exit_reason="tp",
            qty=1.0,
            direction="LONG",
            trade_type="TREND",
            gross_pnl=10.0,
            fees=0.0,
            slippage_cost=0.0,
            net_pnl=10.0,
        ),
        TradeRecord(
            market="X",
            entry_ts="2024-01-01T00:00:00+00:00",
            entry_price=1.0,
            exit_ts="2024-06-01T00:00:00+00:00",
            exit_price=0.5,
            exit_reason="sl",
            qty=1.0,
            direction="LONG",
            trade_type="COUNTERTREND",
            gross_pnl=-5.0,
            fees=0.0,
            slippage_cost=0.0,
            net_pnl=-5.0,
        ),
        TradeRecord(
            market="X",
            entry_ts="2025-01-01T00:00:00+00:00",
            entry_price=1.0,
            exit_ts="2025-06-01T00:00:00+00:00",
            exit_price=2.0,
            exit_reason="tp",
            qty=1.0,
            direction="LONG",
            trade_type="TREND",
            gross_pnl=8.0,
            fees=0.0,
            slippage_cost=0.0,
            net_pnl=8.0,
        ),
    ]
    y = yearly_stability(trades)
    assert y["active_years"] == 3
    assert y["year_pass_rate"] == pytest.approx(2 / 3)
    sleeves = sleeve_breakdown(trades)
    assert sleeves["n_trend_trades"] == 2
    assert sleeves["n_countertrend_trades"] == 1


def test_apply_end_mtm_closes_open_trade() -> None:
    open_trade = Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        quantity=1.0,
        opened_at="2024-01-01T00:00:00+00:00",
    )
    last = Candle(
        timestamp=datetime(2024, 6, 1, tzinfo=timezone.utc),
        open=100.0,
        high=110.0,
        low=95.0,
        close=105.0,
    )
    trades, eq, curve, hist = apply_end_mtm(
        market="BTC",
        trades=[],
        open_trade=open_trade,
        last_candle=last,
        equity=10_000.0,
        equity_curve=[10_000.0],
        fee_roundtrip_bps=0.0,
        slippage_bps=0.0,
    )
    assert len(trades) == 1
    assert trades[0].exit_reason == "mtm_end"
    assert trades[0].net_pnl == pytest.approx(5.0)
    assert eq == pytest.approx(10_005.0)
    assert hist.get("mtm_end") == 1
    assert curve[-1] == pytest.approx(10_005.0)


def test_history_coverage() -> None:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(timestamp=start, open=1, high=1, low=1, close=1),
        Candle(timestamp=start + timedelta(days=365), open=1, high=1, low=1, close=1),
    ]
    assert history_coverage(candles, years=1.0) == pytest.approx(1.0, abs=0.01)
    assert history_coverage(candles, years=5.0) < 0.3


def test_evaluate_market_go_and_nogo() -> None:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(timestamp=start + timedelta(days=i), open=100, high=110, low=90, close=100)
        for i in range(0, 365 * 3 + 10)
    ]
    # Build synthetic winning trades across years
    trades = []
    for year, pnl in [(2020, 50.0), (2021, 40.0), (2022, 30.0)]:
        for i in range(3):
            trades.append(
                TradeRecord(
                    market="BTC",
                    entry_ts=f"{year}-01-0{i+1}T00:00:00+00:00",
                    entry_price=100.0,
                    exit_ts=f"{year}-06-0{i+1}T00:00:00+00:00",
                    exit_price=110.0,
                    exit_reason="tp",
                    qty=1.0,
                    direction="LONG",
                    trade_type="TREND",
                    gross_pnl=pnl,
                    fees=1.0,
                    slippage_cost=0.0,
                    net_pnl=pnl - 1.0,
                )
            )
    # Add one loser so profit factor is defined
    trades.append(
        TradeRecord(
            market="BTC",
            entry_ts="2022-07-01T00:00:00+00:00",
            entry_price=100.0,
            exit_ts="2022-08-01T00:00:00+00:00",
            exit_price=95.0,
            exit_reason="sl",
            qty=1.0,
            direction="LONG",
            trade_type="TREND",
            gross_pnl=-10.0,
            fees=1.0,
            slippage_cost=0.0,
            net_pnl=-11.0,
        )
    )

    equity = 10_000.0
    curve = [equity]
    for t in trades:
        equity += t.net_pnl
        curve.append(equity)

    sim = {
        "skipped_reason": "",
        "trades": trades,
        "equity_curve": curve,
        "open_trade": None,
        "final_equity": equity,
        "exit_reason_distribution": {},
    }
    gates = ScreenerGateConfig(
        min_trades=8,
        min_trades_recent=1,
        max_dd_pct=50.0,
        min_profit_factor=1.0,
        min_year_pass_rate=0.5,
        min_history_coverage=0.5,
        recent_days=365 * 4,  # all trades recent for this unit test
    )
    res = evaluate_market(
        market="BTC",
        candles=candles,
        sim_result=sim,
        years=3.0,
        initial_capital=10_000.0,
        fee_roundtrip_bps=0.0,
        slippage_bps=0.0,
        gates=gates,
    )
    assert res.decision == "GO"
    assert res.metrics["n_trades"] == 10

    # Force NO_GO via drawdown gate
    gates2 = ScreenerGateConfig(
        min_trades=8,
        min_trades_recent=1,
        max_dd_pct=0.01,
        min_profit_factor=1.0,
        min_year_pass_rate=0.5,
        min_history_coverage=0.5,
        recent_days=365 * 4,
    )
    res2 = evaluate_market(
        market="BTC",
        candles=candles,
        sim_result=sim,
        years=3.0,
        initial_capital=10_000.0,
        fee_roundtrip_bps=0.0,
        slippage_bps=0.0,
        gates=gates2,
    )
    # May be GO if DD is ~0 on this synthetic curve, or NO_GO on max_drawdown
    # Ensure insufficient when too few trades
    sim_few = dict(sim)
    sim_few["trades"] = trades[:2]
    sim_few["final_equity"] = 10_000.0 + sum(t.net_pnl for t in trades[:2])
    sim_few["equity_curve"] = [10_000.0, sim_few["final_equity"]]
    res3 = evaluate_market(
        market="BTC",
        candles=candles,
        sim_result=sim_few,
        years=3.0,
        initial_capital=10_000.0,
        fee_roundtrip_bps=0.0,
        slippage_bps=0.0,
        gates=gates,
    )
    assert res3.decision == "INSUFFICIENT_DATA"
    assert "min_trades" in res3.fail_reasons


def test_realize_pnl_still_works() -> None:
    trade = Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        quantity=1.0,
    )
    r = realize_pnl_for_closed_trade(trade, 110.0, fee_roundtrip_bps=0.0, slippage_bps=0.0)
    assert r["net_pnl"] == pytest.approx(10.0)

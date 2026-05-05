"""Tests for daily backtest PnL helpers and SL/TP touch rules."""

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.daily_universe import (
    realize_pnl_for_closed_trade,
    touch_trade_sl_tp,
)
from models.candle import Candle
from models.trade import Trade, TradeDirection, TradeType


def _bar(*, low: float, high: float, open_: float = 100.0, close: float = 100.0) -> Candle:
    return Candle(
        timestamp=datetime(2024, 6, 15, tzinfo=timezone.utc),
        open=open_,
        high=high,
        low=low,
        close=close,
    )


def _long_trade() -> Trade:
    return Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=90.0,
        take_profit=120.0,
        quantity=1.0,
        opened_at="2024-06-14T00:00:00+00:00",
    )


def test_touch_long_sl_before_tp_when_both_hit_conservative() -> None:
    trade = _long_trade()
    bar = _bar(low=85.0, high=125.0)
    ex = touch_trade_sl_tp(trade, bar, optimistic=False)
    assert ex is not None
    assert ex.reason == "sl"
    assert ex.price == 90.0


def test_touch_long_tp_first_when_optimistic() -> None:
    trade = _long_trade()
    bar = _bar(low=85.0, high=125.0)
    ex = touch_trade_sl_tp(trade, bar, optimistic=True)
    assert ex is not None
    assert ex.reason == "tp"
    assert ex.price == 120.0


def test_realize_pnl_long_applies_fees_and_slippage() -> None:
    trade = _long_trade()
    r = realize_pnl_for_closed_trade(
        trade,
        110.0,
        fee_roundtrip_bps=10.0,
        slippage_bps=0.0,
    )
    assert r["gross_pnl"] == pytest.approx(10.0)
    assert r["fees"] > 0
    assert r["net_pnl"] < r["gross_pnl"]

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from config.strategy_config import build_strategy_config
from models.candle import Candle
from scripts.export_strategy_diagnostics import build_strategy_diagnostics_rows


def _make_candles() -> list[Candle]:
    closes = [100.0, 101.0, 102.5, 103.0, 104.5, 105.0, 106.0, 107.5]
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        open_price = close - 0.5
        candles.append(
            Candle(
                timestamp=base_time + timedelta(days=index),
                open=open_price,
                high=close + 0.5,
                low=open_price - 0.5,
                close=close,
            )
        )
    return candles


def test_build_strategy_diagnostics_rows_exports_expected_fields() -> None:
    config = build_strategy_config(
        bollinger_period=3,
        macd_fast_period=2,
        macd_slow_period=4,
        macd_signal_period=2,
        min_bandwidth_avg_period=3,
    )

    rows = build_strategy_diagnostics_rows(
        _make_candles(),
        config=config,
        min_warmup_bars=3,
    )

    assert len(rows) == 3
    assert rows[0]["required_warmup_bars"] == 6
    assert rows[0]["bollinger_period"] == 3
    assert rows[0]["macd_slow_period"] == 4
    assert rows[-1]["timestamp"] == "2026-01-08T00:00:00+00:00"
    assert "decision_action" in rows[-1]
    assert "trend_reason" in rows[-1]
    assert "bb_lower" in rows[-1]

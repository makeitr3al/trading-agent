from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from models.candle import Candle
from strategy.agent_cycle import _middle_band_retest_ok


def _ts(i: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)


def _c(i: int, *, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(timestamp=_ts(i), open=o, high=h, low=l, close=c)


def _bb(n: int, *, upper: float, middle: float, lower: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "bb_upper": [upper] * n,
            "bb_middle": [middle] * n,
            "bb_lower": [lower] * n,
        }
    )


def test_middle_band_retest_blocks_after_prior_outside_close_until_wick_touch() -> None:
    # Index 1 closes above upper -> anchor at 1.
    candles = [
        _c(0, o=10, h=12, l=9, c=11),
        _c(1, o=10, h=120, l=10, c=110),  # outside above upper=100
        _c(2, o=90, h=99, l=80, c=95),  # does NOT reach middle=50 (range is above 50? actually l=80)
        _c(3, o=90, h=99, l=80, c=95),
    ]
    bb = _bb(len(candles), upper=100, middle=50, lower=0)

    ok, consumed, detail = _middle_band_retest_ok(
        candles, bb, signal_bar_idx=3, state_anchor_ts=None
    )
    assert ok is False
    assert consumed is False
    assert detail is not None

    # Now add a wick touch on index 2 by making its low <= middle <= high.
    candles[2] = _c(2, o=90, h=99, l=40, c=95)
    ok, consumed, detail = _middle_band_retest_ok(
        candles, bb, signal_bar_idx=3, state_anchor_ts=None
    )
    assert ok is True
    assert consumed is True
    assert detail is None


def test_middle_band_retest_excludes_signal_bar_from_geometric_anchor() -> None:
    # Signal bar itself closes outside. Because it is excluded from anchor search (j < signal_bar_idx),
    # this should not self-block.
    candles = [
        _c(0, o=10, h=12, l=9, c=11),
        _c(1, o=10, h=12, l=9, c=11),
        _c(2, o=10, h=12, l=9, c=11),
        _c(3, o=10, h=120, l=10, c=110),  # outside above upper=100 (signal bar)
    ]
    bb = _bb(len(candles), upper=100, middle=50, lower=0)

    ok, consumed, detail = _middle_band_retest_ok(
        candles, bb, signal_bar_idx=3, state_anchor_ts=None
    )
    assert ok is True
    assert consumed is True
    assert detail is None


def test_middle_band_retest_consumes_state_anchor_only_after_wick_on_or_after_anchor() -> None:
    candles = [
        _c(0, o=10, h=12, l=9, c=11),
        _c(1, o=10, h=120, l=10, c=110),  # outside (geom anchor at 1)
        _c(2, o=90, h=99, l=40, c=95),  # wick touch at 2
        _c(3, o=90, h=99, l=80, c=95),
    ]
    bb = _bb(len(candles), upper=100, middle=50, lower=0)
    state_anchor_ts = candles[1].timestamp.isoformat()

    ok, consumed, detail = _middle_band_retest_ok(
        candles, bb, signal_bar_idx=3, state_anchor_ts=state_anchor_ts
    )
    assert ok is True
    assert consumed is True
    assert detail is None


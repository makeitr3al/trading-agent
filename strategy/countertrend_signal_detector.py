import math

import pandas as pd

from config.strategy_config import StrategyConfig
from models.candle import Candle
from models.regime import RegimeState, RegimeType
from models.signal import SignalState, SignalType
from strategy.signal_rules import (
    get_relevant_half_bandwidth,
    has_sufficient_bandwidth,
    is_close_deep_outside_bands,
)

# TODO: Later add support for later countertrend setups as trade management.
# TODO: Later add support for reversing an active trend trade.
# TODO: Later add order type selection between limit and stop.


def detect_countertrend_signal(
    candles: list[Candle],
    bollinger_df: pd.DataFrame,
    regime_states: list[RegimeState],
    config: StrategyConfig,
) -> SignalState | None:
    if not candles or bollinger_df.empty or not regime_states:
        return None

    available_bars = min(len(candles), len(bollinger_df), len(regime_states))
    if available_bars < 1:
        return None

    latest_candle = candles[available_bars - 1]
    latest_bollinger = bollinger_df.iloc[available_bars - 1]
    latest_regime_state = regime_states[available_bars - 1]

    if latest_bollinger[["bb_upper", "bb_middle", "bb_lower"]].isna().any():
        return None

    regime = latest_regime_state.regime
    if regime == RegimeType.NEUTRAL:
        return SignalState(
            signal_type=SignalType.COUNTERTREND_SHORT,
            is_valid=False,
            reason="neutral regime",
        )

    signal_type = (
        SignalType.COUNTERTREND_SHORT
        if regime == RegimeType.BULLISH
        else SignalType.COUNTERTREND_LONG
    )

    if latest_regime_state.bars_since_regime_start != 1:
        return SignalState(
            signal_type=signal_type,
            is_valid=False,
            reason="not first regime bar",
        )

    bb_upper = float(latest_bollinger["bb_upper"])
    bb_middle = float(latest_bollinger["bb_middle"])
    bb_lower = float(latest_bollinger["bb_lower"])

    if not is_close_deep_outside_bands(
        close=latest_candle.close,
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        outside_buffer_pct=config.outside_buffer_pct,
    ):
        return SignalState(
            signal_type=signal_type,
            is_valid=False,
            reason="close not deep outside bands",
        )

    historical_rows = bollinger_df.iloc[
        max(0, available_bars - config.min_bandwidth_avg_period) : available_bars
    ]
    historical_half_bandwidths = [
        get_relevant_half_bandwidth(
            regime=regime,
            bb_upper=float(row.bb_upper),
            bb_middle=float(row.bb_middle),
            bb_lower=float(row.bb_lower),
        )
        for row in historical_rows.itertuples(index=False)
        if not any(
            math.isnan(float(value))
            for value in (row.bb_upper, row.bb_middle, row.bb_lower)
        )
    ]
    current_half_bandwidth = get_relevant_half_bandwidth(
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
    )

    if not has_sufficient_bandwidth(
        current_half_bandwidth=current_half_bandwidth,
        historical_half_bandwidths=historical_half_bandwidths,
        min_bandwidth_ratio=config.min_bandwidth_ratio,
    ):
        return SignalState(
            signal_type=signal_type,
            is_valid=False,
            reason="insufficient bandwidth",
        )

    entry = latest_candle.close
    if regime == RegimeType.BULLISH:
        stop_loss = entry + (entry - bb_middle)
    else:
        stop_loss = entry - (bb_middle - entry)

    return SignalState(
        signal_type=signal_type,
        is_valid=True,
        reason="countertrend signal detected",
        entry=entry,
        stop_loss=stop_loss,
        take_profit=bb_middle,
    )

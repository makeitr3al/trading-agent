import math

import pandas as pd

from config.strategy_config import StrategyConfig
from models.candle import Candle
from models.regime import RegimeState, RegimeType
from models.signal import SignalState, SignalType
from strategy.signal_rules import (
    get_relevant_half_bandwidth,
    has_sufficient_bandwidth,
    is_candle_in_trend_direction,
    is_close_deep_inside_bands,
)

# TODO: Later add checks for earlier potential trend entries within the same regime.
# TODO: Later add handling for last neutral phase, fake countertrend, and neutralization.


def _trend_signal_strength(
    candle_open: float,
    candle_close: float,
    regime: RegimeType,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
) -> float:
    relevant_half_bandwidth = get_relevant_half_bandwidth(
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
    )
    if relevant_half_bandwidth <= 0:
        return 0.0

    if regime == RegimeType.BULLISH:
        directional_body = candle_close - candle_open
        directional_position = candle_close - bb_middle
    else:
        directional_body = candle_open - candle_close
        directional_position = bb_middle - candle_close

    normalized_body = max(0.0, directional_body / relevant_half_bandwidth)
    normalized_position = max(0.0, directional_position / relevant_half_bandwidth)
    return round(normalized_body + normalized_position, 8)


def detect_trend_signal(
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
        return SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=False,
            reason="too few bars since data start",
        )

    regime = latest_regime_state.regime
    if regime == RegimeType.NEUTRAL:
        return SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=False,
            reason="neutral regime",
        )

    signal_type = (
        SignalType.TREND_LONG
        if regime == RegimeType.BULLISH
        else SignalType.TREND_SHORT
    )

    if latest_regime_state.bars_since_regime_start > (
        config.max_bars_since_regime_start_for_trend_signal
    ):
        return SignalState(
            signal_type=signal_type,
            is_valid=False,
            reason="regime too old",
        )

    if not is_candle_in_trend_direction(
        candle_open=latest_candle.open,
        candle_close=latest_candle.close,
        regime=regime,
    ):
        return SignalState(
            signal_type=signal_type,
            is_valid=False,
            reason="candle not in trend direction",
        )

    bb_upper = float(latest_bollinger["bb_upper"])
    bb_middle = float(latest_bollinger["bb_middle"])
    bb_lower = float(latest_bollinger["bb_lower"])

    if not is_close_deep_inside_bands(
        close=latest_candle.close,
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        inside_buffer_pct=config.inside_buffer_pct,
    ):
        return SignalState(
            signal_type=signal_type,
            is_valid=False,
            reason="close not deep inside bands",
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
        if not any(math.isnan(float(value)) for value in (row.bb_upper, row.bb_middle, row.bb_lower))
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

    if regime == RegimeType.BULLISH:
        entry = bb_upper
        stop_loss = bb_middle
        risk = entry - stop_loss
        take_profit = entry + config.trend_tp_rr * risk
    else:
        entry = bb_lower
        stop_loss = bb_middle
        risk = stop_loss - entry
        take_profit = entry - config.trend_tp_rr * risk

    return SignalState(
        signal_type=signal_type,
        is_valid=True,
        reason="trend signal detected",
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        signal_strength=_trend_signal_strength(
            candle_open=latest_candle.open,
            candle_close=latest_candle.close,
            regime=regime,
            bb_upper=bb_upper,
            bb_middle=bb_middle,
            bb_lower=bb_lower,
        ),
    )

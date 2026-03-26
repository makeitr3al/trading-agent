from models.regime import RegimeType


def get_relevant_half_bandwidth(
    regime: RegimeType,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
) -> float:
    """Return the regime-relevant half of the Bollinger bandwidth."""
    if regime == RegimeType.BEARISH:
        return bb_middle - bb_lower

    return bb_upper - bb_middle


def is_close_deep_inside_bands(
    close: float,
    regime: RegimeType,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
    inside_buffer_pct: float,
) -> bool:
    """Check whether the close is deeply inside the relevant side of the bands."""
    if regime == RegimeType.NEUTRAL:
        return False

    if not bb_lower <= close <= bb_upper:
        return False

    relevant_half_bandwidth = get_relevant_half_bandwidth(
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
    )
    required_distance = inside_buffer_pct * relevant_half_bandwidth

    if regime == RegimeType.BULLISH:
        return (bb_upper - close) >= required_distance

    return (close - bb_lower) >= required_distance


def is_close_deep_outside_bands(
    close: float,
    regime: RegimeType,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
    outside_buffer_pct: float,
) -> bool:
    """Check whether the close is deeply outside the relevant side of the bands."""
    if regime == RegimeType.NEUTRAL:
        return False

    relevant_half_bandwidth = get_relevant_half_bandwidth(
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
    )
    required_distance = outside_buffer_pct * relevant_half_bandwidth

    if regime == RegimeType.BULLISH:
        return close >= bb_upper + required_distance

    return close <= bb_lower - required_distance


def is_candle_in_trend_direction(
    candle_open: float,
    candle_close: float,
    regime: RegimeType,
) -> bool:
    """Return whether the candle direction aligns with the current regime."""
    if regime == RegimeType.BULLISH:
        return candle_close > candle_open

    if regime == RegimeType.BEARISH:
        return candle_close < candle_open

    return False


def has_sufficient_bandwidth(
    current_half_bandwidth: float,
    historical_half_bandwidths: list[float],
    min_bandwidth_ratio: float,
) -> bool:
    """Compare the current half bandwidth against the historical average."""
    if not historical_half_bandwidths:
        return False

    average_half_bandwidth = sum(historical_half_bandwidths) / len(
        historical_half_bandwidths
    )
    return current_half_bandwidth >= min_bandwidth_ratio * average_half_bandwidth


def touches_middle_band(
    high: float,
    low: float,
    bb_middle: float,
) -> bool:
    """Return whether the candle range touches the middle band."""
    return low <= bb_middle <= high

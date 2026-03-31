from enum import Enum


class SignalReason(str, Enum):
    # Trend detector
    TOO_FEW_BARS_SINCE_DATA_START = "too few bars since data start"
    NEUTRAL_REGIME = "neutral regime"
    REGIME_TOO_OLD = "regime too old"
    CANDLE_NOT_IN_TREND_DIRECTION = "candle not in trend direction"
    CLOSE_NOT_DEEP_INSIDE_BANDS = "close not deep inside bands"
    TREND_SIGNAL_DETECTED = "trend signal detected"

    # Countertrend detector
    NOT_FIRST_REGIME_BAR = "not first regime bar"
    CLOSE_NOT_OUTSIDE_BANDS = "close not outside bands"
    COUNTERTREND_SIGNAL_DETECTED = "countertrend signal detected"

    # Shared
    INSUFFICIENT_BANDWIDTH = "insufficient bandwidth"

    # Agent cycle
    WAITING_FOR_MIDDLE_BAND_RETEST = "waiting for middle band retest"
    TREND_SIGNAL_ALREADY_CONSUMED_IN_REGIME = "trend signal already consumed in regime"
    COUNTERTREND_SIGNAL_ALREADY_CONSUMED_IN_REGIME = "countertrend signal already consumed in regime direction"
    REFRESH_TREND_PENDING_ORDER = "refresh trend pending order"

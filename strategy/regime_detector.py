import pandas as pd

from models.regime import RegimeState, RegimeType


def detect_regime(macd: float, macd_signal: float) -> RegimeType:
    if macd > 0 and macd > macd_signal:
        return RegimeType.BULLISH

    if macd < 0 and macd < macd_signal:
        return RegimeType.BEARISH

    return RegimeType.NEUTRAL


def build_regime_states(macd_df: pd.DataFrame) -> list[RegimeState]:
    regime_states: list[RegimeState] = []
    previous_regime: RegimeType | None = None
    bars_since_regime_start = 0

    for row in macd_df.itertuples(index=False):
        current_regime = detect_regime(macd=row.macd, macd_signal=row.macd_signal)

        if current_regime == previous_regime:
            bars_since_regime_start += 1
        else:
            bars_since_regime_start = 1

        regime_states.append(
            RegimeState(
                regime=current_regime,
                bars_since_regime_start=bars_since_regime_start,
            )
        )
        previous_regime = current_regime

    return regime_states

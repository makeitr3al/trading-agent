from enum import Enum

from pydantic import BaseModel


class RegimeType(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class RegimeState(BaseModel):
    regime: RegimeType
    bars_since_regime_start: int

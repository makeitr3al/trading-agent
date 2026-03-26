from enum import Enum

from pydantic import BaseModel


class SignalType(str, Enum):
    TREND_LONG = "TREND_LONG"
    TREND_SHORT = "TREND_SHORT"
    COUNTERTREND_LONG = "COUNTERTREND_LONG"
    COUNTERTREND_SHORT = "COUNTERTREND_SHORT"


class SignalState(BaseModel):
    signal_type: SignalType
    is_valid: bool
    reason: str
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None

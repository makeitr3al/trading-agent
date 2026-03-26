from enum import Enum

from pydantic import BaseModel


class DecisionAction(str, Enum):
    NO_ACTION = "NO_ACTION"
    PREPARE_TREND_ORDER = "PREPARE_TREND_ORDER"
    PREPARE_COUNTERTREND_ORDER = "PREPARE_COUNTERTREND_ORDER"
    KEEP_EXISTING_TREND_TRADE = "KEEP_EXISTING_TREND_TRADE"
    CLOSE_TREND_AND_PREPARE_COUNTERTREND = "CLOSE_TREND_AND_PREPARE_COUNTERTREND"


class DecisionResult(BaseModel):
    action: DecisionAction
    reason: str
    selected_signal_type: str | None = None

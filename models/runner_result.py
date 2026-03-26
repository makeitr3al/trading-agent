from pydantic import BaseModel

from models.decision import DecisionResult
from models.order import Order
from models.signal import SignalState
from models.trade import Trade


class StrategyRunResult(BaseModel):
    trend_signal: SignalState | None
    countertrend_signal: SignalState | None
    decision: DecisionResult
    order: Order | None
    updated_trade: Trade | None

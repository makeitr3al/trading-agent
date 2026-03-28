from enum import Enum

from pydantic import BaseModel


class TradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeType(str, Enum):
    TREND = "TREND"
    COUNTERTREND = "COUNTERTREND"


class Trade(BaseModel):
    trade_type: TradeType
    direction: TradeDirection
    entry: float
    stop_loss: float
    take_profit: float
    quantity: float | None = None
    position_id: str | None = None
    is_active: bool = True
    break_even_activated: bool = False
    opened_at: str | None = None

from enum import Enum

from pydantic import BaseModel


class OrderType(str, Enum):
    BUY_STOP = "BUY_STOP"
    SELL_STOP = "SELL_STOP"
    BUY_LIMIT = "BUY_LIMIT"
    SELL_LIMIT = "SELL_LIMIT"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class Order(BaseModel):
    order_type: OrderType
    status: OrderStatus = OrderStatus.PENDING
    entry: float
    stop_loss: float
    take_profit: float
    position_size: float | None = None
    signal_source: str
    created_at: str | None = None

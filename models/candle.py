from datetime import datetime

from pydantic import BaseModel, model_validator


class Candle(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float

    @model_validator(mode="after")
    def _validate_ohlc(self) -> "Candle":
        if self.high < self.open or self.high < self.close:
            raise ValueError("high must be >= open and close")
        if self.low > self.open or self.low > self.close:
            raise ValueError("low must be <= open and close")
        if self.low < 0:
            raise ValueError("low must be >= 0")
        return self

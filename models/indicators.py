from pydantic import BaseModel


class IndicatorValues(BaseModel):
    bb_upper: float
    bb_middle: float
    bb_lower: float
    macd: float
    macd_signal: float

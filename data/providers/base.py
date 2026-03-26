from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from config.strategy_config import StrategyConfig
from models.candle import Candle


@dataclass
class DataBatch:
    candles: list[Candle]
    symbol: str | None = None
    source_name: str = "unknown"
    config: StrategyConfig | None = None


class CandleDataProvider(Protocol):
    def get_data(self) -> DataBatch:
        ...

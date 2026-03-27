from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from config.strategy_config import StrategyConfig
from models.agent_state import AgentState
from models.candle import Candle
from models.trade import Trade


@dataclass
class DataBatch:
    candles: list[Candle]
    symbol: str | None = None
    source_name: str = "unknown"
    config: StrategyConfig | None = None
    account_balance: float | None = None
    active_trade: Trade | None = None
    agent_state: AgentState | None = None


class CandleDataProvider(Protocol):
    def get_data(self) -> DataBatch:
        ...

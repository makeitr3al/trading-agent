from __future__ import annotations

from datetime import datetime, timedelta

from config.strategy_config import StrategyConfig
from data.providers.base import DataBatch
from models.candle import Candle


# TODO: Replace the live stub with a real production market data source.
# TODO: Later support broker-native or exchange-native candles.

DEMO_CLOSES = [
    1.0950,
    1.0954,
    1.0957,
    1.0959,
    1.0961,
    1.0965,
    1.0968,
    1.0970,
    1.0974,
    1.0978,
    1.0981,
    1.0983,
    1.0986,
    1.0990,
    1.0994,
    1.0997,
    1.1001,
    1.1005,
    1.1008,
    1.1010,
    1.1014,
    1.1017,
    1.1020,
    1.1023,
    1.1027,
    1.1030,
    1.1034,
    1.1038,
    1.1041,
    1.1044,
    1.1048,
    1.1051,
    1.1055,
    1.1058,
    1.1062,
    1.1065,
    1.1069,
    1.1072,
    1.1076,
    1.1080,
]


class LiveDataProvider:
    def get_data(self) -> DataBatch:
        start = datetime(2026, 1, 1, 0, 0, 0)
        candles: list[Candle] = []
        for index, close in enumerate(DEMO_CLOSES):
            candles.append(
                Candle(
                    timestamp=start + timedelta(hours=index),
                    open=close - 0.0010,
                    high=close + 0.0015,
                    low=close - 0.0015,
                    close=close,
                )
            )

        return DataBatch(
            candles=candles,
            symbol=None,
            source_name="live_stub",
            config=StrategyConfig(),
        )

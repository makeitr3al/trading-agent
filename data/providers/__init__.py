from config.hyperliquid_config import HyperliquidConfig
from data.providers.base import CandleDataProvider, DataBatch
from data.providers.contract import validate_data_batch
from data.providers.golden_data_provider import GoldenDataProvider
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from data.providers.live_data_provider import LiveDataProvider
from utils.env_loader import load_hyperliquid_config_from_env


def get_data_provider(
    data_source: str,
    golden_scenario: str | None = None,
    hyperliquid_config: HyperliquidConfig | None = None,
) -> CandleDataProvider:
    if data_source == "live":
        return HyperliquidHistoricalProvider(hyperliquid_config or load_hyperliquid_config_from_env())
    if data_source == "golden":
        return GoldenDataProvider(golden_scenario or "")
    raise ValueError(f"Unsupported data source: {data_source}")


__all__ = [
    "DataBatch",
    "CandleDataProvider",
    "GoldenDataProvider",
    "HyperliquidHistoricalProvider",
    "HyperliquidConfig",
    "LiveDataProvider",
    "get_data_provider",
    "validate_data_batch",
]

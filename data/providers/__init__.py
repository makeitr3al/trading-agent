from data.providers.base import CandleDataProvider, DataBatch
from data.providers.golden_data_provider import GoldenDataProvider
from data.providers.live_data_provider import LiveDataProvider


def get_data_provider(
    data_source: str,
    golden_scenario: str | None = None,
) -> CandleDataProvider:
    if data_source == "live":
        return LiveDataProvider()
    if data_source == "golden":
        return GoldenDataProvider(golden_scenario or "")
    raise ValueError(f"Unsupported data source: {data_source}")


__all__ = [
    "DataBatch",
    "CandleDataProvider",
    "GoldenDataProvider",
    "LiveDataProvider",
    "get_data_provider",
]

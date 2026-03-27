from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.hyperliquid_config import HyperliquidConfig
from data.providers.hyperliquid_historical_provider import (
    HyperliquidHistoricalProvider,
    compute_time_range_ms,
)
from utils.env_loader import load_hyperliquid_config_from_env


class FakeHyperliquidHttpClient:
    def __init__(self, response):
        self.response = response
        self.last_url = None
        self.last_json = None

    def post(self, url: str, json: dict):
        self.last_url = url
        self.last_json = json
        return self.response



def test_computes_correct_time_range_for_1h_interval() -> None:
    start_ms, end_ms = compute_time_range_ms("1h", 10, now_ms=1_800_000_000_000)

    assert end_ms == 1_800_000_000_000
    assert start_ms == 1_800_000_000_000 - (10 * 60 * 60 * 1000)



def test_computes_correct_time_range_for_1d_interval() -> None:
    start_ms, end_ms = compute_time_range_ms("1d", 3, now_ms=1_800_000_000_000)

    assert end_ms == 1_800_000_000_000
    assert start_ms == 1_800_000_000_000 - (3 * 24 * 60 * 60 * 1000)



def test_raises_value_error_for_unknown_interval() -> None:
    with pytest.raises(ValueError, match="Unsupported Hyperliquid interval"):
        compute_time_range_ms("2h", 10, now_ms=1_800_000_000_000)



def test_maps_candle_snapshot_response_to_internal_candles() -> None:
    fake_client = FakeHyperliquidHttpClient(
        [
            {"t": 1_700_000_000_000, "o": "100", "h": "110", "l": "95", "c": "105"},
            {"time": 1_700_000_060_000, "open": 105, "high": 112, "low": 101, "close": 111},
        ]
    )
    provider = HyperliquidHistoricalProvider(
        HyperliquidConfig(coin="BTC", interval="1h", lookback_bars=2),
        http_client=fake_client,
    )

    batch = provider.fetch_candles()

    assert len(batch.candles) == 2
    assert batch.candles[0].timestamp == datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=timezone.utc)
    assert batch.candles[0].open == 100.0
    assert batch.candles[0].high == 110.0
    assert batch.candles[0].low == 95.0
    assert batch.candles[0].close == 105.0
    assert fake_client.last_url == "https://api.hyperliquid.xyz/info"
    assert fake_client.last_json["type"] == "candleSnapshot"
    assert fake_client.last_json["req"]["coin"] == "BTC"



def test_sorts_candles_chronologically() -> None:
    fake_client = FakeHyperliquidHttpClient(
        [
            {"t": 1_700_000_060_000, "o": "105", "h": "112", "l": "101", "c": "111"},
            {"t": 1_700_000_000_000, "o": "100", "h": "110", "l": "95", "c": "105"},
        ]
    )
    provider = HyperliquidHistoricalProvider(HyperliquidConfig(coin="BTC"), http_client=fake_client)

    batch = provider.fetch_candles()

    assert batch.candles[0].timestamp < batch.candles[1].timestamp



def test_returns_data_batch_with_hyperliquid_source_name() -> None:
    fake_client = FakeHyperliquidHttpClient(
        [{"t": 1_700_000_000_000, "o": "100", "h": "110", "l": "95", "c": "105"}]
    )
    provider = HyperliquidHistoricalProvider(HyperliquidConfig(coin="ETH"), http_client=fake_client)

    batch = provider.fetch_candles()

    assert batch.source_name == "hyperliquid_historical"
    assert batch.symbol == "ETH"



def test_raises_clear_error_when_response_is_empty_or_invalid() -> None:
    empty_provider = HyperliquidHistoricalProvider(
        HyperliquidConfig(coin="BTC"),
        http_client=FakeHyperliquidHttpClient([]),
    )
    invalid_provider = HyperliquidHistoricalProvider(
        HyperliquidConfig(coin="BTC"),
        http_client=FakeHyperliquidHttpClient([{"t": 1_700_000_000_000, "o": "100"}]),
    )

    with pytest.raises(ValueError, match="empty or invalid"):
        empty_provider.fetch_candles()

    with pytest.raises(ValueError, match="empty or invalid"):
        invalid_provider.fetch_candles()



def test_env_loader_loads_hyperliquid_config_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPERLIQUID_COIN", "ETH")
    monkeypatch.setenv("HYPERLIQUID_BASE_URL", "https://api.example.xyz")
    monkeypatch.setenv("HYPERLIQUID_INTERVAL", "4h")
    monkeypatch.setenv("HYPERLIQUID_LOOKBACK_BARS", "123")

    config = load_hyperliquid_config_from_env()

    assert config.coin == "ETH"
    assert config.base_url == "https://api.example.xyz"
    assert config.interval == "4h"
    assert config.lookback_bars == 123



def test_env_loader_raises_error_when_hyperliquid_coin_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPERLIQUID_COIN", raising=False)
    monkeypatch.delenv("HYPERLIQUID_BASE_URL", raising=False)
    monkeypatch.delenv("HYPERLIQUID_INTERVAL", raising=False)
    monkeypatch.delenv("HYPERLIQUID_LOOKBACK_BARS", raising=False)

    with pytest.raises(ValueError, match="Missing HYPERLIQUID_COIN"):
        load_hyperliquid_config_from_env()

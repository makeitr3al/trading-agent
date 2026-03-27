from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import requests

from config.hyperliquid_config import HyperliquidConfig
from data.providers.base import DataBatch
from models.candle import Candle


_INTERVAL_TO_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}


class HyperliquidHttpClient(Protocol):
    def post(self, url: str, json: dict[str, Any]) -> Any:
        ...


class RequestsHyperliquidHttpClient:
    def post(self, url: str, json: dict[str, Any]) -> Any:
        response = requests.post(url, json=json, timeout=30)
        response.raise_for_status()
        return response.json()


def compute_time_range_ms(
    interval: str,
    lookback_bars: int,
    now_ms: int | None = None,
) -> tuple[int, int]:
    interval_ms = _INTERVAL_TO_MS.get(interval)
    if interval_ms is None:
        raise ValueError(f"Unsupported Hyperliquid interval: {interval}")

    if lookback_bars <= 0:
        raise ValueError("lookback_bars must be greater than 0")

    end_time = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    start_time = end_time - (lookback_bars * interval_ms)
    return start_time, end_time


class HyperliquidHistoricalProvider:
    def __init__(
        self,
        config: HyperliquidConfig,
        http_client: HyperliquidHttpClient | None = None,
    ) -> None:
        self.config = config
        self.http_client = http_client or RequestsHyperliquidHttpClient()

    def get_data(self) -> DataBatch:
        return self.fetch_candles()

    def fetch_candles(self) -> DataBatch:
        start_ms, end_ms = compute_time_range_ms(
            interval=self.config.interval,
            lookback_bars=self.config.lookback_bars,
        )
        url = f"{self.config.base_url.rstrip('/')}{self.config.info_path}"
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": self.config.coin,
                "interval": self.config.interval,
                "startTime": start_ms,
                "endTime": end_ms,
            },
        }
        response = self.http_client.post(url, json=payload)
        candles = self._parse_candles(response)
        return DataBatch(
            candles=candles,
            symbol=self.config.coin,
            source_name="hyperliquid_historical",
        )

    def _parse_candles(self, payload: Any) -> list[Candle]:
        if not isinstance(payload, list) or not payload:
            raise ValueError("Hyperliquid candleSnapshot response is empty or invalid")

        candles: list[Candle] = []
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Hyperliquid candleSnapshot response is empty or invalid")

            timestamp_ms = self._get_first_present(item, "time", "t")
            open_price = self._get_first_present(item, "open", "o")
            high_price = self._get_first_present(item, "high", "h")
            low_price = self._get_first_present(item, "low", "l")
            close_price = self._get_first_present(item, "close", "c")

            if None in {timestamp_ms, open_price, high_price, low_price, close_price}:
                raise ValueError("Hyperliquid candleSnapshot response is empty or invalid")

            candles.append(
                Candle(
                    timestamp=datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=timezone.utc),
                    open=float(open_price),
                    high=float(high_price),
                    low=float(low_price),
                    close=float(close_price),
                )
            )

        return sorted(candles, key=lambda candle: candle.timestamp)

    @staticmethod
    def _get_first_present(payload: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return value
        return None

from datetime import timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(TESTS_ROOT))

from config.hyperliquid_config import HyperliquidConfig
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from fixtures.strategy_scenarios import valid_trend_long_scenario
from strategy.engine import run_strategy_cycle


class FakeHyperliquidHttpClient:
    def __init__(self, response):
        self.response = response

    def post(self, url: str, json: dict):
        return self.response



def test_live_data_provider_integration_uses_same_internal_candle_model_as_golden() -> None:
    scenario = valid_trend_long_scenario()
    response = [
        {
            "t": int(candle.timestamp.replace(tzinfo=timezone.utc).timestamp() * 1000),
            "o": str(candle.open),
            "h": str(candle.high),
            "l": str(candle.low),
            "c": str(candle.close),
        }
        for candle in scenario.candles
    ]
    provider = HyperliquidHistoricalProvider(
        config=HyperliquidConfig(coin="BTC", interval="1h", lookback_bars=len(response)),
        http_client=FakeHyperliquidHttpClient(response),
    )

    batch = provider.fetch_candles()
    result = run_strategy_cycle(
        candles=batch.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert len(batch.candles) == len(scenario.candles)
    assert batch.source_name == "hyperliquid_historical"
    assert batch.candles[0].timestamp == scenario.candles[0].timestamp
    assert batch.candles[-1].close == scenario.candles[-1].close
    assert result.decision.action.value == scenario.expected_decision_action
    assert result.order is not None

from __future__ import annotations

import pytest

from config.strategy_config import StrategyConfig, build_strategy_config
from tests.fixtures.strategy_scenarios import make_config


def test_build_strategy_config_uses_live_defaults() -> None:
    assert build_strategy_config() == StrategyConfig()


def test_build_strategy_config_applies_runtime_overrides_without_losing_defaults() -> None:
    config = build_strategy_config(buy_spread=1.5)

    assert config.buy_spread == 1.5
    assert config.bollinger_period == StrategyConfig().bollinger_period
    assert config.macd_slow_period == StrategyConfig().macd_slow_period


def test_golden_make_config_allows_only_targeted_non_indicator_overrides() -> None:
    config = make_config(outside_band_sweet_spot=0.2)

    assert config.outside_band_sweet_spot == 0.2
    assert config.bollinger_period == StrategyConfig().bollinger_period


def test_golden_make_config_rejects_indicator_structure_overrides() -> None:
    with pytest.raises(ValueError, match="canonical live strategy config"):
        make_config(bollinger_period=3)

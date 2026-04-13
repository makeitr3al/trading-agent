from __future__ import annotations

import pytest

from config.strategy_config import StrategyConfig, build_strategy_config, min_strategy_candle_count
from tests.fixtures.strategy_scenarios import make_config


def test_build_strategy_config_uses_live_defaults() -> None:
    assert build_strategy_config() == StrategyConfig()


def test_min_strategy_candle_count_matches_default_indicator_windows() -> None:
    assert min_strategy_candle_count(StrategyConfig()) == max(
        StrategyConfig().bollinger_period,
        StrategyConfig().macd_slow_period,
    )


def test_build_strategy_config_applies_runtime_overrides_without_losing_defaults() -> None:
    config = build_strategy_config(buy_spread=1.5)

    assert config.buy_spread == 1.5
    assert config.bollinger_period == StrategyConfig().bollinger_period
    assert config.macd_slow_period == StrategyConfig().macd_slow_period


def test_golden_make_config_allows_only_targeted_non_indicator_overrides() -> None:
    config = make_config(outside_band_sweet_spot_pct=0.2)

    assert config.outside_band_sweet_spot_pct == 0.2
    assert config.bollinger_period == StrategyConfig().bollinger_period


def test_golden_make_config_rejects_indicator_structure_overrides() -> None:
    with pytest.raises(ValueError, match="canonical live strategy config"):
        make_config(bollinger_period=3)


# ---------------------------------------------------------------------------
# Constraint validation
# ---------------------------------------------------------------------------


def test_bollinger_period_must_be_positive() -> None:
    with pytest.raises(ValueError, match="bollinger_period must be > 0"):
        StrategyConfig(bollinger_period=0)


def test_bollinger_std_dev_must_be_positive() -> None:
    with pytest.raises(ValueError, match="bollinger_std_dev must be > 0"):
        StrategyConfig(bollinger_std_dev=-1.0)


def test_macd_fast_must_be_less_than_slow() -> None:
    with pytest.raises(ValueError, match="macd_fast_period must be < macd_slow_period"):
        StrategyConfig(macd_fast_period=26, macd_slow_period=12)


def test_macd_fast_equal_slow_rejected() -> None:
    with pytest.raises(ValueError, match="macd_fast_period must be < macd_slow_period"):
        StrategyConfig(macd_fast_period=12, macd_slow_period=12)


def test_min_bandwidth_ratio_out_of_range() -> None:
    with pytest.raises(ValueError, match="min_bandwidth_ratio must be in"):
        StrategyConfig(min_bandwidth_ratio=1.5)


def test_risk_per_trade_pct_zero_rejected() -> None:
    with pytest.raises(ValueError, match="risk_per_trade_pct must be in"):
        StrategyConfig(risk_per_trade_pct=0.0)


def test_risk_per_trade_pct_above_one_rejected() -> None:
    with pytest.raises(ValueError, match="risk_per_trade_pct must be in"):
        StrategyConfig(risk_per_trade_pct=1.5)


def test_macd_signal_period_must_be_positive() -> None:
    with pytest.raises(ValueError, match="macd_signal_period must be > 0"):
        StrategyConfig(macd_signal_period=0)


def test_valid_config_passes_validation() -> None:
    config = StrategyConfig()
    assert config.bollinger_period == 12
    assert config.macd_fast_period < config.macd_slow_period

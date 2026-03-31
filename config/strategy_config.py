from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


class StrategyConfig(BaseModel):
    bollinger_period: int = 12
    bollinger_std_dev: float = 2.0
    macd_fast_period: int = 12
    macd_slow_period: int = 26
    macd_signal_period: int = 9
    inside_buffer_pct: float = 0.20
    outside_buffer_pct: float = 0.20
    min_bandwidth_avg_period: int = 30
    min_bandwidth_ratio: float = 0.70
    max_bars_since_regime_start_for_trend_signal: int = 6
    trend_tp_rr: float = 2.0
    break_even_rr: float = 1.0
    risk_per_trade_pct: float = 0.01
    buy_spread: float = 0.0
    outside_band_sweet_spot: float = 0.0
    trading_times: list[str] = ["07:00"]

    @model_validator(mode="after")
    def _validate_constraints(self) -> StrategyConfig:
        if self.bollinger_period <= 0:
            raise ValueError("bollinger_period must be > 0")
        if self.bollinger_std_dev <= 0:
            raise ValueError("bollinger_std_dev must be > 0")
        if self.macd_fast_period <= 0:
            raise ValueError("macd_fast_period must be > 0")
        if self.macd_slow_period <= 0:
            raise ValueError("macd_slow_period must be > 0")
        if self.macd_signal_period <= 0:
            raise ValueError("macd_signal_period must be > 0")
        if self.macd_fast_period >= self.macd_slow_period:
            raise ValueError("macd_fast_period must be < macd_slow_period")
        if not (0.0 <= self.min_bandwidth_ratio <= 1.0):
            raise ValueError("min_bandwidth_ratio must be in [0, 1]")
        if not (0.0 < self.risk_per_trade_pct <= 1.0):
            raise ValueError("risk_per_trade_pct must be in (0, 1]")
        return self


def build_strategy_config(**overrides: Any) -> StrategyConfig:
    base = StrategyConfig()
    if not overrides:
        return base
    return StrategyConfig(**{**base.model_dump(), **overrides})

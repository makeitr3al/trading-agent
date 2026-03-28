from pydantic import BaseModel


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

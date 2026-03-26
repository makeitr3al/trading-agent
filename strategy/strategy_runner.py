import pandas as pd

from config.strategy_config import StrategyConfig
from indicators.bollinger import compute_bollinger_bands
from indicators.macd import compute_macd
from models.candle import Candle
from models.runner_result import StrategyRunResult
from models.trade import Trade
from strategy.countertrend_signal_detector import detect_countertrend_signal
from strategy.decision_engine import decide_next_action
from strategy.order_manager import build_order_from_decision
from strategy.regime_detector import build_regime_states
from strategy.trade_manager import update_active_trade
from strategy.trend_signal_detector import detect_trend_signal

# TODO: Later manage pending orders across multiple strategy cycles.
# TODO: Later add actual fill handling.
# TODO: Later add market close handling for aggressive reversal.
# TODO: Later add file-based logging.


def run_strategy_cycle(
    candles: list[Candle],
    config: StrategyConfig,
    account_balance: float,
    active_trade: Trade | None = None,
) -> StrategyRunResult:
    min_required_candles = max(config.bollinger_period, config.macd_slow_period)
    if len(candles) < min_required_candles:
        raise ValueError(
            f"At least {min_required_candles} candles are required to run the strategy cycle."
        )

    closes = pd.Series([candle.close for candle in candles], dtype=float)
    bollinger_df = compute_bollinger_bands(
        closes=closes,
        period=config.bollinger_period,
        std_dev=config.bollinger_std_dev,
    )
    macd_df = compute_macd(
        closes=closes,
        fast_period=config.macd_fast_period,
        slow_period=config.macd_slow_period,
        signal_period=config.macd_signal_period,
    )
    regime_states = build_regime_states(macd_df)
    trend_signal = detect_trend_signal(
        candles=candles,
        bollinger_df=bollinger_df,
        regime_states=regime_states,
        config=config,
    )
    countertrend_signal = detect_countertrend_signal(
        candles=candles,
        bollinger_df=bollinger_df,
        regime_states=regime_states,
        config=config,
    )
    decision = decide_next_action(
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        active_trade=active_trade,
    )
    current_price = float(closes.iloc[-1])
    order = build_order_from_decision(
        decision=decision,
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        current_price=current_price,
        account_balance=account_balance,
        risk_per_trade_pct=config.risk_per_trade_pct,
    )
    updated_trade = None
    if active_trade is not None:
        updated_trade = update_active_trade(
            active_trade=active_trade,
            latest_bb_middle=float(bollinger_df.iloc[-1]["bb_middle"]),
            latest_close=current_price,
        )

    return StrategyRunResult(
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        decision=decision,
        order=order,
        updated_trade=updated_trade,
    )

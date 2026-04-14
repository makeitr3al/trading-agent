import math

from datetime import datetime, timedelta, timezone
from statistics import median

import pandas as pd

from config.strategy_config import StrategyConfig, min_strategy_candle_count
from indicators.bollinger import compute_bollinger_bands
from indicators.macd import compute_macd
from models.candle import Candle
from models.decision import DecisionAction
from models.regime import RegimeType
from models.runner_result import StrategyRunResult
from models.trade import Trade, TradeDirection, TradeType
from strategy.countertrend_signal_detector import detect_countertrend_signal
from strategy.decision_engine import decide_next_action
from strategy.order_manager import build_order_from_decision
from strategy.regime_detector import build_regime_states
from strategy.signal_rules import (
    is_close_deep_outside_bands,
    is_close_in_outer_band_sweet_spot,
)
from strategy.trade_manager import (
    tighten_trend_stop_to_last_close,
    tighten_trend_stop_to_signal_bar_close,
    update_active_trade,
)
from strategy.trend_signal_detector import detect_trend_signal

# TODO: Later manage pending orders across multiple strategy cycles.
# TODO: Later add actual fill handling.
# TODO: Later add market close handling for aggressive reversal.
# TODO: Later add file-based logging.


def _trend_exit_regime_from_trade(active_trade: Trade) -> RegimeType:
    return RegimeType.BULLISH if active_trade.direction == TradeDirection.LONG else RegimeType.BEARISH


def _should_trigger_active_trend_exit(
    active_trade: Trade | None,
    latest_close: float,
    latest_bb_upper: float,
    latest_bb_middle: float,
    latest_bb_lower: float,
    config: StrategyConfig,
) -> bool:
    if active_trade is None or active_trade.trade_type != TradeType.TREND:
        return False

    if any(
        math.isnan(value)
        for value in (latest_close, latest_bb_upper, latest_bb_middle, latest_bb_lower)
    ):
        return False

    trade_regime = _trend_exit_regime_from_trade(active_trade)
    return is_close_deep_outside_bands(
        close=latest_close,
        regime=trade_regime,
        bb_upper=latest_bb_upper,
        bb_middle=latest_bb_middle,
        bb_lower=latest_bb_lower,
        outside_buffer_pct=config.outside_buffer_pct,
    ) or is_close_in_outer_band_sweet_spot(
        close=latest_close,
        regime=trade_regime,
        bb_upper=latest_bb_upper,
        bb_middle=latest_bb_middle,
        bb_lower=latest_bb_lower,
        sweet_spot_pct=config.outside_band_sweet_spot_pct,
    )


def _should_close_active_countertrend_trade(
    active_trade: Trade | None,
    latest_high: float,
    latest_low: float,
    latest_bb_middle: float,
) -> bool:
    if active_trade is None or active_trade.trade_type != TradeType.COUNTERTREND:
        return False

    if any(math.isnan(value) for value in (latest_high, latest_low, latest_bb_middle)):
        return False

    if active_trade.direction == TradeDirection.LONG:
        return latest_high >= latest_bb_middle

    return latest_low <= latest_bb_middle


def _countertrend_management_bb_middle(bollinger_df: pd.DataFrame) -> float:
    if len(bollinger_df) >= 2 and not math.isnan(float(bollinger_df.iloc[-2]["bb_middle"])):
        return float(bollinger_df.iloc[-2]["bb_middle"])
    return float(bollinger_df.iloc[-1]["bb_middle"])


def _infer_candle_interval(candles: list[Candle], *, lookback: int = 20) -> timedelta | None:
    if len(candles) < 2:
        return None
    deltas_s: list[float] = []
    start = max(1, len(candles) - lookback)
    for i in range(start, len(candles)):
        dt = candles[i].timestamp - candles[i - 1].timestamp
        if dt.total_seconds() > 0:
            deltas_s.append(dt.total_seconds())
    if not deltas_s:
        return None
    return timedelta(seconds=float(median(deltas_s)))


def _now_like_candles(candles: list[Candle], now: datetime) -> datetime:
    """Return ``now`` normalized to match candle tz-awareness.

    Live providers emit UTC-aware timestamps. Some unit tests use naive datetimes; we
    normalize comparisons to avoid offset-naive/aware TypeErrors.
    """
    if not candles:
        return now
    candle_ts = candles[-1].timestamp
    if candle_ts.tzinfo is None:
        # Compare naive with naive.
        return now.replace(tzinfo=None)
    # Compare aware with aware (default to UTC when caller passed naive).
    return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)


def _is_last_candle_closed(candles: list[Candle], *, now: datetime) -> bool:
    interval = _infer_candle_interval(candles)
    if interval is None:
        return True
    normalized_now = _now_like_candles(candles, now)
    return normalized_now >= (candles[-1].timestamp + interval)


def _signal_candles_only(candles: list[Candle], *, now: datetime) -> list[Candle]:
    if len(candles) < 2:
        return candles
    if _is_last_candle_closed(candles, now=now):
        return candles
    return candles[:-1]


def run_strategy_cycle(
    candles: list[Candle],
    config: StrategyConfig,
    account_balance: float,
    active_trade: Trade | None = None,
    now: datetime | None = None,
) -> StrategyRunResult:
    min_required_candles = min_strategy_candle_count(config)
    if len(candles) < min_required_candles:
        raise ValueError(
            f"At least {min_required_candles} candles are required to run the strategy cycle."
        )

    effective_now = now or datetime.now(timezone.utc)
    signal_candles = _signal_candles_only(candles, now=effective_now)
    if len(signal_candles) < min_required_candles:
        signal_candles = candles

    closes_all = pd.Series([candle.close for candle in candles], dtype=float)
    bollinger_all = compute_bollinger_bands(
        closes=closes_all,
        period=config.bollinger_period,
        std_dev=config.bollinger_std_dev,
    )
    macd_all = compute_macd(
        closes=closes_all,
        fast_period=config.macd_fast_period,
        slow_period=config.macd_slow_period,
        signal_period=config.macd_signal_period,
    )

    closes_sig = pd.Series([candle.close for candle in signal_candles], dtype=float)
    bollinger_sig = compute_bollinger_bands(
        closes=closes_sig,
        period=config.bollinger_period,
        std_dev=config.bollinger_std_dev,
    )
    macd_sig = compute_macd(
        closes=closes_sig,
        fast_period=config.macd_fast_period,
        slow_period=config.macd_slow_period,
        signal_period=config.macd_signal_period,
    )
    regime_sig = build_regime_states(macd_sig)

    trend_signal = detect_trend_signal(
        candles=signal_candles,
        bollinger_df=bollinger_sig,
        regime_states=regime_sig,
        config=config,
    )
    countertrend_signal = detect_countertrend_signal(
        candles=signal_candles,
        bollinger_df=bollinger_sig,
        regime_states=regime_sig,
        config=config,
    )

    current_price = float(closes_all.iloc[-1])
    decision_price = float(closes_sig.iloc[-1])
    latest_candle = candles[-1]
    latest_bollinger = bollinger_all.iloc[-1]
    trend_exit_triggered = _should_trigger_active_trend_exit(
        active_trade=active_trade,
        latest_close=current_price,
        latest_bb_upper=float(latest_bollinger["bb_upper"]),
        latest_bb_middle=float(latest_bollinger["bb_middle"]),
        latest_bb_lower=float(latest_bollinger["bb_lower"]),
        config=config,
    )
    countertrend_close_triggered = _should_close_active_countertrend_trade(
        active_trade=active_trade,
        latest_high=latest_candle.high,
        latest_low=latest_candle.low,
        latest_bb_middle=float(latest_bollinger["bb_middle"]),
    )
    decision = decide_next_action(
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        active_trade=active_trade,
        current_price=decision_price,
        trend_exit_triggered=trend_exit_triggered,
        countertrend_close_triggered=countertrend_close_triggered,
    )
    order = build_order_from_decision(
        decision=decision,
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        current_price=decision_price,
        account_balance=account_balance,
        risk_per_trade_pct=config.risk_per_trade_pct,
        buy_spread=config.buy_spread,
    )
    updated_trade = None
    close_active_trade = False
    if active_trade is not None:
        if decision.action == DecisionAction.ADJUST_TREND_STOP_TO_SIGNAL_BAR_CLOSE:
            if countertrend_signal is not None and countertrend_signal.signal_bar_close is not None:
                updated_trade = tighten_trend_stop_to_signal_bar_close(
                    active_trade, float(countertrend_signal.signal_bar_close)
                )
            else:
                updated_trade = tighten_trend_stop_to_last_close(active_trade, current_price)
        elif decision.action == DecisionAction.ADJUST_TREND_STOP_TO_LAST_CLOSE:
            updated_trade = tighten_trend_stop_to_last_close(active_trade, current_price)
        elif decision.action in (
            DecisionAction.CLOSE_TREND_TRADE,
            DecisionAction.CLOSE_COUNTERTREND_TRADE,
        ):
            close_active_trade = True
        else:
            management_bb_middle = (
                _countertrend_management_bb_middle(bollinger_all)
                if active_trade.trade_type == TradeType.COUNTERTREND
                else float(bollinger_all.iloc[-1]["bb_middle"])
            )
            updated_trade = update_active_trade(
                active_trade=active_trade,
                latest_bb_middle=management_bb_middle,
                latest_close=current_price,
                buy_spread=config.buy_spread,
            )

    return StrategyRunResult(
        trend_signal=trend_signal,
        countertrend_signal=countertrend_signal,
        decision=decision,
        order=order,
        updated_trade=updated_trade,
        close_active_trade=close_active_trade,
    )

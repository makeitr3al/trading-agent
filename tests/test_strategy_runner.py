from datetime import datetime, timedelta
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.strategy_config import StrategyConfig
from models.candle import Candle
from models.runner_result import StrategyRunResult
from models.signal import SignalState, SignalType
from models.trade import Trade, TradeDirection, TradeType
from strategy.strategy_runner import run_strategy_cycle


def _make_candles(closes: list[float]) -> list[Candle]:
    base_time = datetime(2026, 1, 1, 0, 0, 0)
    return [
        Candle(
            timestamp=base_time + timedelta(hours=index),
            open=float(close - 0.0010),
            high=float(close + 0.0015),
            low=float(close - 0.0015),
            close=float(close),
        )
        for index, close in enumerate(closes)
    ]


def _make_default_candles() -> list[Candle]:
    closes = [
        100.0,
        100.5,
        101.0,
        100.8,
        101.4,
        102.0,
        101.7,
        102.5,
        103.1,
        102.9,
        103.4,
        104.0,
        103.8,
        104.6,
        105.1,
        104.9,
        105.5,
        106.0,
        105.7,
        106.4,
        107.0,
        106.8,
        107.3,
        108.0,
        107.6,
        108.4,
        109.0,
        108.7,
        109.5,
        110.0,
        109.8,
        110.4,
        111.0,
        110.6,
        111.3,
        112.0,
        111.8,
        112.4,
        113.0,
        112.7,
    ]
    return _make_candles(closes)


def test_run_strategy_cycle_raises_value_error_when_too_few_candles_are_provided() -> None:
    config = StrategyConfig()
    candles = _make_candles([100.0] * 10)

    with pytest.raises(ValueError, match="At least 26 candles are required"):
        run_strategy_cycle(
            candles=candles,
            config=config,
            account_balance=10000.0,
            active_trade=None,
        )


def test_run_strategy_cycle_returns_strategy_run_result_with_no_active_trade() -> None:
    config = StrategyConfig()
    candles = _make_default_candles()

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=10000.0,
        active_trade=None,
    )

    assert isinstance(result, StrategyRunResult)
    assert result.trend_signal is not None
    assert result.countertrend_signal is not None
    assert result.decision is not None
    assert result.updated_trade is None


def test_run_strategy_cycle_updates_active_trend_trade_when_active_trade_is_provided() -> None:
    config = StrategyConfig()
    candles = _make_default_candles()
    active_trade = Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=10000.0,
        active_trade=active_trade,
    )

    assert result.updated_trade is not None
    assert result.updated_trade.trade_type == TradeType.TREND


def test_run_strategy_cycle_updates_active_countertrend_trade_when_active_trade_is_provided() -> None:
    config = StrategyConfig()
    candles = _make_default_candles()
    active_trade = Trade(
        trade_type=TradeType.COUNTERTREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=110.0,
        take_profit=95.0,
    )

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=10000.0,
        active_trade=active_trade,
    )

    assert result.updated_trade is not None
    assert result.updated_trade.trade_type == TradeType.COUNTERTREND


def test_run_strategy_cycle_can_return_no_order_when_no_valid_signal_exists() -> None:
    config = StrategyConfig()
    candles = _make_default_candles()

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=10000.0,
        active_trade=None,
    )

    assert result.order is None
    assert result.decision.action.value == "NO_ACTION"


def test_run_strategy_cycle_can_return_an_order_when_a_valid_signal_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    config = StrategyConfig()
    candles = _make_default_candles()
    valid_trend_signal = SignalState(
        signal_type=SignalType.TREND_LONG,
        is_valid=True,
        reason="trend signal detected",
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
    )

    monkeypatch.setattr(
        "strategy.strategy_runner.detect_trend_signal",
        lambda candles, bollinger_df, regime_states, config: valid_trend_signal,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner.detect_countertrend_signal",
        lambda candles, bollinger_df, regime_states, config: None,
    )

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=10000.0,
        active_trade=None,
    )

    assert result.order is not None
    assert result.order.entry == 110.0
    assert result.order.stop_loss == 100.0
    assert result.order.take_profit == 130.0
    assert result.order.position_size == pytest.approx(10.0)

from datetime import datetime, timedelta
from pathlib import Path
import sys

import pandas as pd
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


def test_run_strategy_cycle_can_exit_active_trend_on_sweet_spot_without_valid_countertrend_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = StrategyConfig()
    candles = _make_default_candles()
    invalid_countertrend_signal = SignalState(
        signal_type=SignalType.COUNTERTREND_SHORT,
        is_valid=False,
        reason="close not outside bands",
    )
    active_trade = Trade(
        trade_type=TradeType.TREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )

    monkeypatch.setattr(
        "strategy.strategy_runner.detect_trend_signal",
        lambda candles, bollinger_df, regime_states, config: None,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner.detect_countertrend_signal",
        lambda candles, bollinger_df, regime_states, config: invalid_countertrend_signal,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner._should_trigger_active_trend_exit",
        lambda active_trade, latest_close, latest_bb_upper, latest_bb_middle, latest_bb_lower, config: True,
    )

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=10000.0,
        active_trade=active_trade,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is False
    assert result.decision.action.value == "ADJUST_TREND_STOP_TO_LAST_CLOSE"
    assert result.decision.selected_signal_type is None
    assert result.updated_trade is not None
    assert result.updated_trade.stop_loss == pytest.approx(candles[-1].close)
    assert result.close_active_trade is False


def test_run_strategy_cycle_closes_active_countertrend_trade_when_middle_band_is_touched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = StrategyConfig(buy_spread=1.5)
    candles = _make_default_candles()
    active_trade = Trade(
        trade_type=TradeType.COUNTERTREND,
        direction=TradeDirection.LONG,
        entry=100.0,
        stop_loss=90.0,
        take_profit=101.5,
    )

    monkeypatch.setattr(
        "strategy.strategy_runner.detect_trend_signal",
        lambda candles, bollinger_df, regime_states, config: None,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner.detect_countertrend_signal",
        lambda candles, bollinger_df, regime_states, config: None,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner._should_close_active_countertrend_trade",
        lambda active_trade, latest_high, latest_low, latest_bb_middle: True,
    )

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=10000.0,
        active_trade=active_trade,
    )

    assert result.decision.action.value == "CLOSE_COUNTERTREND_TRADE"
    assert result.updated_trade is None
    assert result.close_active_trade is True


def test_run_strategy_cycle_uses_last_closed_middle_band_for_active_countertrend_trade_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = StrategyConfig()
    candles = _make_default_candles()
    active_trade = Trade(
        trade_type=TradeType.COUNTERTREND,
        direction=TradeDirection.SHORT,
        entry=100.0,
        stop_loss=110.0,
        take_profit=95.0,
    )
    captured: dict[str, float] = {}

    bollinger_df = pd.DataFrame(
        {
            "bb_upper": [110.0] * len(candles),
            "bb_middle": [100.0] * (len(candles) - 2) + [97.0, 101.0],
            "bb_lower": [90.0] * len(candles),
        }
    )

    monkeypatch.setattr(
        "strategy.strategy_runner.compute_bollinger_bands",
        lambda closes, period, std_dev: bollinger_df,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner.detect_trend_signal",
        lambda candles, bollinger_df, regime_states, config: None,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner.detect_countertrend_signal",
        lambda candles, bollinger_df, regime_states, config: None,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner.update_active_trade",
        lambda active_trade, latest_bb_middle, latest_close, buy_spread=0.0: (
            captured.update({"latest_bb_middle": latest_bb_middle})
            or active_trade.copy(update={"take_profit": latest_bb_middle})
        ),
    )

    result = run_strategy_cycle(
        candles=candles,
        config=config,
        account_balance=10000.0,
        active_trade=active_trade,
    )

    assert captured["latest_bb_middle"] == pytest.approx(97.0)
    assert result.updated_trade is not None
    assert result.updated_trade.take_profit == pytest.approx(97.0)

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from indicators.bollinger import compute_bollinger_bands
from models.agent_state import AgentState
from models.decision import DecisionAction
from models.order import OrderType
from strategy.engine import run_agent_cycle, run_strategy_cycle
from strategy_scenarios import (
    break_even_should_activate_scenario,
    countertrend_should_override_active_trend_trade_scenario,
    countertrend_tp_should_update_scenario,
    invalid_trend_candle_not_in_direction_scenario,
    invalid_trend_regime_too_old_scenario,
    no_countertrend_not_first_regime_bar_scenario,
    regime_change_should_reset_consumed_flag_scenario,
    trend_order_should_be_prepared_scenario,
    trend_signal_consumed_duplicate_order_scenario,
    valid_countertrend_long_first_bearish_regime_scenario,
    valid_countertrend_short_first_bullish_regime_scenario,
    valid_trend_long_scenario,
)


def _patch_strategy_signals(monkeypatch: pytest.MonkeyPatch, trend_signal, countertrend_signal) -> None:
    monkeypatch.setattr(
        "strategy.strategy_runner.detect_trend_signal",
        lambda candles, bollinger_df, regime_states, config: trend_signal,
    )
    monkeypatch.setattr(
        "strategy.strategy_runner.detect_countertrend_signal",
        lambda candles, bollinger_df, regime_states, config: countertrend_signal,
    )


def test_valid_trend_long_scenario_prepares_trend_order(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = valid_trend_long_scenario()
    _patch_strategy_signals(monkeypatch, scenario.trend_signal, scenario.countertrend_signal)

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is True
    assert result.trend_signal.signal_type.value == "TREND_LONG"
    assert result.decision.action == DecisionAction.PREPARE_TREND_ORDER
    assert result.order is not None
    assert result.order.order_type == OrderType.BUY_STOP
    assert result.order.signal_source == "trend_long"
    assert result.order.position_size == pytest.approx(20.0)


def test_invalid_trend_regime_too_old_scenario_produces_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = invalid_trend_regime_too_old_scenario()
    _patch_strategy_signals(monkeypatch, scenario.trend_signal, scenario.countertrend_signal)

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is False
    assert result.trend_signal.reason == "regime too old"
    assert result.decision.action == DecisionAction.NO_ACTION
    assert result.order is None


def test_invalid_trend_candle_not_in_direction_scenario_produces_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = invalid_trend_candle_not_in_direction_scenario()
    _patch_strategy_signals(monkeypatch, scenario.trend_signal, scenario.countertrend_signal)

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is False
    assert result.trend_signal.reason == "candle not in trend direction"
    assert result.decision.action == DecisionAction.NO_ACTION
    assert result.order is None


def test_valid_countertrend_short_on_first_bullish_regime_bar_prepares_order(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = valid_countertrend_short_first_bullish_regime_scenario()
    _patch_strategy_signals(monkeypatch, scenario.trend_signal, scenario.countertrend_signal)

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is True
    assert result.countertrend_signal.signal_type.value == "COUNTERTREND_SHORT"
    assert result.decision.action == DecisionAction.PREPARE_COUNTERTREND_ORDER
    assert result.order is not None
    assert result.order.order_type == OrderType.SELL_LIMIT
    assert result.order.signal_source == "countertrend_short"


def test_valid_countertrend_long_on_first_bearish_regime_bar_prepares_order(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = valid_countertrend_long_first_bearish_regime_scenario()
    _patch_strategy_signals(monkeypatch, scenario.trend_signal, scenario.countertrend_signal)

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is True
    assert result.countertrend_signal.signal_type.value == "COUNTERTREND_LONG"
    assert result.decision.action == DecisionAction.PREPARE_COUNTERTREND_ORDER
    assert result.order is not None
    assert result.order.order_type == OrderType.BUY_LIMIT
    assert result.order.signal_source == "countertrend_long"


def test_no_countertrend_when_not_first_regime_bar_results_in_no_action(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = no_countertrend_not_first_regime_bar_scenario()
    _patch_strategy_signals(monkeypatch, scenario.trend_signal, scenario.countertrend_signal)

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is False
    assert result.countertrend_signal.reason == "not first regime bar"
    assert result.decision.action == DecisionAction.NO_ACTION
    assert result.order is None


def test_trend_order_should_be_prepared_and_stored_in_agent_state(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = trend_order_should_be_prepared_scenario()
    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: scenario.strategy_result,
    )

    result, new_state = run_agent_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        state=scenario.state or AgentState(),
    )

    assert result.decision.action == DecisionAction.PREPARE_TREND_ORDER
    assert new_state.pending_order is not None
    assert new_state.pending_order.signal_source == "trend_long"
    assert new_state.trend_signal_consumed_in_regime is True


def test_countertrend_overrides_active_trend_trade(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = countertrend_should_override_active_trend_trade_scenario()
    _patch_strategy_signals(monkeypatch, scenario.trend_signal, scenario.countertrend_signal)

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.decision.action == DecisionAction.CLOSE_TREND_AND_PREPARE_COUNTERTREND
    assert result.decision.reason == "valid countertrend overrides active trend trade"
    assert result.order is not None
    assert result.order.signal_source == "countertrend_short"


def test_break_even_should_activate_for_active_trend_trade() -> None:
    scenario = break_even_should_activate_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.updated_trade is not None
    assert result.updated_trade.stop_loss == pytest.approx(scenario.active_trade.entry)
    assert result.updated_trade.break_even_activated is True


def test_countertrend_tp_should_be_updated_while_sl_stays_fixed() -> None:
    scenario = countertrend_tp_should_update_scenario()
    closes = [candle.close for candle in scenario.candles]
    expected_bb_middle = float(
        compute_bollinger_bands(
            closes=__import__("pandas").Series(closes, dtype=float),
            period=scenario.config.bollinger_period,
            std_dev=scenario.config.bollinger_std_dev,
        ).iloc[-1]["bb_middle"]
    )

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.updated_trade is not None
    assert result.updated_trade.stop_loss == pytest.approx(scenario.active_trade.stop_loss)
    assert result.updated_trade.take_profit == pytest.approx(expected_bb_middle)
    assert result.updated_trade.break_even_activated is False


@pytest.mark.xfail(
    reason="Current agent cycle stores trend_signal_consumed_in_regime but does not yet block duplicate trend orders within the same regime.",
    strict=False,
)
def test_trend_signal_consumed_in_regime_should_block_duplicate_trend_order(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = trend_signal_consumed_duplicate_order_scenario()
    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: scenario.strategy_result,
    )

    _, new_state = run_agent_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        state=scenario.state or AgentState(),
    )

    assert new_state.pending_order is None
    assert new_state.last_decision_action == DecisionAction.NO_ACTION.value


def test_regime_change_should_reset_consumed_trend_signal_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    scenario = regime_change_should_reset_consumed_flag_scenario()
    monkeypatch.setattr(
        "strategy.agent_cycle.run_strategy_cycle",
        lambda candles, config, account_balance, active_trade: scenario.strategy_result,
    )

    _, new_state = run_agent_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        state=scenario.state or AgentState(),
    )

    assert new_state.last_regime == "bullish"
    assert new_state.trend_signal_consumed_in_regime is False

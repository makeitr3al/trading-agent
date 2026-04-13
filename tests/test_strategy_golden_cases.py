from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from strategy.engine import run_agent_cycle, run_strategy_cycle
from strategy_scenarios import (
    break_even_should_activate_scenario,
    countertrend_adjusts_short_trend_stop_at_signal_bar_close_scenario,
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
    sweet_spot_should_manage_active_trend_without_countertrend_signal_scenario,
    valid_trend_long_scenario,
)


def test_valid_trend_long_scenario_prepares_trend_order() -> None:
    scenario = valid_trend_long_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is scenario.expected_trend_signal_valid
    assert result.trend_signal.signal_type.value == scenario.expected_trend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present


def test_invalid_trend_regime_too_old_scenario_produces_no_action() -> None:
    scenario = invalid_trend_regime_too_old_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is scenario.expected_trend_signal_valid
    assert result.trend_signal.reason == "regime too old"
    assert result.trend_signal.signal_type.value == scenario.expected_trend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present


def test_invalid_trend_candle_not_in_direction_scenario_produces_no_action() -> None:
    scenario = invalid_trend_candle_not_in_direction_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is scenario.expected_trend_signal_valid
    assert result.trend_signal.reason == "candle not in trend direction"
    assert result.trend_signal.signal_type.value == scenario.expected_trend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present


def test_valid_countertrend_short_on_first_bullish_regime_bar() -> None:
    scenario = valid_countertrend_short_first_bullish_regime_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is scenario.expected_countertrend_signal_valid
    assert result.countertrend_signal.signal_type.value == scenario.expected_countertrend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present


def test_sweet_spot_manages_active_trend_without_countertrend_signal() -> None:
    scenario = sweet_spot_should_manage_active_trend_without_countertrend_signal_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is scenario.expected_countertrend_signal_valid
    assert result.countertrend_signal.signal_type.value == scenario.expected_countertrend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present
    assert result.close_active_trade is scenario.expected_close_active_trade
    assert result.updated_trade is not None
    assert result.updated_trade.stop_loss == pytest.approx(scenario.expected_updated_stop_loss)


def test_valid_countertrend_long_on_first_bearish_regime_bar() -> None:
    scenario = valid_countertrend_long_first_bearish_regime_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is scenario.expected_countertrend_signal_valid
    assert result.countertrend_signal.signal_type.value == scenario.expected_countertrend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present


def test_no_countertrend_when_not_first_regime_bar() -> None:
    scenario = no_countertrend_not_first_regime_bar_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is scenario.expected_countertrend_signal_valid
    assert result.countertrend_signal.reason == "not first regime bar"
    assert result.countertrend_signal.signal_type.value == scenario.expected_countertrend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present


def test_trend_order_should_be_prepared() -> None:
    scenario = trend_order_should_be_prepared_scenario()

    result, new_state = run_agent_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        state=scenario.agent_state,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is scenario.expected_trend_signal_valid
    assert result.trend_signal.signal_type.value == scenario.expected_trend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (new_state.pending_order is not None) is scenario.expected_order_present
    assert new_state.trend_signal_consumed_in_regime is scenario.expected_consumed_flag


def test_countertrend_can_lock_active_trend_stop_to_last_close() -> None:
    scenario = countertrend_should_override_active_trend_trade_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is scenario.expected_countertrend_signal_valid
    assert result.countertrend_signal.signal_type.value == scenario.expected_countertrend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present
    assert result.close_active_trade is scenario.expected_close_active_trade
    assert result.updated_trade is not None
    assert result.updated_trade.stop_loss == pytest.approx(scenario.expected_updated_stop_loss)


def test_countertrend_adjusts_short_trend_stop_to_signal_bar_close() -> None:
    scenario = countertrend_adjusts_short_trend_stop_at_signal_bar_close_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.countertrend_signal is not None
    assert result.countertrend_signal.is_valid is scenario.expected_countertrend_signal_valid
    assert result.countertrend_signal.signal_type.value == scenario.expected_countertrend_signal_type
    assert result.decision.action.value == scenario.expected_decision_action
    assert (result.order is not None) is scenario.expected_order_present
    assert result.close_active_trade is scenario.expected_close_active_trade
    assert result.updated_trade is not None
    assert result.updated_trade.stop_loss == pytest.approx(scenario.expected_updated_stop_loss)


def test_break_even_activates_for_active_trend_trade() -> None:
    scenario = break_even_should_activate_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.updated_trade is not None
    assert result.updated_trade.break_even_activated is scenario.expected_break_even_activated
    assert result.updated_trade.stop_loss == pytest.approx(scenario.active_trade.entry)


def test_countertrend_tp_updates_while_sl_stays_fixed() -> None:
    scenario = countertrend_tp_should_update_scenario()

    result = run_strategy_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )

    assert result.updated_trade is not None
    assert result.updated_trade.break_even_activated is scenario.expected_break_even_activated
    assert result.updated_trade.stop_loss == pytest.approx(scenario.active_trade.stop_loss)
    assert result.updated_trade.take_profit != pytest.approx(scenario.active_trade.take_profit)


def test_trend_signal_consumed_in_regime_blocks_duplicate_trend_order() -> None:
    scenario = trend_signal_consumed_duplicate_order_scenario()

    result, new_state = run_agent_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        state=scenario.agent_state,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is scenario.expected_trend_signal_valid
    assert result.trend_signal.reason == "trend regime consumed"
    assert result.decision.action.value == scenario.expected_decision_action
    assert (new_state.pending_order is not None) is scenario.expected_order_present
    assert new_state.trend_signal_consumed_in_regime is scenario.expected_consumed_flag


def test_regime_change_resets_consumed_trend_signal_flag() -> None:
    scenario = regime_change_should_reset_consumed_flag_scenario()

    result, new_state = run_agent_cycle(
        candles=scenario.candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        state=scenario.agent_state,
    )

    assert result.trend_signal is not None
    assert result.trend_signal.is_valid is scenario.expected_trend_signal_valid
    assert result.decision.action.value == scenario.expected_decision_action
    assert (new_state.pending_order is not None) is scenario.expected_order_present
    assert new_state.trend_signal_consumed_in_regime is scenario.expected_consumed_flag


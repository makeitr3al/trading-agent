from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data.providers.golden_data_provider import _discover_scenario_builders, _load_strategy_scenarios_module
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from indicators.bollinger import compute_bollinger_bands
from indicators.macd import compute_macd
from models.agent_state import AgentState
from models.candle import Candle
from strategy.engine import run_agent_cycle, run_strategy_cycle
from strategy.regime_detector import build_regime_states
from strategy.signal_rules import (
    get_relevant_half_bandwidth,
    has_sufficient_bandwidth,
    is_candle_in_trend_direction,
    is_close_deep_inside_bands,
    is_close_deep_outside_bands,
)
from utils.env_loader import load_hyperliquid_config_from_env


ARTIFACTS_JSON_PATH = PROJECT_ROOT / "artifacts" / "historical_reference_cases.json"
ARTIFACTS_CSV_PATH = PROJECT_ROOT / "artifacts" / "historical_reference_cases.csv"
CSV_NA = "n/a"

# TODO: Later add scenario filters, e.g. by name prefix or tags.
# TODO: Later add richer market-shape diagnostics for close manual review.


@dataclass
class HistoricalReferenceCandidate:
    scenario_name: str
    score: int
    coin: str
    window_size_bars: int
    start_timestamp: str
    end_timestamp: str
    trigger_timestamp: str
    decision_action: str
    selected_signal_type: str | None
    trend_signal_valid: bool | None
    trend_signal_type: str | None
    countertrend_signal_valid: bool | None
    countertrend_signal_type: str | None
    trend_reason: str | None
    countertrend_reason: str | None
    order_present: bool | None
    break_even_activated: bool | None
    consumed_flag: bool | None
    latest_open: float | None
    latest_high: float | None
    latest_low: float | None
    latest_close: float | None
    latest_regime: str | None
    bars_since_regime_start: int | None
    bb_upper: float | None
    bb_middle: float | None
    bb_lower: float | None
    relevant_half_bandwidth: float | None
    average_relevant_half_bandwidth: float | None
    bandwidth_ratio_value: float | None
    bandwidth_ok: bool | None
    close_inside_bands: bool | None
    candle_in_trend_direction: bool | None
    inside_distance_actual: float | None
    inside_distance_required: float | None
    inside_margin: float | None
    outside_distance_actual: float | None
    outside_distance_required: float | None
    outside_margin: float | None
    close_deep_inside_bands: bool | None
    close_deep_outside_bands: bool | None
    expected_decision_action: str | None
    expected_trend_signal_valid: bool | None
    expected_trend_signal_type: str | None
    expected_countertrend_signal_valid: bool | None
    expected_countertrend_signal_type: str | None
    expected_order_present: bool | None
    expected_break_even_activated: bool | None
    expected_consumed_flag: bool | None
    decision_match: bool | None
    trend_signal_valid_match: bool | None
    trend_signal_type_match: bool | None
    countertrend_signal_valid_match: bool | None
    countertrend_signal_type_match: bool | None
    order_present_match: bool | None
    break_even_activated_match: bool | None
    consumed_flag_match: bool | None
    match_comment: str | None = None


def load_all_golden_scenarios() -> list[Any]:
    module = _load_strategy_scenarios_module()
    builders = _discover_scenario_builders(module)
    return [builders[name]() for name in sorted(builders)]


def build_replay_windows(candles: list[Candle], window_size: int) -> list[list[Candle]]:
    if not candles or window_size <= 0 or len(candles) < window_size:
        return []
    return [
        candles[start_index : start_index + window_size]
        for start_index in range(0, len(candles) - window_size + 1)
    ]


def _uses_agent_cycle(scenario: Any) -> bool:
    return scenario.agent_state is not None or scenario.expected_consumed_flag is not None


def _build_initial_agent_state(scenario: Any) -> AgentState:
    if scenario.agent_state is not None:
        if scenario.active_trade is None:
            return scenario.agent_state
        return scenario.agent_state.model_copy(update={"active_trade": scenario.active_trade})
    return AgentState(active_trade=scenario.active_trade)


def _round_or_none(value: float | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _calculate_window_diagnostics(candles: list[Candle], config: Any) -> dict[str, Any]:
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
    latest_candle = candles[-1]
    latest_bollinger = bollinger_df.iloc[-1]
    latest_regime_state = regime_states[-1] if regime_states else None

    if latest_regime_state is None or latest_bollinger[["bb_upper", "bb_middle", "bb_lower"]].isna().any():
        return {
            "latest_open": latest_candle.open,
            "latest_high": latest_candle.high,
            "latest_low": latest_candle.low,
            "latest_close": latest_candle.close,
            "latest_regime": latest_regime_state.regime.value if latest_regime_state is not None else None,
            "bars_since_regime_start": latest_regime_state.bars_since_regime_start if latest_regime_state is not None else None,
            "bb_upper": None,
            "bb_middle": None,
            "bb_lower": None,
            "relevant_half_bandwidth": None,
            "average_relevant_half_bandwidth": None,
            "bandwidth_ratio_value": None,
            "bandwidth_ok": None,
            "close_inside_bands": None,
            "candle_in_trend_direction": None,
            "inside_distance_actual": None,
            "inside_distance_required": None,
            "inside_margin": None,
            "outside_distance_actual": None,
            "outside_distance_required": None,
            "outside_margin": None,
            "close_deep_inside_bands": None,
            "close_deep_outside_bands": None,
        }

    bb_upper = float(latest_bollinger["bb_upper"])
    bb_middle = float(latest_bollinger["bb_middle"])
    bb_lower = float(latest_bollinger["bb_lower"])
    regime = latest_regime_state.regime
    relevant_half_bandwidth = get_relevant_half_bandwidth(
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
    )
    historical_rows = bollinger_df.iloc[max(0, len(candles) - config.min_bandwidth_avg_period) : len(candles)]
    historical_half_bandwidths = [
        get_relevant_half_bandwidth(
            regime=regime,
            bb_upper=float(row.bb_upper),
            bb_middle=float(row.bb_middle),
            bb_lower=float(row.bb_lower),
        )
        for row in historical_rows.itertuples(index=False)
        if not any(pd.isna(value) for value in (row.bb_upper, row.bb_middle, row.bb_lower))
    ]
    average_relevant_half_bandwidth = (
        sum(historical_half_bandwidths) / len(historical_half_bandwidths)
        if historical_half_bandwidths
        else None
    )
    bandwidth_ok = has_sufficient_bandwidth(
        current_half_bandwidth=relevant_half_bandwidth,
        historical_half_bandwidths=historical_half_bandwidths,
        min_bandwidth_ratio=config.min_bandwidth_ratio,
    )
    bandwidth_ratio_value = (
        relevant_half_bandwidth / average_relevant_half_bandwidth
        if average_relevant_half_bandwidth not in (None, 0)
        else None
    )
    close_inside_bands = bb_lower <= latest_candle.close <= bb_upper
    candle_in_trend_direction = is_candle_in_trend_direction(
        candle_open=latest_candle.open,
        candle_close=latest_candle.close,
        regime=regime,
    )
    inside_distance_actual = (
        bb_upper - latest_candle.close
        if regime.value == "bullish"
        else latest_candle.close - bb_lower
        if regime.value == "bearish"
        else None
    )
    inside_distance_required = config.inside_buffer_pct * relevant_half_bandwidth
    inside_margin = inside_distance_actual - inside_distance_required if inside_distance_actual is not None else None
    outside_distance_actual = (
        latest_candle.close - bb_upper
        if regime.value == "bullish"
        else bb_lower - latest_candle.close
        if regime.value == "bearish"
        else None
    )
    outside_distance_required = config.outside_buffer_pct * relevant_half_bandwidth
    outside_margin = outside_distance_actual - outside_distance_required if outside_distance_actual is not None else None
    close_deep_inside_bands = is_close_deep_inside_bands(
        close=latest_candle.close,
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        inside_buffer_pct=config.inside_buffer_pct,
    )
    close_deep_outside_bands = is_close_deep_outside_bands(
        close=latest_candle.close,
        regime=regime,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        outside_buffer_pct=config.outside_buffer_pct,
    )

    return {
        "latest_open": latest_candle.open,
        "latest_high": latest_candle.high,
        "latest_low": latest_candle.low,
        "latest_close": latest_candle.close,
        "latest_regime": regime.value,
        "bars_since_regime_start": latest_regime_state.bars_since_regime_start,
        "bb_upper": _round_or_none(bb_upper),
        "bb_middle": _round_or_none(bb_middle),
        "bb_lower": _round_or_none(bb_lower),
        "relevant_half_bandwidth": _round_or_none(relevant_half_bandwidth),
        "average_relevant_half_bandwidth": _round_or_none(average_relevant_half_bandwidth),
        "bandwidth_ratio_value": _round_or_none(bandwidth_ratio_value),
        "bandwidth_ok": bandwidth_ok,
        "close_inside_bands": close_inside_bands,
        "candle_in_trend_direction": candle_in_trend_direction,
        "inside_distance_actual": _round_or_none(inside_distance_actual),
        "inside_distance_required": _round_or_none(inside_distance_required),
        "inside_margin": _round_or_none(inside_margin),
        "outside_distance_actual": _round_or_none(outside_distance_actual),
        "outside_distance_required": _round_or_none(outside_distance_required),
        "outside_margin": _round_or_none(outside_margin),
        "close_deep_inside_bands": close_deep_inside_bands,
        "close_deep_outside_bands": close_deep_outside_bands,
    }


def _evaluate_window(scenario: Any, candles: list[Candle]) -> tuple[Any, AgentState | None]:
    if _uses_agent_cycle(scenario):
        result, post_state = run_agent_cycle(
            candles=candles,
            config=scenario.config,
            account_balance=scenario.account_balance,
            state=_build_initial_agent_state(scenario),
        )
        return result, post_state

    result = run_strategy_cycle(
        candles=candles,
        config=scenario.config,
        account_balance=scenario.account_balance,
        active_trade=scenario.active_trade,
    )
    return result, None


def _append_match_comment(comments: list[str], field_name: str, matched: bool, actual: Any, expected: Any) -> None:
    status = "match" if matched else "mismatch"
    comments.append(f"{field_name}:{status} actual={actual} expected={expected}")


def _match_or_none(actual: Any, expected: Any) -> bool | None:
    if expected is None:
        return None
    return actual == expected


def score_scenario_match(scenario: Any, strategy_result: Any, post_state_or_agent_result: Any = None) -> int:
    score, _ = _score_scenario_match_with_comment(
        scenario=scenario,
        strategy_result=strategy_result,
        post_state_or_agent_result=post_state_or_agent_result,
    )
    return score


def _score_scenario_match_with_comment(
    scenario: Any,
    strategy_result: Any,
    post_state_or_agent_result: Any = None,
) -> tuple[int, str | None]:
    score = 0
    comments: list[str] = []

    trend_signal = getattr(strategy_result, "trend_signal", None)
    countertrend_signal = getattr(strategy_result, "countertrend_signal", None)
    decision = getattr(strategy_result, "decision", None)
    updated_trade = getattr(strategy_result, "updated_trade", None)

    if scenario.expected_trend_signal_valid is not None:
        actual = trend_signal.is_valid if trend_signal is not None else None
        matched = actual == scenario.expected_trend_signal_valid
        if matched:
            score += 2
        _append_match_comment(comments, "trend_valid", matched, actual, scenario.expected_trend_signal_valid)

    if scenario.expected_trend_signal_type is not None:
        actual = trend_signal.signal_type.value if trend_signal is not None else None
        matched = actual == scenario.expected_trend_signal_type
        if matched:
            score += 1
        _append_match_comment(comments, "trend_type", matched, actual, scenario.expected_trend_signal_type)

    if scenario.expected_countertrend_signal_valid is not None:
        actual = countertrend_signal.is_valid if countertrend_signal is not None else None
        matched = actual == scenario.expected_countertrend_signal_valid
        if matched:
            score += 2
        _append_match_comment(comments, "countertrend_valid", matched, actual, scenario.expected_countertrend_signal_valid)

    if scenario.expected_countertrend_signal_type is not None:
        actual = countertrend_signal.signal_type.value if countertrend_signal is not None else None
        matched = actual == scenario.expected_countertrend_signal_type
        if matched:
            score += 1
        _append_match_comment(comments, "countertrend_type", matched, actual, scenario.expected_countertrend_signal_type)

    if scenario.expected_decision_action is not None:
        actual = decision.action.value if decision is not None else None
        matched = actual == scenario.expected_decision_action
        if matched:
            score += 3
        _append_match_comment(comments, "decision", matched, actual, scenario.expected_decision_action)

    if scenario.expected_order_present is not None:
        if post_state_or_agent_result is not None:
            actual = getattr(post_state_or_agent_result, "pending_order", None) is not None
        else:
            actual = getattr(strategy_result, "order", None) is not None
        matched = actual == scenario.expected_order_present
        if matched:
            score += 2
        _append_match_comment(comments, "order_present", matched, actual, scenario.expected_order_present)

    if scenario.expected_break_even_activated is not None:
        actual = updated_trade.break_even_activated if updated_trade is not None else None
        matched = actual == scenario.expected_break_even_activated
        if matched:
            score += 2
        _append_match_comment(comments, "break_even_activated", matched, actual, scenario.expected_break_even_activated)

    if scenario.expected_consumed_flag is not None:
        actual = post_state_or_agent_result.trend_signal_consumed_in_regime if post_state_or_agent_result is not None else None
        matched = actual == scenario.expected_consumed_flag
        if matched:
            score += 2
        _append_match_comment(comments, "consumed_flag", matched, actual, scenario.expected_consumed_flag)

    return score, "; ".join(comments) if comments else None


def _build_candidate(
    scenario: Any,
    coin: str,
    candles: list[Candle],
    strategy_result: Any,
    post_state: AgentState | None,
    score: int,
    match_comment: str | None,
) -> HistoricalReferenceCandidate:
    trend_signal = getattr(strategy_result, "trend_signal", None)
    countertrend_signal = getattr(strategy_result, "countertrend_signal", None)
    updated_trade = getattr(strategy_result, "updated_trade", None)
    order_present = post_state.pending_order is not None if post_state is not None else getattr(strategy_result, "order", None) is not None
    consumed_flag = post_state.trend_signal_consumed_in_regime if post_state is not None else None
    decision_action = strategy_result.decision.action.value
    trend_signal_valid = trend_signal.is_valid if trend_signal is not None else None
    trend_signal_type = trend_signal.signal_type.value if trend_signal is not None else None
    countertrend_signal_valid = countertrend_signal.is_valid if countertrend_signal is not None else None
    countertrend_signal_type = countertrend_signal.signal_type.value if countertrend_signal is not None else None
    break_even_activated = updated_trade.break_even_activated if updated_trade is not None else None
    diagnostics = _calculate_window_diagnostics(candles, scenario.config)

    return HistoricalReferenceCandidate(
        scenario_name=scenario.name,
        score=score,
        coin=coin,
        window_size_bars=len(candles),
        start_timestamp=candles[0].timestamp.isoformat(),
        end_timestamp=candles[-1].timestamp.isoformat(),
        trigger_timestamp=candles[-1].timestamp.isoformat(),
        decision_action=decision_action,
        selected_signal_type=strategy_result.decision.selected_signal_type,
        trend_signal_valid=trend_signal_valid,
        trend_signal_type=trend_signal_type,
        countertrend_signal_valid=countertrend_signal_valid,
        countertrend_signal_type=countertrend_signal_type,
        trend_reason=trend_signal.reason if trend_signal is not None else None,
        countertrend_reason=countertrend_signal.reason if countertrend_signal is not None else None,
        order_present=order_present,
        break_even_activated=break_even_activated,
        consumed_flag=consumed_flag,
        latest_open=_round_or_none(diagnostics["latest_open"]),
        latest_high=_round_or_none(diagnostics["latest_high"]),
        latest_low=_round_or_none(diagnostics["latest_low"]),
        latest_close=_round_or_none(diagnostics["latest_close"]),
        latest_regime=diagnostics["latest_regime"],
        bars_since_regime_start=diagnostics["bars_since_regime_start"],
        bb_upper=diagnostics["bb_upper"],
        bb_middle=diagnostics["bb_middle"],
        bb_lower=diagnostics["bb_lower"],
        relevant_half_bandwidth=diagnostics["relevant_half_bandwidth"],
        average_relevant_half_bandwidth=diagnostics["average_relevant_half_bandwidth"],
        bandwidth_ratio_value=diagnostics["bandwidth_ratio_value"],
        bandwidth_ok=diagnostics["bandwidth_ok"],
        close_inside_bands=diagnostics["close_inside_bands"],
        candle_in_trend_direction=diagnostics["candle_in_trend_direction"],
        inside_distance_actual=diagnostics["inside_distance_actual"],
        inside_distance_required=diagnostics["inside_distance_required"],
        inside_margin=diagnostics["inside_margin"],
        outside_distance_actual=diagnostics["outside_distance_actual"],
        outside_distance_required=diagnostics["outside_distance_required"],
        outside_margin=diagnostics["outside_margin"],
        close_deep_inside_bands=diagnostics["close_deep_inside_bands"],
        close_deep_outside_bands=diagnostics["close_deep_outside_bands"],
        expected_decision_action=scenario.expected_decision_action,
        expected_trend_signal_valid=scenario.expected_trend_signal_valid,
        expected_trend_signal_type=scenario.expected_trend_signal_type,
        expected_countertrend_signal_valid=scenario.expected_countertrend_signal_valid,
        expected_countertrend_signal_type=scenario.expected_countertrend_signal_type,
        expected_order_present=scenario.expected_order_present,
        expected_break_even_activated=scenario.expected_break_even_activated,
        expected_consumed_flag=scenario.expected_consumed_flag,
        decision_match=_match_or_none(decision_action, scenario.expected_decision_action),
        trend_signal_valid_match=_match_or_none(trend_signal_valid, scenario.expected_trend_signal_valid),
        trend_signal_type_match=_match_or_none(trend_signal_type, scenario.expected_trend_signal_type),
        countertrend_signal_valid_match=_match_or_none(countertrend_signal_valid, scenario.expected_countertrend_signal_valid),
        countertrend_signal_type_match=_match_or_none(countertrend_signal_type, scenario.expected_countertrend_signal_type),
        order_present_match=_match_or_none(order_present, scenario.expected_order_present),
        break_even_activated_match=_match_or_none(break_even_activated, scenario.expected_break_even_activated),
        consumed_flag_match=_match_or_none(consumed_flag, scenario.expected_consumed_flag),
        match_comment=match_comment,
    )


def keep_best_candidates(
    existing_candidates: list[HistoricalReferenceCandidate],
    new_candidate: HistoricalReferenceCandidate,
    limit: int = 2,
) -> list[HistoricalReferenceCandidate]:
    ranked = sorted([*existing_candidates, new_candidate], key=lambda candidate: (candidate.score, candidate.end_timestamp), reverse=True)
    return ranked[:limit]


def serialize_candidates(
    scenario_candidates: dict[str, list[HistoricalReferenceCandidate]],
) -> dict[str, list[dict[str, Any]]]:
    return {scenario_name: [asdict(candidate) for candidate in candidates] for scenario_name, candidates in scenario_candidates.items()}


def _to_csv_value(value: Any) -> str:
    if value is None:
        return CSV_NA
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value).strip()
    return text if text else CSV_NA

def flatten_candidates_for_csv(
    scenario_candidates: dict[str, list[HistoricalReferenceCandidate]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for scenario_name, candidates in scenario_candidates.items():
        for rank, candidate in enumerate(candidates, start=1):
            row = {
                "scenario_name": scenario_name,
                "candidate_rank": rank,
                "score": candidate.score,
                "coin": candidate.coin,
                "window_size_bars": candidate.window_size_bars,
                "window_start_timestamp": candidate.start_timestamp,
                "window_start_date": candidate.start_timestamp.split("T", 1)[0],
                "window_end_timestamp": candidate.end_timestamp,
                "window_end_date": candidate.end_timestamp.split("T", 1)[0],
                "trigger_timestamp": candidate.trigger_timestamp,
                "trigger_date": candidate.trigger_timestamp.split("T", 1)[0],
                "actual_decision_action": candidate.decision_action,
                "actual_selected_signal_type": candidate.selected_signal_type,
                "actual_trend_signal_valid": candidate.trend_signal_valid,
                "actual_trend_signal_type": candidate.trend_signal_type,
                "actual_trend_reason": candidate.trend_reason,
                "actual_countertrend_signal_valid": candidate.countertrend_signal_valid,
                "actual_countertrend_signal_type": candidate.countertrend_signal_type,
                "actual_countertrend_reason": candidate.countertrend_reason,
                "actual_order_present": candidate.order_present,
                "actual_break_even_activated": candidate.break_even_activated,
                "actual_consumed_flag": candidate.consumed_flag,
                "actual_latest_open": candidate.latest_open,
                "actual_latest_high": candidate.latest_high,
                "actual_latest_low": candidate.latest_low,
                "actual_latest_close": candidate.latest_close,
                "actual_latest_regime": candidate.latest_regime,
                "actual_bars_since_regime_start": candidate.bars_since_regime_start,
                "actual_bb_upper": candidate.bb_upper,
                "actual_bb_middle": candidate.bb_middle,
                "actual_bb_lower": candidate.bb_lower,
                "actual_relevant_half_bandwidth": candidate.relevant_half_bandwidth,
                "actual_average_relevant_half_bandwidth": candidate.average_relevant_half_bandwidth,
                "actual_bandwidth_ratio_value": candidate.bandwidth_ratio_value,
                "actual_bandwidth_ok": candidate.bandwidth_ok,
                "actual_close_inside_bands": candidate.close_inside_bands,
                "actual_candle_in_trend_direction": candidate.candle_in_trend_direction,
                "actual_inside_distance_actual": candidate.inside_distance_actual,
                "actual_inside_distance_required": candidate.inside_distance_required,
                "actual_inside_margin": candidate.inside_margin,
                "actual_outside_distance_actual": candidate.outside_distance_actual,
                "actual_outside_distance_required": candidate.outside_distance_required,
                "actual_outside_margin": candidate.outside_margin,
                "actual_close_deep_inside_bands": candidate.close_deep_inside_bands,
                "actual_close_deep_outside_bands": candidate.close_deep_outside_bands,
                "expected_decision_action": candidate.expected_decision_action,
                "expected_trend_signal_valid": candidate.expected_trend_signal_valid,
                "expected_trend_signal_type": candidate.expected_trend_signal_type,
                "expected_countertrend_signal_valid": candidate.expected_countertrend_signal_valid,
                "expected_countertrend_signal_type": candidate.expected_countertrend_signal_type,
                "expected_order_present": candidate.expected_order_present,
                "expected_break_even_activated": candidate.expected_break_even_activated,
                "expected_consumed_flag": candidate.expected_consumed_flag,
                "match_decision_action": candidate.decision_match,
                "match_trend_signal_valid": candidate.trend_signal_valid_match,
                "match_trend_signal_type": candidate.trend_signal_type_match,
                "match_countertrend_signal_valid": candidate.countertrend_signal_valid_match,
                "match_countertrend_signal_type": candidate.countertrend_signal_type_match,
                "match_order_present": candidate.order_present_match,
                "match_break_even_activated": candidate.break_even_activated_match,
                "match_consumed_flag": candidate.consumed_flag_match,
            }
            rows.append({key: _to_csv_value(value) for key, value in row.items()})
    return rows


def export_candidates(
    scenario_candidates: dict[str, list[HistoricalReferenceCandidate]],
    output_path: Path = ARTIFACTS_JSON_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(serialize_candidates(scenario_candidates), indent=2), encoding="utf-8")
    return output_path


def export_candidates_csv(
    scenario_candidates: dict[str, list[HistoricalReferenceCandidate]],
    output_path: Path = ARTIFACTS_CSV_PATH,
) -> Path:
    rows = flatten_candidates_for_csv(scenario_candidates)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scenario_name", "candidate_rank", "score", "coin", "window_size_bars",
        "window_start_timestamp", "window_start_date", "window_end_timestamp", "window_end_date",
        "trigger_timestamp", "trigger_date", "actual_decision_action", "actual_selected_signal_type",
        "actual_trend_signal_valid", "actual_trend_signal_type", "actual_trend_reason",
        "actual_countertrend_signal_valid", "actual_countertrend_signal_type", "actual_countertrend_reason",
        "actual_order_present", "actual_break_even_activated", "actual_consumed_flag",
        "actual_latest_open", "actual_latest_high", "actual_latest_low", "actual_latest_close",
        "actual_latest_regime", "actual_bars_since_regime_start", "actual_bb_upper", "actual_bb_middle",
        "actual_bb_lower", "actual_relevant_half_bandwidth", "actual_average_relevant_half_bandwidth",
        "actual_bandwidth_ratio_value", "actual_bandwidth_ok", "actual_close_inside_bands",
        "actual_candle_in_trend_direction", "actual_inside_distance_actual", "actual_inside_distance_required",
        "actual_inside_margin", "actual_outside_distance_actual", "actual_outside_distance_required",
        "actual_outside_margin", "actual_close_deep_inside_bands", "actual_close_deep_outside_bands",
        "expected_decision_action", "expected_trend_signal_valid", "expected_trend_signal_type",
        "expected_countertrend_signal_valid", "expected_countertrend_signal_type", "expected_order_present",
        "expected_break_even_activated", "expected_consumed_flag", "match_decision_action",
        "match_trend_signal_valid", "match_trend_signal_type", "match_countertrend_signal_valid",
        "match_countertrend_signal_type", "match_order_present", "match_break_even_activated",
        "match_consumed_flag",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return output_path


def _summarize_results(candidates_by_scenario: dict[str, list[HistoricalReferenceCandidate]]) -> None:
    for scenario_name, candidates in candidates_by_scenario.items():
        print(f"Scenario: {scenario_name}")
        if not candidates:
            print("  no matching candidates found")
            continue

        for index, candidate in enumerate(candidates, start=1):
            print(f"  candidate {index}:")
            print(f"    score: {candidate.score}")
            print(f"    coin: {candidate.coin}")
            print(f"    window: {candidate.start_timestamp} -> {candidate.end_timestamp}")
            print(f"    trigger_timestamp: {candidate.trigger_timestamp}")
            print(f"    decision_action: {candidate.decision_action}")
            print(f"    selected_signal_type: {candidate.selected_signal_type}")
            print(f"    trend_signal_valid: {candidate.trend_signal_valid}")
            print(f"    countertrend_signal_valid: {candidate.countertrend_signal_valid}")
            print(f"    order_present: {candidate.order_present}")
            print(f"    inside_margin: {candidate.inside_margin}")
            print(f"    outside_margin: {candidate.outside_margin}")
            if candidate.match_comment:
                print(f"    match_comment: {candidate.match_comment}")


def main() -> None:
    print("Historical reference case scan started.")

    try:
        hyperliquid_config = load_hyperliquid_config_from_env()
        scenarios = load_all_golden_scenarios()

        print(f"Hyperliquid coin: {hyperliquid_config.coin}")
        print(f"interval: {hyperliquid_config.interval}")
        print(f"lookback_bars: {hyperliquid_config.lookback_bars}")
        print(f"Golden scenarios: {len(scenarios)}")

        live_batch = HyperliquidHistoricalProvider(hyperliquid_config).fetch_candles()
        candidates_by_scenario: dict[str, list[HistoricalReferenceCandidate]] = {scenario.name: [] for scenario in scenarios}

        for scenario in scenarios:
            window_size = len(scenario.candles)
            windows = build_replay_windows(live_batch.candles, window_size)
            for window in windows:
                strategy_result, post_state = _evaluate_window(scenario, window)
                score, match_comment = _score_scenario_match_with_comment(
                    scenario=scenario,
                    strategy_result=strategy_result,
                    post_state_or_agent_result=post_state,
                )
                if score <= 0:
                    continue

                candidate = _build_candidate(
                    scenario=scenario,
                    coin=hyperliquid_config.coin,
                    candles=window,
                    strategy_result=strategy_result,
                    post_state=post_state,
                    score=score,
                    match_comment=match_comment,
                )
                candidates_by_scenario[scenario.name] = keep_best_candidates(candidates_by_scenario[scenario.name], candidate)

        _summarize_results(candidates_by_scenario)
        json_output_path = export_candidates(candidates_by_scenario)
        csv_output_path = export_candidates_csv(candidates_by_scenario)
        print(f"Exported review data (JSON): {json_output_path}")
        print(f"Exported review data (CSV): {csv_output_path}")
    except Exception as exc:
        print(f"Historical reference case scan failed: {exc}")


if __name__ == "__main__":
    main()

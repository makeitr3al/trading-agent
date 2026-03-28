from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.find_historical_reference_cases import (
    HistoricalReferenceCandidate,
    build_replay_windows,
    export_candidates,
    export_candidates_csv,
    flatten_candidates_for_csv,
    keep_best_candidates,
    score_scenario_match,
    serialize_candidates,
)
from models.candle import Candle


class FakeSignal:
    def __init__(self, is_valid: bool, signal_type: str, reason: str = "reason") -> None:
        self.is_valid = is_valid
        self.signal_type = SimpleNamespace(value=signal_type)
        self.reason = reason


class FakeDecision:
    def __init__(self, action: str, selected_signal_type: str | None = None) -> None:
        self.action = SimpleNamespace(value=action)
        self.selected_signal_type = selected_signal_type


class FakeUpdatedTrade:
    def __init__(self, break_even_activated: bool) -> None:
        self.break_even_activated = break_even_activated


class FakeResult:
    def __init__(
        self,
        trend_signal: FakeSignal | None = None,
        countertrend_signal: FakeSignal | None = None,
        decision: FakeDecision | None = None,
        order: object | None = None,
        updated_trade: FakeUpdatedTrade | None = None,
    ) -> None:
        self.trend_signal = trend_signal
        self.countertrend_signal = countertrend_signal
        self.decision = decision or FakeDecision("NO_ACTION")
        self.order = order
        self.updated_trade = updated_trade


def _make_candle(day: int, open_price: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp=datetime(2026, 1, day, tzinfo=timezone.utc),
        open=open_price,
        high=high,
        low=low,
        close=close,
    )


def _make_candidate() -> HistoricalReferenceCandidate:
    return HistoricalReferenceCandidate(
        scenario_name="scenario",
        score=7,
        coin="BTC",
        window_size_bars=20,
        analysis_window_size_bars=220,
        warmup_bars=200,
        start_timestamp="2026-01-01T00:00:00+00:00",
        end_timestamp="2026-01-20T00:00:00+00:00",
        analysis_start_timestamp="2025-06-15T00:00:00+00:00",
        analysis_end_timestamp="2026-01-20T00:00:00+00:00",
        trigger_timestamp="2026-01-20T00:00:00+00:00",
        decision_action="PREPARE_TREND_ORDER",
        selected_signal_type="TREND_LONG",
        trend_signal_valid=True,
        trend_signal_type="TREND_LONG",
        countertrend_signal_valid=False,
        countertrend_signal_type=None,
        trend_reason="trend signal detected",
        countertrend_reason="not first regime bar",
        order_present=True,
        break_even_activated=None,
        consumed_flag=None,
        latest_open=100.0,
        latest_high=104.0,
        latest_low=99.5,
        latest_close=103.0,
        latest_regime="bullish",
        bars_since_regime_start=2,
        bb_upper=105.0,
        bb_middle=101.0,
        bb_lower=97.0,
        relevant_half_bandwidth=4.0,
        average_relevant_half_bandwidth=4.5,
        bandwidth_ratio_value=0.88888889,
        bandwidth_ok=True,
        close_inside_bands=True,
        candle_in_trend_direction=True,
        inside_distance_actual=2.0,
        inside_distance_required=0.8,
        inside_margin=1.2,
        outside_distance_actual=-2.0,
        outside_distance_required=0.8,
        outside_margin=-2.8,
        close_deep_inside_bands=True,
        close_deep_outside_bands=False,
        expected_decision_action="PREPARE_TREND_ORDER",
        expected_trend_signal_valid=True,
        expected_trend_signal_type="TREND_LONG",
        expected_countertrend_signal_valid=False,
        expected_countertrend_signal_type=None,
        expected_order_present=True,
        expected_break_even_activated=None,
        expected_consumed_flag=None,
        decision_match=True,
        trend_signal_valid_match=True,
        trend_signal_type_match=True,
        countertrend_signal_valid_match=True,
        countertrend_signal_type_match=None,
        order_present_match=True,
        break_even_activated_match=None,
        consumed_flag_match=None,
        match_comment="decision:match",
    )


def test_score_scenario_match_gives_higher_score_for_closer_match() -> None:
    scenario = SimpleNamespace(
        expected_trend_signal_valid=True,
        expected_trend_signal_type="TREND_LONG",
        expected_countertrend_signal_valid=False,
        expected_countertrend_signal_type=None,
        expected_decision_action="PREPARE_TREND_ORDER",
        expected_order_present=True,
        expected_break_even_activated=None,
        expected_consumed_flag=None,
    )
    strong_result = FakeResult(
        trend_signal=FakeSignal(True, "TREND_LONG"),
        countertrend_signal=FakeSignal(False, "COUNTERTREND_SHORT"),
        decision=FakeDecision("PREPARE_TREND_ORDER", "TREND_LONG"),
        order=object(),
    )
    weak_result = FakeResult(
        trend_signal=FakeSignal(False, "TREND_LONG"),
        countertrend_signal=FakeSignal(False, "COUNTERTREND_SHORT"),
        decision=FakeDecision("NO_ACTION"),
        order=None,
    )

    assert score_scenario_match(scenario, strong_result) > score_scenario_match(scenario, weak_result)


def test_score_scenario_match_handles_missing_expected_fields_gracefully() -> None:
    scenario = SimpleNamespace(
        expected_trend_signal_valid=None,
        expected_trend_signal_type=None,
        expected_countertrend_signal_valid=None,
        expected_countertrend_signal_type=None,
        expected_decision_action=None,
        expected_order_present=None,
        expected_break_even_activated=None,
        expected_consumed_flag=None,
    )
    result = FakeResult()

    assert score_scenario_match(scenario, result) == 0


def test_candidate_selection_keeps_at_most_two_best_matches_per_scenario() -> None:
    existing: list[HistoricalReferenceCandidate] = []
    candidates = [_make_candidate(), _make_candidate(), _make_candidate()]
    candidates[0].score = 3
    candidates[0].end_timestamp = "2026-01-02T00:00:00+00:00"
    candidates[1].score = 8
    candidates[1].end_timestamp = "2026-01-04T00:00:00+00:00"
    candidates[2].score = 5
    candidates[2].end_timestamp = "2026-01-06T00:00:00+00:00"

    for candidate in candidates:
        existing = keep_best_candidates(existing, candidate)

    assert len(existing) == 2
    assert [candidate.score for candidate in existing] == [8, 5]


def test_replay_window_helper_handles_empty_input_gracefully() -> None:
    assert build_replay_windows([], 5) == []
    assert build_replay_windows([_make_candle(1, 1.0, 1.1, 0.9, 1.0)], 2) == []


def test_export_helper_serializes_basic_candidate_data_correctly(tmp_path: Path) -> None:
    candidates = {"scenario": [_make_candidate()]}

    serialized = serialize_candidates(candidates)
    assert serialized["scenario"][0]["score"] == 7
    assert serialized["scenario"][0]["coin"] == "BTC"
    assert serialized["scenario"][0]["inside_margin"] == 1.2

    csv_rows = flatten_candidates_for_csv(candidates)
    assert csv_rows[0]["candidate_rank"] == "1"
    assert csv_rows[0]["window_start_date"] == "2026-01-01"
    assert csv_rows[0]["analysis_start_date"] == "2025-06-15"
    assert csv_rows[0]["trigger_date"] == "2026-01-20"
    assert csv_rows[0]["warmup_bars"] == "200"
    assert csv_rows[0]["actual_break_even_activated"] == "n/a"
    assert csv_rows[0]["expected_countertrend_signal_type"] == "n/a"
    assert csv_rows[0]["match_countertrend_signal_type"] == "n/a"
    assert csv_rows[0]["actual_inside_margin"] == "1.2"
    assert csv_rows[0]["actual_outside_margin"] == "-2.8"
    assert csv_rows[0]["actual_bb_upper"] == "105.0"

    json_output_path = export_candidates(candidates, tmp_path / "cases.json")
    json_content = json_output_path.read_text(encoding="utf-8")
    assert '"scenario_name": "scenario"' in json_content
    assert '"decision_action": "PREPARE_TREND_ORDER"' in json_content

    csv_output_path = export_candidates_csv(candidates, tmp_path / "cases.csv")
    csv_content = csv_output_path.read_text(encoding="utf-8")
    assert "scenario_name,candidate_rank,score,coin,window_size_bars" in csv_content
    assert "analysis_window_size_bars" in csv_content
    assert "warmup_bars" in csv_content
    assert "actual_inside_margin" in csv_content
    assert "actual_bb_upper" in csv_content
    assert "scenario,1,7,BTC,20,220,200" in csv_content


def test_chronological_windows_keep_original_order() -> None:
    candles = [
        _make_candle(1, 1.0, 1.1, 0.9, 1.0),
        _make_candle(2, 1.0, 1.2, 0.95, 1.1),
        _make_candle(3, 1.1, 1.3, 1.0, 1.2),
    ]

    windows = build_replay_windows(candles, 2, warmup_bars=1)

    assert len(windows) == 2
    assert windows[0].trigger_candles[0].timestamp < windows[0].trigger_candles[1].timestamp
    assert windows[1].analysis_candles[0].timestamp < windows[1].analysis_candles[1].timestamp
    assert windows[0].warmup_bars == 0
    assert windows[1].warmup_bars == 1
    assert len(windows[1].analysis_candles) == 3
    assert len(windows[1].trigger_candles) == 2

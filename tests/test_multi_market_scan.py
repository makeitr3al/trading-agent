from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.multi_market_scan import _best_signal_strength, _select_execution_candidates


def _make_signal(is_valid: bool, strength: float | None):
    return SimpleNamespace(is_valid=is_valid, signal_strength=strength)


def _make_result(trend_valid: bool, trend_strength: float | None, counter_valid: bool, counter_strength: float | None):
    strategy_result = SimpleNamespace(
        trend_signal=_make_signal(trend_valid, trend_strength),
        countertrend_signal=_make_signal(counter_valid, counter_strength),
    )
    return SimpleNamespace(strategy_result=strategy_result)


def test_best_signal_strength_returns_max_valid_strength() -> None:
    result = _make_result(True, 0.35, True, 0.9)

    assert _best_signal_strength(result) == 0.9


def test_select_execution_candidates_keeps_all_when_slots_are_sufficient() -> None:
    candidates = [
        {"symbol": "BTC/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.2},
        {"symbol": "ETH/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.8},
    ]

    selected = _select_execution_candidates(candidates, available_slots=2)

    assert [item["symbol"] for item in selected] == ["BTC/USDC", "ETH/USDC"]


def test_select_execution_candidates_uses_strength_only_when_slots_are_limited() -> None:
    candidates = [
        {"symbol": "BTC/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.2},
        {"symbol": "ETH/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.8},
        {"symbol": "SOL/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.5},
    ]

    selected = _select_execution_candidates(candidates, available_slots=2)

    assert [item["symbol"] for item in selected] == ["ETH/USDC", "SOL/USDC"]

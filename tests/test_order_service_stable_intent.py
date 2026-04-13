"""Optional stable intent id (``PROPR_STABLE_INTENT_ID``) for submit idempotency experiments."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from broker.order_service import build_order_submission_preview, derive_stable_intent_id
from models.order import Order, OrderType


def _buy_stop_order() -> Order:
    return Order(
        order_type=OrderType.BUY_STOP,
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
        position_size=1.0,
        signal_source="trend_long",
    )


def test_derive_stable_intent_id_is_deterministic_for_same_seed() -> None:
    assert derive_stable_intent_id("seed-a") == derive_stable_intent_id("seed-a")
    assert derive_stable_intent_id("seed-a") != derive_stable_intent_id("seed-b")


def test_build_order_submission_preview_reuses_intent_when_stable_env_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPR_STABLE_INTENT_ID", "YES")
    order = _buy_stop_order()
    seed = "account-1|BTC/USDC|2026-01-01T00:00:00Z|BUY_STOP|110.0|100.0|130.0|1.0|trend_long"
    first = build_order_submission_preview(order, "BTC/USDC", stable_intent_seed=seed)
    second = build_order_submission_preview(order, "BTC/USDC", stable_intent_seed=seed)
    assert first["intent_id"] == second["intent_id"]
    assert len(first["intent_id"]) == 26


def test_build_order_submission_preview_ignores_stable_seed_when_env_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROPR_STABLE_INTENT_ID", raising=False)
    order = _buy_stop_order()
    seed = "account-1|BTC/USDC|2026-01-01T00:00:00Z|BUY_STOP|110.0|100.0|130.0|1.0|trend_long"
    first = build_order_submission_preview(order, "BTC/USDC", stable_intent_seed=seed)
    second = build_order_submission_preview(order, "BTC/USDC", stable_intent_seed=seed)
    assert first["intent_id"] != second["intent_id"]

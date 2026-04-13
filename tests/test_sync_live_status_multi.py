"""Multi-challenge aggregation for scripts/sync_live_status.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sync_live_status import build_live_status_from_all_active_challenges


def _open_pos(symbol: str, account_tag: str) -> dict:
    return {
        "status": "open",
        "positionSide": "long",
        "entryPrice": "100",
        "stopLoss": "90",
        "takeProfit": "120",
        "quantity": "0.1",
        "positionId": f"pos-{account_tag}-{symbol}",
        "asset": symbol,
        "unrealizedPnl": "5.5" if symbol == "BTC" else "1.0",
    }


class FakeMultiClient:
    def __init__(self) -> None:
        self.environment = "beta"

    def get_challenge_attempts(self) -> dict:
        return {
            "data": [
                {
                    "attemptId": "a1",
                    "accountId": "urn:acc:1",
                    "challengeId": "ch-A",
                    "status": "active",
                },
                {
                    "attemptId": "a2",
                    "accountId": "urn:acc:2",
                    "challengeId": "ch-B",
                    "status": "active",
                },
            ]
        }

    def get_challenge_attempt(self, attempt_id: str) -> dict:
        name = "Alpha" if attempt_id == "a1" else "Beta"
        return {
            "account": {
                "balance": "10000",
                "totalUnrealizedPnl": "6.5" if attempt_id == "a1" else "2.0",
                "marginBalance": "10006.5" if attempt_id == "a1" else "10002",
                "availableBalance": "9000",
                "highWaterMark": "10000",
            },
            "challenge": {"name": name, "initialBalance": "10000"},
        }

    def get_orders(self, account_id: str) -> dict:
        return {"data": []}

    def get_positions(self, account_id: str) -> dict:
        if account_id == "urn:acc:1":
            return {"data": [_open_pos("BTC", "1")]}
        return {"data": [_open_pos("ETH", "2")]}


def test_build_live_status_aggregates_two_challenges() -> None:
    payload = build_live_status_from_all_active_challenges(FakeMultiClient(), "beta")
    assert payload is not None
    assert payload["active_challenges_count"] == 2
    assert payload["account_open_positions_count"] == 2
    assert payload["account_unrealized_pnl"] == 5.5 + 1.0
    assert len(payload["challenges_overview"]) == 2
    assert payload["challenges_overview"][0]["challenge_name"] == "Alpha"
    assert payload["challenges_overview"][1]["account_open_positions_count"] == 1
    assert payload["challenges_overview"][0]["margin_balance"] == 10006.5
    assert payload["challenges_overview"][1]["margin_balance"] == 10002.0
    assert payload["account_total_margin_balance"] == pytest.approx(10006.5 + 10002.0)
    flat = payload["open_positions_summary"]
    assert flat is not None and len(flat) == 2
    names = {row.get("challenge_name") for row in flat}
    assert names == {"Alpha", "Beta"}


class FakeSingleChallengeMissingSlTpOnPosition(FakeMultiClient):
    """REST position without SL/TP on the row; exit orders carry levels (enrichment path)."""

    def get_challenge_attempts(self) -> dict:
        return {
            "data": [
                {
                    "attemptId": "solo",
                    "accountId": "urn:acc:solo",
                    "challengeId": "ch-solo",
                    "status": "active",
                },
            ]
        }

    def get_challenge_attempt(self, attempt_id: str) -> dict:
        return {
            "account": {
                "balance": "10000",
                "totalUnrealizedPnl": "7.25",
                "marginBalance": "10007.25",
                "availableBalance": "9000",
                "highWaterMark": "10000",
            },
            "challenge": {"name": "Solo", "initialBalance": "10000"},
        }

    def get_orders(self, account_id: str) -> dict:
        return {
            "data": [
                {
                    "orderId": "sl-1",
                    "type": "stop_market",
                    "side": "sell",
                    "positionId": "p-solo",
                    "reduceOnly": True,
                    "status": "open",
                    "triggerPrice": "90",
                },
                {
                    "orderId": "tp-1",
                    "type": "take_profit_limit",
                    "side": "sell",
                    "positionId": "p-solo",
                    "reduceOnly": True,
                    "status": "open",
                    "price": "120",
                },
            ]
        }

    def get_positions(self, account_id: str) -> dict:
        return {
            "data": [
                {
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100",
                    "quantity": "0.1",
                    "positionId": "p-solo",
                    "asset": "BTC",
                    "unrealizedPnl": "7.25",
                },
            ]
        }


def test_build_live_status_counts_open_position_when_sl_tp_only_on_orders() -> None:
    payload = build_live_status_from_all_active_challenges(
        FakeSingleChallengeMissingSlTpOnPosition(),
        "beta",
    )
    assert payload is not None
    assert payload["account_open_positions_count"] == 1
    assert payload["account_unrealized_pnl"] == pytest.approx(7.25)
    ov = payload["challenges_overview"][0]
    assert ov["account_open_positions_count"] == 1
    assert ov["margin_balance"] == pytest.approx(10007.25)
    summary = payload["open_positions_summary"]
    assert summary is not None and len(summary) == 1
    assert summary[0]["stop_loss"] == 90.0
    assert summary[0]["take_profit"] == 120.0

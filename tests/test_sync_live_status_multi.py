"""Multi-challenge aggregation for scripts/sync_live_status.py."""

from __future__ import annotations

import sys
from pathlib import Path

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
    flat = payload["open_positions_summary"]
    assert flat is not None and len(flat) == 2
    names = {row.get("challenge_name") for row in flat}
    assert names == {"Alpha", "Beta"}

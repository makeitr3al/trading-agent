"""Shared test doubles for ``sync_agent_state_from_propr`` tests."""

from __future__ import annotations

from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class FakeProprClient:
    def __init__(self, orders_payload: dict, positions_payload: dict) -> None:
        self.orders_payload = orders_payload
        self.positions_payload = positions_payload
        self.calls: list[tuple[str, str]] = []

    def get_orders(self, account_id: str) -> dict:
        self.calls.append(("orders", account_id))
        return self.orders_payload

    def get_positions(self, account_id: str) -> dict:
        self.calls.append(("positions", account_id))
        return self.positions_payload

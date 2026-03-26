from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from broker.challenge_service import get_active_challenge_context, parse_challenge_attempts
from broker.propr_client import ProprClient
from utils.env_loader import load_propr_config_from_env


def _count_items(payload: dict[str, Any]) -> int:
    data = payload.get("data")
    if isinstance(data, list):
        return len(data)
    return 0


def _compact_dict(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: payload.get(key) for key in keys if payload.get(key) is not None}


def main() -> None:
    try:
        config = load_propr_config_from_env()
        client = ProprClient(config)

        print("Propr smoke test started.")
        print(f"Environment: {config.environment}")
        print(f"Base URL: {config.base_url}")

        health = client.health_check()
        print("[health]", health)

        profile = client.get_user_profile()
        print(
            "[user]",
            _compact_dict(profile, ["id", "email", "name", "status"]),
        )

        challenge_payload = client.get_challenge_attempts()
        attempts = parse_challenge_attempts(challenge_payload)
        print(f"[challenge-attempts] count={len(attempts)}")

        for attempt in attempts[:5]:
            print(f"  - attempt_id: {attempt.attempt_id}")
            print(f"    account_id: {attempt.account_id}")
            print(f"    status: {attempt.status}")

        challenge_context = get_active_challenge_context(client)
        if challenge_context is None:
            print("No active challenge attempt found. Read-only smoke test finished.")
            return

        print("Active challenge:")
        print(f"- attempt_id: {challenge_context.attempt.attempt_id}")
        print(f"- account_id: {challenge_context.account_id}")
        print(f"- status: {challenge_context.attempt.status}")

        account_id = challenge_context.account_id
        orders = client.get_orders(account_id)
        positions = client.get_positions(account_id)
        trades = client.get_trades(account_id)

        print(f"[orders] count={_count_items(orders)}")
        print(f"[positions] count={_count_items(positions)}")
        print(f"[trades] count={_count_items(trades)}")
        print("Read-only Propr smoke test finished.")
    except Exception as exc:
        print(f"Smoke test failed: {exc}")


if __name__ == "__main__":
    main()

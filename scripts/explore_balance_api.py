"""
Read-only exploration script: dumps challenge, attempt, and position data
from the Propr Beta API to understand how account balance can be derived.

Usage: .\.venv\Scripts\python.exe scripts/explore_balance_api.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.env_loader import load_propr_config_from_env
from broker.propr_client import ProprClient


def pp(label: str, data) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(json.dumps(data, indent=2, default=str))


def main() -> int:
    config = load_propr_config_from_env()
    print(f"Environment: {config.environment}")
    print(f"Base URL: {config.base_url}")

    if config.environment != "beta":
        print("ERROR: This script must run against beta only.")
        return 1

    client = ProprClient(config)

    # 1. List all challenges (public, no auth needed)
    print("\n--- Fetching challenges (public endpoint) ---")
    challenges_raw = client.sdk_client.get_challenges()
    pp("GET /challenges (all available challenges)", challenges_raw)

    # 2. List challenge attempts (auth required)
    print("\n--- Fetching challenge attempts ---")
    attempts_raw = client.sdk_client.get_challenge_attempts()
    pp("GET /challenge-attempts", attempts_raw)

    # 3. For each active attempt, get detailed attempt info and positions
    active_attempts = [a for a in attempts_raw if a.get("status") == "active"]
    print(f"\nActive attempts: {len(active_attempts)}")

    for attempt in active_attempts:
        attempt_id = attempt.get("attemptId") or attempt.get("attempt_id") or attempt.get("id")
        account_id = attempt.get("accountId") or attempt.get("account_id")
        challenge_id = attempt.get("challengeId") or attempt.get("challenge_id")

        print(f"\n--- Attempt: {attempt_id} ---")
        print(f"    Account: {account_id}")
        print(f"    Challenge: {challenge_id}")

        # 3a. Get detailed attempt info
        if attempt_id:
            try:
                detail = client.sdk_client.get_challenge_attempt(attempt_id)
                pp(f"GET /challenge-attempts/{attempt_id}", detail)
            except Exception as exc:
                print(f"  Failed to get attempt detail: {exc}")

        # 3b. Get positions for this account
        if account_id:
            try:
                client.sdk_client.setup(account_id=account_id)
                positions = client.sdk_client.get_positions()
                pp(f"GET /accounts/{account_id}/positions", positions)

                # Summarize position balances
                for pos in positions:
                    qty = pos.get("quantity", "0")
                    if float(qty) != 0:
                        print(f"  OPEN: {pos.get('asset')} {pos.get('positionSide')} "
                              f"qty={qty} entry={pos.get('entryPrice')} "
                              f"unrealizedPnl={pos.get('unrealizedPnl')} "
                              f"marginUsed={pos.get('marginUsed')}")
            except Exception as exc:
                print(f"  Failed to get positions: {exc}")

        # 3c. If we have a challengeId, try to find the matching challenge definition
        if challenge_id:
            matching = [c for c in challenges_raw if
                        (c.get("challengeId") or c.get("id")) == challenge_id]
            if matching:
                pp(f"Matching challenge definition for {challenge_id}", matching[0])
            else:
                print(f"  No matching challenge definition found for {challenge_id}")

    # 4. Also dump leverage limits
    print("\n--- Fetching leverage limits ---")
    try:
        limits = client.get_effective_leverage_limits()
        pp("GET /leverage-limits/effective", limits)
    except Exception as exc:
        print(f"  Failed: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

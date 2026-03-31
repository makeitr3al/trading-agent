"""Sync account status from Propr API and write live_status.json."""

from __future__ import annotations

import argparse
import sys

from broker.challenge_service import get_active_challenge_context
from broker.propr_client import ProprClient
from broker.state_sync import sync_agent_state_from_propr
from utils.env_loader import load_propr_config_from_env
from utils.live_status import write_live_status_from_state


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync live account status from Propr API.")
    parser.add_argument("--output-path", required=True, help="Path to write live_status.json")
    args = parser.parse_args()

    propr_config = load_propr_config_from_env()
    environment = propr_config.environment
    client = ProprClient(propr_config)

    try:
        challenge_context = get_active_challenge_context(client)
        if challenge_context is None:
            write_live_status_from_state(
                environment=environment,
                state=None,
                source="poll",
                last_error="no active challenge",
                path=args.output_path,
            )
            print("Live status written (no active challenge).")
            return

        state = sync_agent_state_from_propr(
            client,
            challenge_context.account_id,
        )
        path = write_live_status_from_state(
            environment=environment,
            state=state,
            source="poll",
            path=args.output_path,
        )
        print(f"Live status written to {path}")
    except Exception as exc:
        write_live_status_from_state(
            environment=environment,
            state=None,
            source="poll",
            last_error=str(exc),
            path=args.output_path,
        )
        print(f"Live status sync failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()

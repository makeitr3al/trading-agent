"""Sync account status from Propr API and write live_status.json."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from broker.challenge_service import list_active_challenge_contexts
from broker.propr_client import ProprClient
from broker.state_sync import _get_items, summarize_open_position_rows, sync_agent_state_from_propr
from models.propr_challenge import ActiveChallengeContext
from utils.env_loader import load_propr_config_from_env
from utils.live_status import build_live_status_payload, write_live_status, write_live_status_from_state


def _balance_fields_from_context(ctx: ActiveChallengeContext) -> dict[str, Any]:
    ab = ctx.account_balance
    if ab is None:
        return {
            "challenge_name": ctx.challenge_name,
            "challenge_id": ctx.challenge_id,
            "initial_balance": None,
            "balance": None,
            "margin_balance": None,
            "available_balance": None,
            "high_water_mark": None,
        }
    return {
        "challenge_name": ctx.challenge_name,
        "challenge_id": ctx.challenge_id,
        "initial_balance": ab.initial_balance,
        "balance": ab.balance,
        "margin_balance": ab.margin_balance,
        "available_balance": ab.available_balance,
        "high_water_mark": ab.high_water_mark,
    }


def build_live_status_from_all_active_challenges(
    client: ProprClient,
    environment: str,
) -> dict[str, Any] | None:
    contexts = list_active_challenge_contexts(client)
    if not contexts:
        return None

    if len(contexts) == 1:
        ctx = contexts[0]
        state = sync_agent_state_from_propr(client, ctx.account_id)
        positions = client.get_positions(ctx.account_id)
        summary = summarize_open_position_rows(_get_items(positions))
        overview = [
            {
                "challenge_id": ctx.challenge_id,
                "challenge_name": ctx.challenge_name,
                "account_id": ctx.account_id,
                "account_unrealized_pnl": state.account_unrealized_pnl,
                "account_open_positions_count": state.account_open_positions_count,
                "open_positions_summary": summary,
            }
        ]
        balance = _balance_fields_from_context(ctx)
        return build_live_status_payload(
            environment=environment,
            state=state,
            source="poll",
            open_positions_summary=summary if summary else None,
            challenges_overview=overview,
            active_challenges_count=1,
            **balance,
        )

    overviews: list[dict[str, Any]] = []
    flat_summary: list[dict[str, Any]] = []
    pnl_parts: list[float | None] = []
    total_count = 0
    for ctx in contexts:
        state = sync_agent_state_from_propr(client, ctx.account_id)
        positions = client.get_positions(ctx.account_id)
        summary = summarize_open_position_rows(_get_items(positions))
        pnl_parts.append(state.account_unrealized_pnl)
        total_count += int(state.account_open_positions_count or 0)
        for row in summary:
            flat_summary.append(
                {
                    **row,
                    "challenge_name": ctx.challenge_name,
                    "challenge_id": ctx.challenge_id,
                }
            )
        overviews.append(
            {
                "challenge_id": ctx.challenge_id,
                "challenge_name": ctx.challenge_name,
                "account_id": ctx.account_id,
                "account_unrealized_pnl": state.account_unrealized_pnl,
                "account_open_positions_count": state.account_open_positions_count,
                "open_positions_summary": summary,
            }
        )

    if all(x is None for x in pnl_parts):
        total_pnl: float | None = None
    else:
        total_pnl = float(sum((x or 0.0) for x in pnl_parts))

    return build_live_status_payload(
        environment=environment,
        state=None,
        source="poll",
        account_unrealized_pnl=total_pnl,
        account_open_positions_count=total_count,
        open_positions_summary=flat_summary if flat_summary else None,
        challenges_overview=overviews,
        active_challenges_count=len(contexts),
        challenge_name=None,
        challenge_id=None,
        initial_balance=None,
        balance=None,
        margin_balance=None,
        available_balance=None,
        high_water_mark=None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync live account status from Propr API.")
    parser.add_argument("--output-path", required=True, help="Path to write live_status.json")
    args = parser.parse_args()

    propr_config = load_propr_config_from_env()
    environment = propr_config.environment
    client = ProprClient(propr_config)

    try:
        payload = build_live_status_from_all_active_challenges(client, environment)
        if payload is None:
            write_live_status_from_state(
                environment=environment,
                state=None,
                source="poll",
                last_error="no active challenge",
                path=args.output_path,
            )
            print("Live status written (no active challenge).")
            return

        path = write_live_status(payload, path=args.output_path)
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

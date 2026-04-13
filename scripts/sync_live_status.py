"""Sync account status from Propr API and write live_status.json."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from broker.challenge_service import list_active_challenge_contexts
from broker.propr_client import ProprClient
from broker.state_sync import sync_agent_state_from_propr_with_position_summary
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


def _effective_unrealized_pnl(state: Any, ctx: ActiveChallengeContext) -> float | None:
    if state.account_unrealized_pnl is not None:
        return float(state.account_unrealized_pnl)
    if ctx.account_balance is not None:
        return float(ctx.account_balance.total_unrealized_pnl)
    return None


def _balance_fields_for_overview_row(ctx: ActiveChallengeContext) -> dict[str, Any]:
    b = _balance_fields_from_context(ctx)
    return {
        "initial_balance": b.get("initial_balance"),
        "balance": b.get("balance"),
        "margin_balance": b.get("margin_balance"),
        "available_balance": b.get("available_balance"),
        "high_water_mark": b.get("high_water_mark"),
    }


def _build_challenge_overview_entry(
    ctx: ActiveChallengeContext,
    state: Any,
    summary: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "challenge_id": ctx.challenge_id,
        "challenge_name": ctx.challenge_name,
        "account_id": ctx.account_id,
        "account_unrealized_pnl": _effective_unrealized_pnl(state, ctx),
        "account_open_positions_count": int(state.account_open_positions_count or 0),
        "open_positions_summary": summary,
        **_balance_fields_for_overview_row(ctx),
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
        state, summary = sync_agent_state_from_propr_with_position_summary(client, ctx.account_id)
        eff_pnl = _effective_unrealized_pnl(state, ctx)
        overview = [_build_challenge_overview_entry(ctx, state, summary)]
        balance = _balance_fields_from_context(ctx)
        margin_top = balance.get("margin_balance")
        return build_live_status_payload(
            environment=environment,
            state=state,
            source="poll",
            account_unrealized_pnl=eff_pnl,
            open_positions_summary=summary if summary else None,
            challenges_overview=overview,
            active_challenges_count=1,
            account_total_margin_balance=float(margin_top) if margin_top is not None else None,
            **balance,
        )

    overviews: list[dict[str, Any]] = []
    flat_summary: list[dict[str, Any]] = []
    pnl_parts: list[float] = []
    margin_parts: list[float] = []
    total_count = 0
    for ctx in contexts:
        state, summary = sync_agent_state_from_propr_with_position_summary(client, ctx.account_id)
        row = _build_challenge_overview_entry(ctx, state, summary)
        overviews.append(row)
        total_count += int(row["account_open_positions_count"] or 0)
        eff = row["account_unrealized_pnl"]
        if eff is not None:
            pnl_parts.append(float(eff))
        mb = row.get("margin_balance")
        if mb is not None:
            margin_parts.append(float(mb))
        for srow in summary:
            flat_summary.append(
                {
                    **srow,
                    "challenge_name": ctx.challenge_name,
                    "challenge_id": ctx.challenge_id,
                }
            )

    total_pnl: float | None = float(sum(pnl_parts)) if pnl_parts else None
    total_margin: float | None = float(sum(margin_parts)) if margin_parts else None

    return build_live_status_payload(
        environment=environment,
        state=None,
        source="poll",
        account_unrealized_pnl=total_pnl,
        account_open_positions_count=total_count,
        open_positions_summary=flat_summary if flat_summary else None,
        challenges_overview=overviews,
        active_challenges_count=len(contexts),
        account_total_margin_balance=total_margin,
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

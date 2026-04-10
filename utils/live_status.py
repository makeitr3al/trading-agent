from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from models.agent_state import AgentState


DEFAULT_LIVE_STATUS = {
    "updated_at": None,
    "environment": None,
    "account_unrealized_pnl": None,
    "account_open_positions_count": 0,
    "websocket_connected": False,
    "source": "poll",
    "last_error": None,
    "challenge_name": None,
    "challenge_id": None,
    "initial_balance": None,
    "balance": None,
    "margin_balance": None,
    "available_balance": None,
    "high_water_mark": None,
}


def resolve_live_status_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)

    configured = (os.getenv("TRADING_AGENT_LIVE_STATUS_PATH") or os.getenv("OPERATOR_LIVE_STATUS_PATH") or "").strip()
    if configured:
        return Path(configured)

    data_path = (os.getenv("TRADING_AGENT_DATA_PATH") or "artifacts").strip() or "artifacts"
    return Path(data_path) / "live_status.json"


def _timestamp(value: str | None = None) -> str:
    if value:
        return value
    return datetime.now(timezone.utc).isoformat()


def build_live_status_payload(
    *,
    environment: str | None,
    state: AgentState | None = None,
    websocket_connected: bool = False,
    source: str = "poll",
    last_error: str | None = None,
    updated_at: str | None = None,
    account_unrealized_pnl: float | None = None,
    account_open_positions_count: int | None = None,
    challenge_name: str | None = None,
    challenge_id: str | None = None,
    initial_balance: float | None = None,
    balance: float | None = None,
    margin_balance: float | None = None,
    available_balance: float | None = None,
    high_water_mark: float | None = None,
) -> dict[str, Any]:
    effective_pnl = account_unrealized_pnl
    if effective_pnl is None and state is not None:
        effective_pnl = state.account_unrealized_pnl

    effective_open_positions = account_open_positions_count
    if effective_open_positions is None and state is not None:
        effective_open_positions = state.account_open_positions_count

    return {
        "updated_at": _timestamp(updated_at),
        "environment": environment,
        "account_unrealized_pnl": effective_pnl,
        "account_open_positions_count": int(effective_open_positions or 0),
        "websocket_connected": bool(websocket_connected),
        "source": source,
        "last_error": last_error,
        "challenge_name": challenge_name,
        "challenge_id": challenge_id,
        "initial_balance": initial_balance,
        "balance": balance,
        "margin_balance": margin_balance,
        "available_balance": available_balance,
        "high_water_mark": high_water_mark,
    }


def load_live_status(path: str | Path | None = None) -> dict[str, Any]:
    live_status_path = resolve_live_status_path(path)
    if not live_status_path.exists():
        return dict(DEFAULT_LIVE_STATUS)

    payload = json.loads(live_status_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return dict(DEFAULT_LIVE_STATUS)

    return {
        **DEFAULT_LIVE_STATUS,
        **payload,
    }


def write_live_status(payload: dict[str, Any], path: str | Path | None = None) -> Path:
    live_status_path = resolve_live_status_path(path)
    live_status_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {
        **DEFAULT_LIVE_STATUS,
        **payload,
    }
    live_status_path.write_text(json.dumps(normalized, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return live_status_path


def write_live_status_from_state(
    *,
    environment: str | None,
    state: AgentState | None,
    path: str | Path | None = None,
    websocket_connected: bool = False,
    source: str = "poll",
    last_error: str | None = None,
    updated_at: str | None = None,
) -> Path:
    payload = build_live_status_payload(
        environment=environment,
        state=state,
        websocket_connected=websocket_connected,
        source=source,
        last_error=last_error,
        updated_at=updated_at,
    )
    return write_live_status(payload, path=path)

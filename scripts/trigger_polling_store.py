from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from models.agent_state import AgentState
from scripts.scan_core import ArmedMarketEntry


def resolve_daemon_data_dir() -> Path:
    # In HA add-on this is /share/trading-agent-data via TRADING_AGENT_DATA_PATH.
    raw = (os.getenv("TRADING_AGENT_DATA_PATH") or "").strip()
    return Path(raw) if raw else Path("artifacts")


def sanitize_symbol_for_filename(symbol: str) -> str:
    return (symbol or "").replace("/", "_").replace(":", "_").replace("\\", "_").replace("..", "_")


def armed_markets_path(data_dir: Path | None = None) -> Path:
    base = data_dir or resolve_daemon_data_dir()
    return base / "armed_stop_markets.json"


def agent_state_path(symbol: str, data_dir: Path | None = None) -> Path:
    base = data_dir or resolve_daemon_data_dir()
    return base / f"agent_state_{sanitize_symbol_for_filename(symbol)}.json"


def load_armed_markets(*, data_dir: Path | None = None) -> dict[str, Any] | None:
    path = armed_markets_path(data_dir)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def save_armed_markets(
    *,
    scan_ts: str,
    ttl_hours: int,
    markets: list[ArmedMarketEntry],
    data_dir: Path | None = None,
) -> Path:
    path = armed_markets_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scan_ts": scan_ts,
        "ttl_hours": int(ttl_hours),
        "markets": [asdict(m) for m in markets],
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def parse_armed_markets(payload: dict[str, Any] | None) -> tuple[str | None, int | None, list[ArmedMarketEntry]]:
    if not payload:
        return None, None, []
    scan_ts = payload.get("scan_ts")
    ttl_hours = payload.get("ttl_hours")
    items = payload.get("markets") or []
    markets: list[ArmedMarketEntry] = []
    if isinstance(items, list):
        for raw in items:
            if not isinstance(raw, dict):
                continue
            try:
                markets.append(
                    ArmedMarketEntry(
                        symbol=str(raw.get("symbol") or ""),
                        coin=str(raw.get("coin") or ""),
                        order_type=str(raw.get("order_type") or ""),
                        entry=float(raw.get("entry")),
                        stop_loss=float(raw.get("stop_loss")),
                        take_profit=float(raw.get("take_profit")),
                        signal_source=str(raw.get("signal_source") or ""),
                        selected_signal_type=(raw.get("selected_signal_type") or None),
                        scan_ts=str(raw.get("scan_ts") or scan_ts or ""),
                    )
                )
            except Exception:
                continue
    return str(scan_ts) if scan_ts else None, int(ttl_hours) if ttl_hours is not None else None, markets


def load_agent_state(symbol: str, *, data_dir: Path | None = None) -> AgentState | None:
    path = agent_state_path(symbol, data_dir)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    return AgentState.model_validate(payload)


def save_agent_state(symbol: str, state: AgentState, *, data_dir: Path | None = None) -> Path:
    path = agent_state_path(symbol, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


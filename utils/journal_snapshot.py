from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path
from typing import Any

from utils.operator_config import build_operator_payload, resolve_operator_data_path
from utils.runtime_overrides import get_effective_runtime_value


LEGACY_TRADING_JOURNAL_PATH = "artifacts/trading_journal.jsonl"


def resolve_trading_journal_path() -> Path:
    configured_path = get_effective_runtime_value("TRADING_JOURNAL_PATH")
    if configured_path and configured_path != LEGACY_TRADING_JOURNAL_PATH:
        return Path(configured_path)

    operator_config_path = (os.getenv("TRADING_AGENT_OPERATOR_CONFIG_PATH") or "").strip()
    if operator_config_path or (resolve_operator_data_path() / "operator_config.json").exists():
        operator_payload = build_operator_payload(path=operator_config_path or None)
        return Path(operator_payload["paths"]["journal_path"])

    environment = (get_effective_runtime_value("PROPR_ENV") or "beta").strip().lower() or "beta"
    return Path(f"artifacts/trading_journal_{environment}.jsonl")


def _recent_entries(path: Path, limit: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if limit <= 0:
        return [], {"entry_count": 0, "cycle_count": 0, "order_count": 0, "trade_count": 0}

    entries: deque[dict[str, Any]] = deque(maxlen=limit)
    counters = {"entry_count": 0, "cycle_count": 0, "order_count": 0, "trade_count": 0}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            entry = json.loads(stripped)
            counters["entry_count"] += 1
            if entry.get("entry_type") == "cycle":
                counters["cycle_count"] += 1
            elif entry.get("entry_type") == "order":
                counters["order_count"] += 1
            elif entry.get("entry_type") == "trade":
                counters["trade_count"] += 1
            entries.append(entry)
    return list(entries), counters


def _compact_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_type": entry.get("entry_type"),
        "entry_date": entry.get("entry_date"),
        "entry_timestamp": entry.get("entry_timestamp"),
        "symbol": entry.get("symbol"),
        "environment": entry.get("environment"),
        "decision_action": entry.get("decision_action"),
        "skipped_reason": entry.get("skipped_reason"),
        "direction": entry.get("direction"),
        "position_size": entry.get("position_size"),
        "status": entry.get("status"),
        "pnl": entry.get("pnl"),
        "source_signal_type": entry.get("source_signal_type"),
        "fill_timestamp": entry.get("fill_timestamp"),
        "close_timestamp": entry.get("close_timestamp"),
        "notes": entry.get("notes"),
    }


def build_journal_snapshot(path: str | Path | None = None, tail_limit: int = 10) -> dict[str, Any]:
    journal_path = Path(path) if path is not None else resolve_trading_journal_path()
    snapshot: dict[str, Any] = {
        "journal_path": str(journal_path),
        "exists": journal_path.exists(),
        "entry_count": 0,
        "cycle_count": 0,
        "order_count": 0,
        "trade_count": 0,
        "latest_entry_timestamp": None,
        "latest_cycle_action": None,
        "latest_cycle_skipped_reason": None,
        "latest_order_status": None,
        "latest_order_direction": None,
        "latest_trade_status": None,
        "latest_trade_direction": None,
        "latest_trade_pnl": None,
        "recent_entries": [],
    }

    if not journal_path.exists():
        return snapshot

    recent_entries, counters = _recent_entries(journal_path, tail_limit)
    snapshot["recent_entries"] = [_compact_entry(entry) for entry in recent_entries]
    snapshot.update(counters)
    if recent_entries:
        snapshot["latest_entry_timestamp"] = recent_entries[-1].get("entry_timestamp")

    cycle_entries = [entry for entry in recent_entries if entry.get("entry_type") == "cycle"]
    order_entries = [entry for entry in recent_entries if entry.get("entry_type") == "order"]
    trade_entries = [entry for entry in recent_entries if entry.get("entry_type") == "trade"]

    if cycle_entries:
        latest_cycle = cycle_entries[-1]
        snapshot["latest_cycle_action"] = latest_cycle.get("decision_action")
        snapshot["latest_cycle_skipped_reason"] = latest_cycle.get("skipped_reason")

    if order_entries:
        latest_order = order_entries[-1]
        snapshot["latest_order_status"] = latest_order.get("status")
        snapshot["latest_order_direction"] = latest_order.get("direction")

    if trade_entries:
        latest_trade = trade_entries[-1]
        snapshot["latest_trade_status"] = latest_trade.get("status")
        snapshot["latest_trade_direction"] = latest_trade.get("direction")
        snapshot["latest_trade_pnl"] = latest_trade.get("pnl")

    return snapshot

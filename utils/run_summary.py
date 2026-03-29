from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None

    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def _load_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}

    resolved = Path(path)
    if not resolved.exists():
        return {}

    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _iter_journal_entries(path: str | Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []

    resolved = Path(path)
    if not resolved.exists():
        return []

    entries: list[dict[str, Any]] = []
    with resolved.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                entries.append(payload)
    return entries


def _entries_for_window(path: str | Path | None, started_at: str, finished_at: str) -> list[dict[str, Any]]:
    started_dt = _parse_iso8601(started_at)
    finished_dt = _parse_iso8601(finished_at)
    if started_dt is None or finished_dt is None:
        return []

    matching: list[dict[str, Any]] = []
    for entry in _iter_journal_entries(path):
        entry_dt = _parse_iso8601(str(entry.get("entry_timestamp") or ""))
        if entry_dt is None:
            continue
        if started_dt <= entry_dt <= finished_dt:
            matching.append(entry)
    return matching


def _format_counts(counter: Counter[str]) -> str:
    parts = [f"{key}={value}" for key, value in sorted(counter.items()) if key]
    return ", ".join(parts) if parts else "keine"


def _friendly_mode_name(mode: str) -> str:
    return {
        "scharf": "Scharf-Lauf",
        "preflight": "Preflight-Test",
        "beta_write": "Beta-Write-Test",
    }.get((mode or "").strip().lower(), mode or "Unbekannter Lauf")


def _build_test_run_summary(
    *,
    mode: str,
    environment: str,
    started_at: str,
    finished_at: str,
    exit_code: int,
    test_status_path: str | Path | None,
) -> dict[str, Any]:
    status_payload = _load_json(test_status_path)
    success = bool(status_payload.get("success")) if status_payload else exit_code == 0
    suite_name = str(status_payload.get("suite") or mode)
    last_error = str(status_payload.get("last_error") or "").strip() or None
    failed_step = next(
        (step for step in status_payload.get("steps", []) if isinstance(step, dict) and not step.get("success")),
        None,
    )

    summary_lines = [
        f"Modus: {_friendly_mode_name(mode)}",
        f"Umgebung: {environment}",
        f"Ergebnis: {'erfolgreich' if success else 'fehlgeschlagen'}",
    ]
    if failed_step is not None:
        summary_lines.append(f"Fehlgeschritt: {failed_step.get('name')}")
    if last_error:
        summary_lines.append(f"Grund: {last_error}")

    title = f"{_friendly_mode_name(mode)} {'erfolgreich' if success else 'fehlgeschlagen'}"
    notification_message = (
        f"{_friendly_mode_name(mode)} ({environment}) {'erfolgreich' if success else 'fehlgeschlagen'}."
    )
    if failed_step is not None:
        notification_message += f" Fehlgeschritt: {failed_step.get('name')}."
    if last_error:
        notification_message += f" {last_error}."

    return {
        "run_id": finished_at,
        "mode": mode,
        "environment": environment,
        "started_at": started_at,
        "finished_at": finished_at,
        "success": success,
        "exit_code": exit_code,
        "suite": suite_name,
        "entry_count": 0,
        "cycle_count": 0,
        "order_count": 0,
        "trade_count": 0,
        "symbols": [],
        "latest_symbol": None,
        "latest_outcome": None,
        "title": title,
        "notification_title": f"Trading Agent: {title}",
        "notification_message": notification_message.strip(),
        "summary_lines": summary_lines,
    }


def _build_live_run_summary(
    *,
    mode: str,
    environment: str,
    started_at: str,
    finished_at: str,
    exit_code: int,
    journal_path: str | Path | None,
) -> dict[str, Any]:
    entries = _entries_for_window(journal_path, started_at, finished_at)
    cycle_entries = [entry for entry in entries if entry.get("entry_type") == "cycle"]
    order_entries = [entry for entry in entries if entry.get("entry_type") == "order"]
    trade_entries = [entry for entry in entries if entry.get("entry_type") == "trade"]
    symbols = sorted({str(entry.get("symbol")) for entry in entries if entry.get("symbol")})
    latest_entry = entries[-1] if entries else None

    cycle_actions = Counter(
        str(entry.get("decision_action"))
        for entry in cycle_entries
        if entry.get("decision_action") and entry.get("decision_action") != "NO_ACTION"
    )
    order_statuses = Counter(str(entry.get("status")) for entry in order_entries if entry.get("status"))
    trade_statuses = Counter(str(entry.get("status")) for entry in trade_entries if entry.get("status"))
    skipped_reasons = Counter(str(entry.get("skipped_reason")) for entry in cycle_entries if entry.get("skipped_reason"))

    success = exit_code == 0
    title = f"Scharf-Lauf {'abgeschlossen' if success else 'fehlgeschlagen'}"
    latest_outcome = None
    if latest_entry is not None:
        latest_outcome = latest_entry.get("status") or latest_entry.get("decision_action")

    summary_lines = [
        f"Modus: {_friendly_mode_name(mode)}",
        f"Umgebung: {environment}",
        f"Ergebnis: {'erfolgreich' if success else 'fehlgeschlagen'}",
        f"Maerkte im Lauf: {', '.join(symbols) if symbols else 'keine'}",
        f"Cycle-Aktionen: {_format_counts(cycle_actions)}",
        f"Order-Status: {_format_counts(order_statuses)}",
        f"Trade-Status: {_format_counts(trade_statuses)}",
    ]
    if skipped_reasons:
        summary_lines.append(f"Skip-Gruende: {_format_counts(skipped_reasons)}")
    if latest_entry is not None:
        latest_symbol = latest_entry.get("symbol") or "-"
        summary_lines.append(f"Letzter Eintrag: {latest_symbol} | {latest_outcome or '-'}")

    notification_message = (
        f"Scharf-Lauf ({environment}) {'abgeschlossen' if success else 'fehlgeschlagen'}."
        f" Maerkte: {len(symbols)}."
        f" Orders: {_format_counts(order_statuses)}."
        f" Trades: {_format_counts(trade_statuses)}."
    )
    if latest_entry is not None:
        notification_message += (
            f" Letzter Eintrag: {(latest_entry.get('symbol') or '-')}"
            f" / {(latest_outcome or '-')}."
        )

    return {
        "run_id": finished_at,
        "mode": mode,
        "environment": environment,
        "started_at": started_at,
        "finished_at": finished_at,
        "success": success,
        "exit_code": exit_code,
        "suite": None,
        "entry_count": len(entries),
        "cycle_count": len(cycle_entries),
        "order_count": len(order_entries),
        "trade_count": len(trade_entries),
        "symbols": symbols,
        "latest_symbol": latest_entry.get("symbol") if latest_entry is not None else None,
        "latest_outcome": latest_outcome,
        "title": title,
        "notification_title": f"Trading Agent: {title}",
        "notification_message": notification_message.strip(),
        "summary_lines": summary_lines,
    }


def build_run_summary(
    *,
    mode: str,
    environment: str,
    started_at: str,
    finished_at: str,
    exit_code: int,
    journal_path: str | Path | None = None,
    test_status_path: str | Path | None = None,
) -> dict[str, Any]:
    normalized_mode = (mode or "").strip().lower()
    if normalized_mode in {"preflight", "beta_write"}:
        return _build_test_run_summary(
            mode=normalized_mode,
            environment=environment,
            started_at=started_at,
            finished_at=finished_at,
            exit_code=exit_code,
            test_status_path=test_status_path,
        )

    return _build_live_run_summary(
        mode=normalized_mode,
        environment=environment,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        journal_path=journal_path,
    )

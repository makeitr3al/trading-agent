from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.journal_snapshot import resolve_trading_journal_path


JOURNAL_WARNING_ROW_THRESHOLD = 10_000
JOURNAL_WARNING_BYTES_THRESHOLD = 5_000_000


def _iter_journal_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                entries.append(
                    {
                        "entry_type": "invalid",
                        "entry_timestamp": None,
                        "entry_date": None,
                        "symbol": None,
                        "environment": None,
                        "status": "invalid_json",
                        "notes": f"Zeile {line_number} konnte nicht gelesen werden",
                    }
                )
                continue
            if isinstance(payload, dict):
                entries.append(payload)
    return entries


def _group_key(entry: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (
        entry.get("entry_timestamp"),
        entry.get("symbol"),
        entry.get("environment"),
    )


def _join_distinct(values: list[str | None]) -> str | None:
    normalized = [str(value).strip() for value in values if value not in {None, ""}]
    distinct = list(dict.fromkeys(normalized))
    if not distinct:
        return None
    return ", ".join(distinct)


def _format_signal_list(values: list[Any]) -> str | None:
    if not values:
        return None

    rendered: list[str] = []
    for value in values:
        if isinstance(value, dict):
            signal_type = value.get("signal_type")
            reason = value.get("reason")
            is_valid = value.get("is_valid")
            if signal_type and reason and is_valid is not None:
                rendered.append(f"{signal_type} ({'valid' if is_valid else 'invalid'}: {reason})")
            elif signal_type:
                rendered.append(str(signal_type))
        elif value not in {None, ""}:
            rendered.append(str(value))

    distinct = list(dict.fromkeys(rendered))
    if not distinct:
        return None
    return " | ".join(distinct)


def _build_scan_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_orders: dict[tuple[str | None, str | None, str | None], list[dict[str, Any]]] = {}
    grouped_trades: dict[tuple[str | None, str | None, str | None], list[dict[str, Any]]] = {}

    for entry in entries:
        key = _group_key(entry)
        if entry.get("entry_type") == "order":
            grouped_orders.setdefault(key, []).append(entry)
        elif entry.get("entry_type") == "trade":
            grouped_trades.setdefault(key, []).append(entry)

    scan_rows: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("entry_type") != "cycle":
            continue

        key = _group_key(entry)
        related_orders = grouped_orders.get(key, [])
        related_trades = grouped_trades.get(key, [])
        order_statuses = [order.get("status") for order in related_orders]
        trade_statuses = [trade.get("status") for trade in related_trades]
        trade_pnls = [
            trade.get("pnl")
            for trade in related_trades
            if trade.get("pnl") is not None
        ]

        scan_rows.append(
            {
                "timestamp": entry.get("entry_timestamp"),
                "entry_date": entry.get("entry_date"),
                "symbol": entry.get("symbol"),
                "environment": entry.get("environment"),
                "decision_action": entry.get("decision_action"),
                "selected_signal_type": _join_distinct(entry.get("used_signals") or []),
                "received_signals": _format_signal_list(entry.get("received_signals") or []),
                "unused_signals": _format_signal_list(entry.get("unused_signals") or []),
                "order_created": bool(related_orders),
                "order_status_summary": _join_distinct(order_statuses),
                "trade_status_summary": _join_distinct(trade_statuses),
                "trade_pnl_summary": _join_distinct([str(pnl) for pnl in trade_pnls]),
                "skip_reason": entry.get("skipped_reason"),
                "notes": entry.get("notes"),
                "related_order_count": len(related_orders),
                "related_trade_count": len(related_trades),
            }
        )

    return sorted(
        scan_rows,
        key=lambda row: (row.get("timestamp") or "", row.get("symbol") or ""),
        reverse=True,
    )


def _build_trade_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trade_rows: list[dict[str, Any]] = []
    for entry in entries:
        entry_type = entry.get("entry_type")
        if entry_type not in {"order", "trade"}:
            continue
        trade_rows.append(
            {
                "timestamp": entry.get("entry_timestamp"),
                "entry_date": entry.get("entry_date"),
                "entry_type": entry_type,
                "symbol": entry.get("symbol"),
                "environment": entry.get("environment"),
                "status": entry.get("status"),
                "direction": entry.get("direction"),
                "source_signal_type": entry.get("source_signal_type"),
                "position_size": entry.get("position_size"),
                "pnl": entry.get("pnl"),
                "fill_timestamp": entry.get("fill_timestamp"),
                "close_timestamp": entry.get("close_timestamp"),
                "notes": entry.get("notes"),
            }
        )
    return sorted(
        trade_rows,
        key=lambda row: (
            row.get("timestamp") or "",
            row.get("symbol") or "",
            1 if row.get("entry_type") == "trade" else 0,
        ),
        reverse=True,
    )


def _filter_options(scan_rows: list[dict[str, Any]], trade_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    all_rows = [*scan_rows, *trade_rows]
    return {
        "symbols": sorted({str(row["symbol"]) for row in all_rows if row.get("symbol")}),
        "environments": sorted({str(row["environment"]) for row in all_rows if row.get("environment")}),
        "decision_actions": sorted({str(row["decision_action"]) for row in scan_rows if row.get("decision_action")}),
        "scan_signals": sorted({str(row["selected_signal_type"]) for row in scan_rows if row.get("selected_signal_type")}),
        "entry_types": sorted({str(row["entry_type"]) for row in trade_rows if row.get("entry_type")}),
        "trade_statuses": sorted({str(row["status"]) for row in trade_rows if row.get("status")}),
        "directions": sorted({str(row["direction"]) for row in trade_rows if row.get("direction")}),
        "signal_sources": sorted({str(row["source_signal_type"]) for row in trade_rows if row.get("source_signal_type")}),
    }


def build_journal_table(path: str | Path | None = None) -> dict[str, Any]:
    journal_path = Path(path) if path is not None else resolve_trading_journal_path()
    payload: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_entry_timestamp": None,
        "journal_path": str(journal_path),
        "exists": journal_path.exists(),
        "entry_count_total": 0,
        "scan_rows": [],
        "trade_rows": [],
        "filter_options": {
            "symbols": [],
            "environments": [],
            "decision_actions": [],
            "scan_signals": [],
            "entry_types": [],
            "trade_statuses": [],
            "directions": [],
            "signal_sources": [],
        },
        "warnings": [],
    }
    if not journal_path.exists():
        return payload

    entries = _iter_journal_entries(journal_path)
    scan_rows = _build_scan_rows(entries)
    trade_rows = _build_trade_rows(entries)
    payload["latest_entry_timestamp"] = max(
        (
            str(entry.get("entry_timestamp"))
            for entry in entries
            if entry.get("entry_timestamp")
        ),
        default=None,
    )
    payload["entry_count_total"] = len(entries)
    payload["scan_rows"] = scan_rows
    payload["trade_rows"] = trade_rows
    payload["filter_options"] = _filter_options(scan_rows, trade_rows)

    payload_bytes = len(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    if len(entries) > JOURNAL_WARNING_ROW_THRESHOLD:
        payload["warnings"].append(
            f"Journal umfasst {len(entries)} Eintraege. Die Tabelle bleibt vollstaendig, kann aber groesser werden."
        )
    if payload_bytes > JOURNAL_WARNING_BYTES_THRESHOLD:
        payload["warnings"].append(
            f"Journal-Export ist derzeit {payload_bytes} Bytes gross. Die Anzeige bleibt vollstaendig, kann aber langsamer werden."
        )
    return payload





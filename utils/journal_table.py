from __future__ import annotations

import json
from collections import defaultdict
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


def _derive_signal_type(selected_signal_type: str | None) -> str:
    if not selected_signal_type:
        return "Kein Signal"
    upper = selected_signal_type.upper()
    if upper.startswith("TREND_"):
        return "Trend"
    if upper.startswith("COUNTERTREND_"):
        return "Gegentrend"
    return "Kein Signal"


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

        # Pull entry/fill/close info from related order + trade
        first_order = related_orders[0] if related_orders else None
        first_trade = related_trades[0] if related_trades else None
        closed_trade = next((t for t in related_trades if t.get("status") == "closed"), None)

        selected_signal_type = _join_distinct(entry.get("used_signals") or [])

        received_raw = entry.get("received_signals") or []
        valid_signals_count = sum(
            1
            for item in received_raw
            if isinstance(item, dict) and item.get("is_valid") is True
        )

        scan_rows.append(
            {
                "timestamp": entry.get("entry_timestamp"),
                "entry_date": entry.get("entry_date"),
                "symbol": entry.get("symbol"),
                "environment": entry.get("environment"),
                "decision_action": entry.get("decision_action"),
                "selected_signal_type": selected_signal_type,
                "received_signals": _format_signal_list(received_raw),
                "valid_signals_count": valid_signals_count,
                "unused_signals": _format_signal_list(entry.get("unused_signals") or []),
                "scan_effective_submit_allowed": entry.get("scan_effective_submit_allowed"),
                "scan_cycle_phase": entry.get("scan_cycle_phase"),
                "order_created": bool(related_orders),
                "order_status_summary": _join_distinct(order_statuses),
                "trade_status_summary": _join_distinct(trade_statuses),
                "trade_pnl_summary": _join_distinct([str(pnl) for pnl in trade_pnls]),
                "skip_reason": entry.get("skipped_reason"),
                "notes": entry.get("notes"),
                "related_order_count": len(related_orders),
                "related_trade_count": len(related_trades),
                # Additive fields (Step 12):
                "executed_at": entry.get("executed_at"),
                "signal_type": _derive_signal_type(selected_signal_type),
                "entry_price": first_order.get("entry_price") if first_order else None,
                "fill_time": first_trade.get("fill_timestamp") if first_trade else None,
                "tp": first_order.get("take_profit") if first_order else None,
                "sl": first_order.get("stop_loss") if first_order else None,
                "exit_price": closed_trade.get("close_price") if closed_trade else None,
                "exit_time": closed_trade.get("close_timestamp") if closed_trade else None,
            }
        )

    return sorted(
        scan_rows,
        key=lambda row: (row.get("executed_at") or row.get("timestamp") or "", row.get("symbol") or ""),
        reverse=True,
    )


def _entry_sort_key(entry: dict[str, Any]) -> str:
    return str(entry.get("executed_at") or entry.get("entry_timestamp") or "")


def _lifecycle_phase_from_entries(group: list[dict[str, Any]]) -> str:
    has_closed = any(e.get("entry_type") == "trade" and e.get("status") == "closed" for e in group)
    if has_closed:
        return "closed"
    has_filled = any(e.get("entry_type") == "trade" and e.get("status") == "filled" for e in group)
    if has_filled:
        return "open"
    has_order = any(e.get("entry_type") == "order" for e in group)
    if has_order:
        return "pending_order"
    return "signal_only"


def _lifecycle_steps(group: list[dict[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for entry in sorted(group, key=_entry_sort_key):
        et = entry.get("entry_type")
        ts = entry.get("executed_at") or entry.get("entry_timestamp")
        if et == "cycle":
            steps.append(
                {
                    "step": "signal",
                    "at": ts,
                    "decision_action": entry.get("decision_action"),
                    "received_signals": _format_signal_list(entry.get("received_signals") or []),
                    "notes": entry.get("notes"),
                }
            )
        elif et == "order":
            steps.append(
                {
                    "step": "order",
                    "at": ts,
                    "status": entry.get("status"),
                    "direction": entry.get("direction"),
                    "entry_price": entry.get("entry_price"),
                    "stop_loss": entry.get("stop_loss"),
                    "take_profit": entry.get("take_profit"),
                    "notes": entry.get("notes"),
                }
            )
        elif et == "trade" and entry.get("status") == "filled":
            steps.append(
                {
                    "step": "fill",
                    "at": ts,
                    "direction": entry.get("direction"),
                    "position_size": entry.get("position_size"),
                    "entry_price": entry.get("entry_price"),
                    "stop_loss": entry.get("stop_loss"),
                    "take_profit": entry.get("take_profit"),
                    "notes": entry.get("notes"),
                }
            )
        elif et == "trade_management":
            steps.append(
                {
                    "step": "trade_management",
                    "at": ts,
                    "status": entry.get("status"),
                    "stop_loss": entry.get("stop_loss"),
                    "take_profit": entry.get("take_profit"),
                    "notes": entry.get("notes"),
                }
            )
        elif et == "trade" and entry.get("status") == "closed":
            steps.append(
                {
                    "step": "exit",
                    "at": ts,
                    "close_price": entry.get("close_price"),
                    "pnl": entry.get("pnl"),
                    "notes": entry.get("notes"),
                }
            )
    return steps


def _build_lifecycle_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        et = entry.get("entry_type")
        if et not in {"cycle", "order", "trade", "trade_management"}:
            continue
        sid = entry.get("signal_lifecycle_id")
        if not sid or not str(sid).strip():
            continue
        groups[str(sid).strip()].append(entry)

    rows: list[dict[str, Any]] = []
    for sid, group in groups.items():
        group_sorted = sorted(group, key=_entry_sort_key, reverse=True)
        group_chrono = list(reversed(group_sorted))
        steps = _lifecycle_steps(group_chrono)
        first_cycle = next((e for e in group_chrono if e.get("entry_type") == "cycle"), None)
        source_signal = next(
            (e.get("source_signal_type") for e in group_chrono if e.get("source_signal_type")),
            None,
        )
        filled = next((e for e in group_chrono if e.get("entry_type") == "trade" and e.get("status") == "filled"), None)
        closed = next((e for e in reversed(group_chrono) if e.get("entry_type") == "trade" and e.get("status") == "closed"), None)
        last_mgmt = next(
            (e for e in reversed(group_chrono) if e.get("entry_type") == "trade_management"),
            None,
        )
        last_order = next((e for e in reversed(group_chrono) if e.get("entry_type") == "order"), None)
        management_count = sum(1 for e in group_chrono if e.get("entry_type") == "trade_management")
        sort_ts = max((_entry_sort_key(e) for e in group), default="")
        rows.append(
            {
                "signal_lifecycle_id": sid,
                "sort_timestamp": sort_ts,
                "symbol": group_chrono[0].get("symbol") if group_chrono else None,
                "environment": group_chrono[0].get("environment") if group_chrono else None,
                "source_signal_type": source_signal,
                "phase": _lifecycle_phase_from_entries(group_chrono),
                "signal_summary": _format_signal_list(first_cycle.get("received_signals") or []) if first_cycle else None,
                "decision_action": first_cycle.get("decision_action") if first_cycle else None,
                "order_status": last_order.get("status") if last_order else None,
                "fill_timestamp": filled.get("fill_timestamp") if filled else None,
                "close_timestamp": closed.get("close_timestamp") if closed else None,
                "pnl": closed.get("pnl") if closed else None,
                "stop_loss": (last_mgmt or filled or last_order or {}).get("stop_loss"),
                "take_profit": (last_mgmt or filled or last_order or {}).get("take_profit"),
                "management_count": management_count,
                "steps": steps,
            }
        )

    return sorted(rows, key=lambda r: (r.get("sort_timestamp") or "", r.get("symbol") or ""), reverse=True)


def _build_trade_rows(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trade_rows: list[dict[str, Any]] = []
    for entry in entries:
        entry_type = entry.get("entry_type")
        if entry_type not in {"order", "trade", "trade_management"}:
            continue
        trade_rows.append(
            {
                "timestamp": entry.get("executed_at") or entry.get("entry_timestamp"),
                "entry_date": entry.get("entry_date"),
                "entry_type": entry_type,
                "symbol": entry.get("symbol"),
                "environment": entry.get("environment"),
                "status": entry.get("status"),
                "direction": entry.get("direction"),
                "source_signal_type": entry.get("source_signal_type"),
                "position_size": entry.get("position_size"),
                "entry_price": entry.get("entry_price"),
                "stop_loss": entry.get("stop_loss"),
                "take_profit": entry.get("take_profit"),
                "close_price": entry.get("close_price"),
                "lifecycle_id": entry.get("lifecycle_id"),
                "signal_lifecycle_id": entry.get("signal_lifecycle_id"),
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


def _filter_options(
    scan_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    lifecycle_rows: list[dict[str, Any]] | None = None,
) -> dict[str, list[str]]:
    lifecycle_rows = lifecycle_rows or []
    all_rows = [*scan_rows, *trade_rows]
    return {
        "symbols": sorted({str(row["symbol"]) for row in all_rows if row.get("symbol")}),
        "environments": sorted({str(row["environment"]) for row in all_rows if row.get("environment")}),
        "decision_actions": sorted({str(row["decision_action"]) for row in scan_rows if row.get("decision_action")}),
        "scan_signals": sorted({str(row["selected_signal_type"]) for row in scan_rows if row.get("selected_signal_type")}),
        "signal_types": sorted({str(row["signal_type"]) for row in scan_rows if row.get("signal_type")}),
        "entry_types": sorted({str(row["entry_type"]) for row in trade_rows if row.get("entry_type")}),
        "trade_statuses": sorted({str(row["status"]) for row in trade_rows if row.get("status")}),
        "directions": sorted({str(row["direction"]) for row in trade_rows if row.get("direction")}),
        "signal_sources": sorted({str(row["source_signal_type"]) for row in trade_rows if row.get("source_signal_type")}),
        "lifecycle_phases": sorted({str(row["phase"]) for row in lifecycle_rows if row.get("phase")}),
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
        "lifecycle_rows": [],
        "filter_options": {
            "symbols": [],
            "environments": [],
            "decision_actions": [],
            "scan_signals": [],
            "signal_types": [],
            "entry_types": [],
            "trade_statuses": [],
            "directions": [],
            "signal_sources": [],
            "lifecycle_phases": [],
        },
        "warnings": [],
    }
    if not journal_path.exists():
        return payload

    entries = _iter_journal_entries(journal_path)
    scan_rows = _build_scan_rows(entries)
    trade_rows = _build_trade_rows(entries)
    lifecycle_rows = _build_lifecycle_rows(entries)
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
    payload["lifecycle_rows"] = lifecycle_rows
    payload["filter_options"] = _filter_options(scan_rows, trade_rows, lifecycle_rows)

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

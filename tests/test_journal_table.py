from __future__ import annotations

import json
from pathlib import Path

from utils.journal_table import build_journal_table


def test_build_journal_table_splits_scan_and_trade_rows(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    entries = [
        {
            "entry_type": "cycle",
            "entry_date": "2026-03-29",
            "entry_timestamp": "2026-03-29T08:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "decision_action": "PREPARE_TREND_ORDER",
            "used_signals": ["TREND_LONG"],
            "received_signals": [{"signal_type": "TREND_LONG", "is_valid": True, "reason": "trend signal detected"}],
            "unused_signals": [{"signal_type": "COUNTERTREND_SHORT", "reason": "not selected"}],
            "notes": "cycle note",
        },
        {
            "entry_type": "order",
            "entry_date": "2026-03-29",
            "entry_timestamp": "2026-03-29T08:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "status": "submitted",
            "direction": "long",
            "source_signal_type": "TREND_LONG",
            "position_size": 0.25,
            "notes": "pending order",
        },
        {
            "entry_type": "trade",
            "entry_date": "2026-03-29",
            "entry_timestamp": "2026-03-29T08:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "status": "filled",
            "direction": "long",
            "source_signal_type": "TREND_LONG",
            "position_size": 0.25,
            "fill_timestamp": "2026-03-29T08:05:00+00:00",
            "notes": "filled trade",
        },
    ]
    journal_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")

    payload = build_journal_table(path=journal_path)

    assert payload["entry_count_total"] == 3
    # scan_rows is flat: one per-market row per cycle
    assert len(payload["scan_rows"]) == 1
    row = payload["scan_rows"][0]
    assert row["symbol"] == "BTC/USDC"
    assert row["order_created"] is True
    assert row["order_status_summary"] == "submitted"
    assert row["trade_status_summary"] == "filled"
    assert row["decision_action"] == "PREPARE_TREND_ORDER"
    assert row["selected_signal_type"] == "TREND_LONG"
    assert row["signal_type"] == "Trend"
    assert row["notes"] == "cycle note"
    assert row["related_order_count"] == 1
    assert row["related_trade_count"] == 1
    assert len(payload["trade_rows"]) == 2
    assert payload["trade_rows"][0]["entry_type"] == "trade"
    assert payload["trade_rows"][1]["entry_type"] == "order"
    assert payload["filter_options"]["symbols"] == ["BTC/USDC"]
    assert "signal_types" in payload["filter_options"]
    assert "scan_signals" in payload["filter_options"]
    assert payload["lifecycle_rows"] == []
    assert payload["filter_options"].get("lifecycle_phases") == []


def test_build_journal_table_lifecycle_rows_grouped_by_signal_lifecycle_id(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    sid = "01HZTESTLIFECYCLE01"
    entries = [
        {
            "entry_type": "cycle",
            "entry_date": "2026-03-29",
            "entry_timestamp": "2026-03-29T08:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "decision_action": "PREPARE_TREND_ORDER",
            "used_signals": ["TREND_LONG"],
            "received_signals": [{"signal_type": "TREND_LONG", "is_valid": True, "reason": "ok"}],
            "notes": "prep",
            "signal_lifecycle_id": sid,
        },
        {
            "entry_type": "order",
            "entry_date": "2026-03-29",
            "entry_timestamp": "2026-03-29T08:00:01+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "status": "submitted",
            "direction": "long",
            "source_signal_type": "TREND_LONG",
            "signal_lifecycle_id": sid,
        },
        {
            "entry_type": "trade",
            "entry_date": "2026-03-29",
            "entry_timestamp": "2026-03-29T08:05:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "status": "filled",
            "direction": "long",
            "source_signal_type": "TREND_LONG",
            "fill_timestamp": "2026-03-29T08:05:00+00:00",
            "signal_lifecycle_id": sid,
        },
        {
            "entry_type": "trade_management",
            "entry_date": "2026-03-29",
            "entry_timestamp": "2026-03-29T09:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "status": "managed",
            "direction": "long",
            "stop_loss": 98.0,
            "take_profit": 112.0,
            "notes": "exit orders updated",
            "signal_lifecycle_id": sid,
        },
        {
            "entry_type": "trade",
            "entry_date": "2026-03-29",
            "entry_timestamp": "2026-03-29T10:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "status": "closed",
            "direction": "long",
            "close_timestamp": "2026-03-29T10:00:00+00:00",
            "pnl": 1.5,
            "signal_lifecycle_id": sid,
        },
    ]
    journal_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")

    payload = build_journal_table(path=journal_path)

    assert len(payload["lifecycle_rows"]) == 1
    lr = payload["lifecycle_rows"][0]
    assert lr["signal_lifecycle_id"] == sid
    assert lr["phase"] == "closed"
    assert lr["management_count"] == 1
    assert lr["pnl"] == 1.5
    assert len(lr["steps"]) >= 4
    assert "lifecycle_phases" in payload["filter_options"]


def test_build_journal_table_warns_for_large_entry_count(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    entries = [
        {
            "entry_type": "cycle",
            "entry_date": "2026-03-29",
            "entry_timestamp": f"2026-03-29T08:{index // 60:02d}:{index % 60:02d}+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "decision_action": "NO_ACTION",
        }
        for index in range(10_001)
    ]
    journal_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")

    payload = build_journal_table(path=journal_path)

    assert payload["entry_count_total"] == 10_001
    assert payload["warnings"]

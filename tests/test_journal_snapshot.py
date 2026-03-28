from pathlib import Path
import json
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.journal_snapshot import build_journal_snapshot


def test_build_journal_snapshot_returns_compact_summary(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    entries = [
        {
            "entry_type": "cycle",
            "entry_timestamp": "2026-03-28T10:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "decision_action": "PREPARE_TREND_ORDER",
            "skipped_reason": None,
            "notes": "trend signal accepted",
        },
        {
            "entry_type": "order",
            "entry_timestamp": "2026-03-28T10:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "direction": "LONG",
            "status": "submitted",
            "notes": "pending order via trend_long",
        },
        {
            "entry_type": "trade",
            "entry_timestamp": "2026-03-28T11:00:00+00:00",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "direction": "LONG",
            "status": "closed",
            "pnl": 42.5,
            "notes": "active trade close executed",
        },
    ]
    journal_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")

    snapshot = build_journal_snapshot(path=journal_path, tail_limit=10)

    assert snapshot["exists"] is True
    assert snapshot["entry_count"] == 3
    assert snapshot["cycle_count"] == 1
    assert snapshot["order_count"] == 1
    assert snapshot["trade_count"] == 1
    assert snapshot["latest_cycle_action"] == "PREPARE_TREND_ORDER"
    assert snapshot["latest_order_status"] == "submitted"
    assert snapshot["latest_trade_status"] == "closed"
    assert snapshot["latest_trade_pnl"] == 42.5
    assert len(snapshot["recent_entries"]) == 3


def test_build_journal_snapshot_uses_operator_config_data_path(tmp_path: Path, monkeypatch) -> None:
    data_path = tmp_path / 'trading-agent-data'
    data_path.mkdir(parents=True, exist_ok=True)
    operator_config_path = data_path / 'operator_config.json'
    operator_config_path.write_text(
        json.dumps(
            {
                'mode': 'scharf',
                'environment': 'beta',
                'leverage': 1,
                'markets': 'BTC/USDC:BTC',
                'scheduling_enabled': False,
                'schedule_time': '07:00',
            }
        ) + '\n',
        encoding='utf-8',
    )
    journal_path = data_path / 'trading_journal_beta.jsonl'
    journal_path.write_text(json.dumps({'entry_type': 'cycle', 'entry_timestamp': '2026-03-28T10:00:00+00:00', 'decision_action': 'NO_ACTION'}) + '\n', encoding='utf-8')

    monkeypatch.delenv('TRADING_JOURNAL_PATH', raising=False)
    monkeypatch.setenv('TRADING_AGENT_DATA_PATH', str(data_path))
    monkeypatch.setenv('TRADING_AGENT_OPERATOR_CONFIG_PATH', str(operator_config_path))

    snapshot = build_journal_snapshot(tail_limit=5)

    assert snapshot['exists'] is True
    assert snapshot['journal_path'] == str(journal_path)
    assert snapshot['latest_cycle_action'] == 'NO_ACTION'

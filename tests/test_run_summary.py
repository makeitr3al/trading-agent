from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.run_summary import build_run_summary


def test_build_run_summary_for_preflight_reads_test_status(tmp_path: Path) -> None:
    status_path = tmp_path / "test_suite_status.json"
    status_path.write_text(
        json.dumps(
            {
                "suite": "preflight",
                "success": False,
                "last_error": "verification suite returned non-zero exit code",
                "steps": [
                    {"name": "all_pytests", "success": True},
                    {"name": "propr_smoke", "success": False},
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = build_run_summary(
        mode="preflight",
        environment="beta",
        started_at="2026-03-29T08:00:00+00:00",
        finished_at="2026-03-29T08:01:00+00:00",
        exit_code=1,
        test_status_path=status_path,
    )

    assert summary["success"] is False
    assert summary["suite"] == "preflight"
    assert summary["title"] == "Preflight-Test fehlgeschlagen"
    assert "Fehlgeschritt: propr_smoke" in summary["summary_lines"]
    assert "verification suite returned non-zero exit code" in summary["notification_message"]


def test_build_run_summary_for_scharf_aggregates_current_run_entries(tmp_path: Path) -> None:
    journal_path = tmp_path / "trading_journal_beta.jsonl"
    entries = [
        {
            "entry_type": "cycle",
            "entry_timestamp": "2026-03-29T08:59:59+00:00",
            "symbol": "BTC/USDC",
            "decision_action": "NO_ACTION",
        },
        {
            "entry_type": "cycle",
            "entry_timestamp": "2026-03-29T09:00:05+00:00",
            "symbol": "BTC/USDC",
            "decision_action": "PREPARE_TREND_ORDER",
        },
        {
            "entry_type": "order",
            "entry_timestamp": "2026-03-29T09:00:05+00:00",
            "symbol": "BTC/USDC",
            "status": "prepared",
        },
        {
            "entry_type": "trade",
            "entry_timestamp": "2026-03-29T09:00:10+00:00",
            "symbol": "ETH/USDC",
            "status": "filled",
        },
    ]
    journal_path.write_text("\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8")

    summary = build_run_summary(
        mode="scharf",
        environment="beta",
        started_at="2026-03-29T09:00:00+00:00",
        finished_at="2026-03-29T09:01:00+00:00",
        exit_code=0,
        journal_path=journal_path,
    )

    assert summary["success"] is True
    assert summary["entry_count"] == 3
    assert summary["cycle_count"] == 1
    assert summary["order_count"] == 1
    assert summary["trade_count"] == 1
    assert summary["symbols"] == ["BTC/USDC", "ETH/USDC"]
    assert summary["latest_symbol"] == "ETH/USDC"
    assert summary["latest_outcome"] == "filled"
    assert any("Order-Status: prepared=1" in line for line in summary["summary_lines"])

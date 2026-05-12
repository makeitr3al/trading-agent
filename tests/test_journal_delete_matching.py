from __future__ import annotations

import base64
import json


def _parse_targets_payload(raw: str):
    """Mirrors delete_journal_entries.py _parse_targets_payload (run.sh heredoc)."""
    raw = raw.strip()
    if not raw:
        raise ValueError("empty targets payload")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pad = (4 - len(raw) % 4) % 4
        decoded = base64.standard_b64decode(raw + ("=" * pad)).decode("utf-8")
        return json.loads(decoded)


def _matches_delete_target(entry: dict, target: dict) -> bool:
    """
    Mirrors the HA add-on helper predicate in ha_addons/trading_agent/run.sh
    for deleting JSONL journal entries.
    """
    target_ts = target.get("entry_timestamp")
    if target_ts is None:
        return False
    ts_match = (entry.get("executed_at") == target_ts) or (entry.get("entry_timestamp") == target_ts)
    if not ts_match:
        return False
    return (
        entry.get("symbol") == target.get("symbol")
        and entry.get("entry_type") == target.get("entry_type")
        and entry.get("status") == target.get("status")
        and str(entry.get("environment") or "").strip().lower()
        == str(target.get("environment") or "").strip().lower()
    )


def test_delete_matching_accepts_panel_timestamp_derived_from_executed_at() -> None:
    entry = {
        "entry_timestamp": "2026-05-05T18:00:00Z",
        "executed_at": "2026-05-05T18:00:02Z",
        "symbol": "BTC/USDC",
        "environment": "beta",
        "entry_type": "trade",
        "status": "filled",
    }
    # Panel uses journal_table row.timestamp = executed_at or entry_timestamp
    target = {
        "entry_timestamp": "2026-05-05T18:00:02Z",
        "symbol": "BTC/USDC",
        "environment": "beta",
        "entry_type": "trade",
        "status": "filled",
    }
    assert _matches_delete_target(entry, target) is True


def test_delete_matching_still_accepts_entry_timestamp() -> None:
    entry = {
        "entry_timestamp": "2026-05-05T18:00:00Z",
        "executed_at": None,
        "symbol": "ETH/USDC",
        "environment": "prod",
        "entry_type": "order",
        "status": "resting",
    }
    target = {
        "entry_timestamp": "2026-05-05T18:00:00Z",
        "symbol": "ETH/USDC",
        "environment": "prod",
        "entry_type": "order",
        "status": "resting",
    }
    assert _matches_delete_target(entry, target) is True


def test_delete_matching_rejects_wrong_symbol_or_type_or_status() -> None:
    entry = {
        "entry_timestamp": "2026-05-05T18:00:00Z",
        "executed_at": "2026-05-05T18:00:02Z",
        "symbol": "BTC/USDC",
        "environment": "beta",
        "entry_type": "trade",
        "status": "filled",
    }
    base_target = {
        "entry_timestamp": "2026-05-05T18:00:02Z",
        "symbol": "BTC/USDC",
        "environment": "beta",
        "entry_type": "trade",
        "status": "filled",
    }
    assert _matches_delete_target(entry, {**base_target, "symbol": "ETH/USDC"}) is False
    assert _matches_delete_target(entry, {**base_target, "entry_type": "order"}) is False
    assert _matches_delete_target(entry, {**base_target, "status": "closed"}) is False


def test_parse_targets_payload_accepts_plain_json() -> None:
    assert _parse_targets_payload('[{"a": 1}]') == [{"a": 1}]


def test_parse_targets_payload_accepts_base64_json() -> None:
    b = base64.standard_b64encode('[{"x": 2}]'.encode("utf-8")).decode("ascii")
    assert _parse_targets_payload(b) == [{"x": 2}]


def test_parse_targets_payload_accepts_base64_without_padding() -> None:
    payload = [
        {
            "entry_timestamp": "2026-05-05T18:00:02Z",
            "symbol": "BTC/USDC",
            "environment": "beta",
            "entry_type": "trade",
            "status": "filled",
        }
    ]
    raw = json.dumps(payload, ensure_ascii=True)
    b64 = base64.standard_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
    assert _parse_targets_payload(b64) == payload


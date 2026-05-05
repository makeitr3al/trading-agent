from __future__ import annotations


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


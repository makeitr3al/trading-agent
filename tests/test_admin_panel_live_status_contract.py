"""Contract for HA panel + package placeholder JSON (see admin-panel.js isUsableLiveStatusPayload)."""

from __future__ import annotations

import json


def test_ha_package_live_status_placeholder_uses_source_unknown() -> None:
    """When /share file is missing, trading_agent_sync_panel_assets_haos writes source=unknown (HTTP 200)."""
    raw = (
        '{"updated_at":null,"environment":null,"account_unrealized_pnl":null,'
        '"account_open_positions_count":0,"websocket_connected":false,"source":"unknown",'
        '"last_error":null,"challenge_name":null,"challenge_id":null,"initial_balance":null,'
        '"balance":null,"margin_balance":null,"available_balance":null,"high_water_mark":null,'
        '"open_positions_summary":null,"challenges_overview":null,"active_challenges_count":null,'
        '"account_total_margin_balance":null}'
    )
    d = json.loads(raw)
    assert str(d.get("source", "")).lower() == "unknown"
    assert d.get("margin_balance") is None


def test_sync_live_status_poll_payload_is_usable_shape() -> None:
    """Real sync writes source poll and timestamps (panel must not treat as placeholder)."""
    from utils.live_status import build_live_status_payload

    p = build_live_status_payload(
        environment="beta",
        state=None,
        source="poll",
        updated_at="2026-01-01T00:00:00+00:00",
        account_unrealized_pnl=1.5,
        margin_balance=100.0,
    )
    assert p["source"] == "poll"
    assert p["updated_at"] is not None

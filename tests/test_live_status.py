from pathlib import Path

from models.agent_state import AgentState
from utils.live_status import build_live_status_payload, load_live_status, write_live_status_from_state


def test_build_live_status_payload_uses_state_values() -> None:
    state = AgentState(account_open_positions_count=3, account_unrealized_pnl=12.5)

    payload = build_live_status_payload(
        environment="beta",
        state=state,
        websocket_connected=False,
        source="poll",
    )

    assert payload["environment"] == "beta"
    assert payload["account_open_positions_count"] == 3
    assert payload["account_unrealized_pnl"] == 12.5
    assert payload["source"] == "poll"
    assert payload.get("open_positions_summary") is None


def test_write_live_status_from_state_roundtrip(tmp_path: Path) -> None:
    output_path = tmp_path / "live_status.json"
    state = AgentState(account_open_positions_count=2, account_unrealized_pnl=-4.25)

    write_live_status_from_state(
        environment="prod",
        state=state,
        path=output_path,
        websocket_connected=True,
        source="websocket",
    )
    payload = load_live_status(output_path)

    assert payload["environment"] == "prod"
    assert payload["account_open_positions_count"] == 2
    assert payload["account_unrealized_pnl"] == -4.25
    assert payload["websocket_connected"] is True
    assert payload["source"] == "websocket"
    assert payload.get("open_positions_summary") is None


def test_build_live_status_payload_includes_challenges_overview() -> None:
    overview = [{"challenge_id": "c1", "account_open_positions_count": 1}]
    payload = build_live_status_payload(
        environment="beta",
        state=None,
        source="poll",
        challenges_overview=overview,
        active_challenges_count=2,
    )
    assert payload["challenges_overview"] == overview
    assert payload["active_challenges_count"] == 2


def test_build_live_status_payload_serializes_open_positions_summary() -> None:
    rows = [{"symbol": "BTC", "direction": "long", "position_size": 0.1}]
    payload = build_live_status_payload(
        environment="beta",
        state=None,
        source="websocket",
        open_positions_summary=rows,
    )
    assert payload["open_positions_summary"] == rows


def test_load_live_status_returns_defaults_for_missing_file(tmp_path: Path) -> None:
    payload = load_live_status(tmp_path / "missing.json")

    assert payload["account_open_positions_count"] == 0
    assert payload["account_unrealized_pnl"] is None
    assert payload["websocket_connected"] is False

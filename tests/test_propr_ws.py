from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.propr_ws import ProprWebSocketClient
from config.propr_config import ProprConfig


def _make_client() -> ProprWebSocketClient:
    return ProprWebSocketClient(
        ProprConfig(api_key="api-key-1", websocket_url="wss://example/ws")
    )


def test_build_ws_url_returns_config_websocket_url() -> None:
    client = _make_client()

    assert client.build_ws_url() == "wss://example/ws"


def test_build_auth_headers_returns_api_key_header() -> None:
    client = _make_client()

    assert client.build_auth_headers() == {"X-API-Key": "api-key-1"}


def test_parse_event_reads_event_type_from_type() -> None:
    client = _make_client()
    event = client.parse_event({"type": "order.filled"})

    assert event.event_type == "order.filled"


def test_parse_event_reads_event_type_from_event() -> None:
    client = _make_client()
    event = client.parse_event({"event": "position.updated"})

    assert event.event_type == "position.updated"


def test_parse_event_falls_back_to_unknown() -> None:
    client = _make_client()
    event = client.parse_event({})

    assert event.event_type == "unknown"


def test_is_relevant_event_returns_true_for_order_filled() -> None:
    client = _make_client()
    event = client.parse_event({"type": "order.filled"})

    assert client.is_relevant_event(event) is True


def test_is_relevant_event_returns_true_for_position_updated() -> None:
    client = _make_client()
    event = client.parse_event({"type": "position.updated"})

    assert client.is_relevant_event(event) is True


def test_is_relevant_event_returns_true_for_trade_created() -> None:
    client = _make_client()
    event = client.parse_event({"type": "trade.created"})

    assert client.is_relevant_event(event) is True


def test_is_relevant_event_returns_false_for_unrelated_event() -> None:
    client = _make_client()
    event = client.parse_event({"type": "heartbeat"})

    assert client.is_relevant_event(event) is False

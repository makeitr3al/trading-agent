import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.propr_ws import ProprWebSocketClient
from config.propr_config import ProprConfig
from utils.live_status import load_live_status


class FakeWebSocket:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.sent_messages: list[str] = []
        self.index = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def send(self, message: str) -> None:
        self.sent_messages.append(message)

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self.index >= len(self.messages):
            raise StopAsyncIteration
        message = self.messages[self.index]
        self.index += 1
        return message


def test_extract_live_status_payload_reads_account_wide_pnl_and_positions() -> None:
    client = ProprWebSocketClient(ProprConfig(environment="beta", api_key="key"))

    payload = client.extract_live_status_payload(
        {
            "type": "position.updated",
            "accountUnrealizedPnl": "33.5",
            "data": [
                {
                    "status": "open",
                    "positionSide": "long",
                    "entryPrice": "100.5",
                    "stopLoss": "95.0",
                    "takeProfit": "110.0",
                    "quantity": "1.25",
                    "positionId": "btc-position",
                },
                {
                    "status": "open",
                    "positionSide": "short",
                    "entry": 100,
                    "stopLoss": 105,
                    "takeProfit": 90,
                    "quantity": "2",
                    "positionId": "eth-position",
                },
            ],
        }
    )

    assert payload is not None
    assert payload["account_unrealized_pnl"] == 33.5
    assert payload["account_open_positions_count"] == 2
    assert payload["websocket_connected"] is True
    assert len(payload["open_positions_summary"]) == 2


def test_connect_persists_live_status_updates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = ProprWebSocketClient(ProprConfig(environment="beta", api_key="key", websocket_url="wss://example.test/ws"))
    output_path = tmp_path / "live_status.json"

    messages = [
        '{"type":"position.updated","data":[{"status":"open","positionSide":"long","entryPrice":"100.5","stopLoss":"95.0","takeProfit":"110.0","quantity":"1.25","positionId":"btc-position","unrealizedPnl":"11.5"}]}'
    ]
    fake_websocket = FakeWebSocket(messages)

    monkeypatch.setattr("broker.propr_ws.websockets.connect", lambda *args, **kwargs: fake_websocket)

    asyncio.run(client.connect("account-1", path=output_path, stop_after_events=1))
    payload = load_live_status(output_path)

    assert payload["websocket_connected"] is True
    assert payload["source"] == "websocket"
    assert payload["account_open_positions_count"] == 1
    assert payload["account_unrealized_pnl"] == 11.5
    assert len(fake_websocket.sent_messages) == 3
    assert payload.get("updated_at") is not None
    assert payload.get("open_positions_summary") is not None
    assert len(payload["open_positions_summary"]) == 1
    assert payload["open_positions_summary"][0]["direction"] == "long"


def test_extract_live_status_payload_empty_data_list() -> None:
    client = ProprWebSocketClient(ProprConfig(environment="beta", api_key="key"))
    payload = client.extract_live_status_payload(
        {"type": "position.updated", "accountUnrealizedPnl": "0", "data": []}
    )
    assert payload is not None
    assert payload["account_open_positions_count"] == 0
    assert payload["open_positions_summary"] == []


def test_run_forever_reconnects_after_clean_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = ProprWebSocketClient(ProprConfig(environment="beta", api_key="key", websocket_url="wss://example.test/ws"))
    calls: list[int] = []

    async def fake_connect(
        self: ProprWebSocketClient,
        account_id: str,
        *,
        path: Path | None = None,
        on_status=None,
        stop_after_events: int | None = None,
    ) -> None:
        calls.append(1)
        if len(calls) >= 3:
            raise SystemExit("test_stop")

    monkeypatch.setattr(ProprWebSocketClient, "connect", fake_connect)
    with pytest.raises(SystemExit, match="test_stop"):
        asyncio.run(
            client.run_forever("account-1", path=tmp_path / "live_status.json", reconnect_delay_seconds=0)
        )
    assert len(calls) == 3


def test_run_forever_persists_disconnect_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = ProprWebSocketClient(ProprConfig(environment="beta", api_key="key", websocket_url="wss://example.test/ws"))
    output_path = tmp_path / "live_status.json"

    def raise_connect(*args, **kwargs):
        raise RuntimeError("socket unavailable")

    monkeypatch.setattr("broker.propr_ws.websockets.connect", raise_connect)

    with pytest.raises(RuntimeError, match="socket unavailable"):
        asyncio.run(client.run_forever("account-1", path=output_path, reconnect_delay_seconds=0, max_reconnect_attempts=0))

    payload = load_live_status(output_path)
    assert payload["websocket_connected"] is False
    assert payload["last_error"] == "socket unavailable"


def test_connect_passes_ping_interval_and_timeout_to_websockets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = ProprWebSocketClient(
        ProprConfig(environment="beta", api_key="key", websocket_url="wss://example.test/ws")
    )
    captured: dict[str, object] = {}

    def fake_connect(*args: object, **kwargs: object) -> FakeWebSocket:
        captured.update(kwargs)
        return FakeWebSocket([])

    monkeypatch.setattr("broker.propr_ws.websockets.connect", fake_connect)
    asyncio.run(client.connect("account-1", path=tmp_path / "status.json"))

    assert captured.get("ping_interval") == 20
    assert captured.get("ping_timeout") == 10


def test_parse_event_uses_type_field_from_official_format() -> None:
    client = ProprWebSocketClient(ProprConfig(environment="beta", api_key="key"))
    event = client.parse_event({"type": "order.filled", "data": {"orderId": "abc"}})
    assert event.event_type == "order.filled"


def test_parse_event_warns_when_type_field_missing(caplog: pytest.LogCaptureFixture) -> None:
    import logging
    client = ProprWebSocketClient(ProprConfig(environment="beta", api_key="key"))
    with caplog.at_level(logging.WARNING, logger="broker.propr_ws"):
        event = client.parse_event({"channel": "orders", "data": {}})
    assert "missing 'type' field" in caplog.text
    assert event.event_type == "orders"


def test_connect_skips_subscribe_messages_when_send_subscribe_is_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = ProprWebSocketClient(
        ProprConfig(environment="beta", api_key="key", websocket_url="wss://example.test/ws"),
        send_subscribe=False,
    )
    fake_websocket = FakeWebSocket([])
    monkeypatch.setattr("broker.propr_ws.websockets.connect", lambda *a, **kw: fake_websocket)
    asyncio.run(client.connect("account-1", path=tmp_path / "status.json"))
    assert len(fake_websocket.sent_messages) == 0


# All 13 relevant + 1 non-relevant documented event types
_DOCUMENTED_EVENT_TYPES: list[tuple[str, bool]] = [
    ("connected",                  False),  # initial handshake — not actionable
    ("account.updated",            True),
    ("order.created",              True),
    ("order.updated",              True),
    ("order.cancelled",            True),
    ("order.triggered",            True),
    ("order.filled",               True),
    ("position.updated",           True),
    ("position.closed",            True),
    ("position.liquidated",        True),
    ("position.take_profit.hit",   True),
    ("position.stop_loss.hit",     True),
    ("trade.created",              True),
]


@pytest.mark.parametrize("event_type,expected_relevant", _DOCUMENTED_EVENT_TYPES)
def test_is_relevant_event_covers_all_documented_types(
    event_type: str, expected_relevant: bool
) -> None:
    from broker.propr_ws import ProprWsEvent
    client = ProprWebSocketClient(ProprConfig(environment="beta", api_key="key"))
    event = ProprWsEvent(event_type=event_type, raw_payload={"type": event_type})
    assert client.is_relevant_event(event) is expected_relevant


def test_ws_payload_references_order_id_nested_match() -> None:
    from broker.propr_ws import _ws_payload_references_order_id

    oid = "ord-xyz"
    assert _ws_payload_references_order_id({"orderId": oid}, oid)
    assert _ws_payload_references_order_id({"data": [{"order_id": oid}]}, oid)
    assert not _ws_payload_references_order_id({"data": [{"id": oid}]}, oid)
    assert not _ws_payload_references_order_id({"foo": "bar"}, oid)

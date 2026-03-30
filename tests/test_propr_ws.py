import asyncio
from pathlib import Path

import pytest

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

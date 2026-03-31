from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Awaitable, Callable

try:
    import websockets as _websockets
except ModuleNotFoundError:
    _websockets = None

websockets = _websockets or SimpleNamespace(connect=None)

from pydantic import BaseModel

from broker.state_sync import (
    _extract_account_open_positions_count_from_payload,
    _extract_account_unrealized_pnl_from_payload,
)
from config.propr_config import ProprConfig
from utils.live_status import load_live_status, write_live_status


class ProprWsEvent(BaseModel):
    event_type: str
    raw_payload: dict[str, Any]


class ProprWebSocketClient:
    def __init__(self, config: ProprConfig) -> None:
        self.config = config

    def build_ws_url(self) -> str:
        return self.config.websocket_url

    def build_auth_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            return {}
        return {"X-API-Key": self.config.api_key.get_secret_value()}

    def build_subscribe_messages(self, account_id: str) -> list[dict[str, Any]]:
        return [
            {"action": "subscribe", "channel": "positions", "accountId": account_id},
            {"action": "subscribe", "channel": "orders", "accountId": account_id},
            {"action": "subscribe", "channel": "account", "accountId": account_id},
        ]

    def parse_event(self, payload: dict[str, Any]) -> ProprWsEvent:
        event_type = str(
            payload.get("type")
            or payload.get("event")
            or payload.get("channel")
            or payload.get("topic")
            or "unknown"
        )
        return ProprWsEvent(event_type=event_type, raw_payload=payload)

    def is_relevant_event(self, event: ProprWsEvent) -> bool:
        normalized = event.event_type.lower()
        return any(
            token in normalized
            for token in ["position", "account", "trade", "order.filled"]
        )

    def extract_live_status_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        candidates: list[dict[str, Any] | list[dict[str, Any]]] = []
        if "positions" in payload:
            candidates.append(payload["positions"])
        if "data" in payload:
            candidates.append(payload["data"])
        candidates.append(payload)

        pnl_value: float | None = None
        open_positions_count: int | None = None
        for candidate in candidates:
            if isinstance(candidate, dict):
                maybe_pnl = _extract_account_unrealized_pnl_from_payload(candidate)
                if maybe_pnl is not None and pnl_value is None:
                    pnl_value = maybe_pnl
                maybe_count = _extract_account_open_positions_count_from_payload(candidate)
                if maybe_count and open_positions_count is None:
                    open_positions_count = maybe_count
            elif isinstance(candidate, list):
                wrapped = {"data": candidate}
                maybe_pnl = _extract_account_unrealized_pnl_from_payload(wrapped)
                if maybe_pnl is not None and pnl_value is None:
                    pnl_value = maybe_pnl
                maybe_count = _extract_account_open_positions_count_from_payload(wrapped)
                if maybe_count and open_positions_count is None:
                    open_positions_count = maybe_count

        if pnl_value is None and open_positions_count is None:
            return None

        return {
            "environment": self.config.environment,
            "account_unrealized_pnl": pnl_value,
            "account_open_positions_count": int(open_positions_count or 0),
            "websocket_connected": True,
            "source": "websocket",
            "last_error": None,
        }

    def persist_live_status(self, payload: dict[str, Any], path: str | Path | None = None) -> Path:
        existing = load_live_status(path)
        return write_live_status({**existing, **payload}, path=path)

    async def _emit_status(
        self,
        payload: dict[str, Any],
        *,
        path: str | Path | None = None,
        on_status: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> None:
        self.persist_live_status(payload, path=path)
        if on_status is not None:
            result = on_status(payload)
            if asyncio.iscoroutine(result):
                await result

    async def connect(
        self,
        account_id: str,
        *,
        path: str | Path | None = None,
        on_status: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
        stop_after_events: int | None = None,
    ) -> None:
        await self._emit_status(
            {
                "environment": self.config.environment,
                "websocket_connected": False,
                "source": "websocket",
                "last_error": None,
            },
            path=path,
            on_status=on_status,
        )
        processed_events = 0
        if websockets.connect is None:
            raise RuntimeError("websockets dependency is not installed")

        async with websockets.connect(self.build_ws_url(), additional_headers=self.build_auth_headers()) as websocket:
            for message in self.build_subscribe_messages(account_id):
                await websocket.send(json.dumps(message))

            await self._emit_status(
                {
                    "environment": self.config.environment,
                    "websocket_connected": True,
                    "source": "websocket",
                    "last_error": None,
                },
                path=path,
                on_status=on_status,
            )

            async for raw_message in websocket:
                payload = json.loads(raw_message)
                event = self.parse_event(payload)
                if not self.is_relevant_event(event):
                    continue

                live_status_payload = self.extract_live_status_payload(event.raw_payload)
                if live_status_payload is not None:
                    await self._emit_status(live_status_payload, path=path, on_status=on_status)

                processed_events += 1
                if stop_after_events is not None and processed_events >= stop_after_events:
                    break

    async def run_forever(
        self,
        account_id: str,
        *,
        path: str | Path | None = None,
        on_status: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
        reconnect_delay_seconds: float = 5.0,
        max_reconnect_attempts: int | None = None,
    ) -> None:
        attempts = 0
        while max_reconnect_attempts is None or attempts <= max_reconnect_attempts:
            try:
                await self.connect(account_id, path=path, on_status=on_status)
                return
            except Exception as exc:
                attempts += 1
                await self._emit_status(
                    {
                        "environment": self.config.environment,
                        "websocket_connected": False,
                        "source": "websocket",
                        "last_error": str(exc),
                    },
                    path=path,
                    on_status=on_status,
                )
                if max_reconnect_attempts is not None and attempts > max_reconnect_attempts:
                    raise
                await asyncio.sleep(reconnect_delay_seconds)

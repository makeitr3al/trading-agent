"""Hyperliquid public WebSocket: trades subscriptions for virtual-stop watching."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)

try:
    import websockets as _websockets
except ModuleNotFoundError:  # pragma: no cover
    _websockets = None

websockets = _websockets or SimpleNamespace(connect=None)

DEFAULT_HL_WS_URL = "wss://api.hyperliquid.xyz/ws"


@dataclass(frozen=True)
class HyperliquidTradeTick:
    coin: str
    price: Decimal
    time_ms: int
    side: str | None = None


TradeCallback = Callable[[HyperliquidTradeTick], None]


class HyperliquidTradesWatcher:
    """Subscribe to ``trades`` for a dynamic set of coins; invoke callback on each print."""

    def __init__(
        self,
        *,
        ws_url: str = DEFAULT_HL_WS_URL,
        on_trade: TradeCallback | None = None,
        reconnect_delay_seconds: float = 2.0,
    ) -> None:
        self.ws_url = ws_url
        self.on_trade = on_trade
        self.reconnect_delay_seconds = max(0.5, float(reconnect_delay_seconds))
        self._armed_coins: set[str] = set()
        self._armed_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = threading.Event()
        self._resubscribe = threading.Event()
        self._last_disconnect_at: float | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def get_armed_coins(self) -> set[str]:
        with self._armed_lock:
            return set(self._armed_coins)

    def set_armed_coins(self, coins: set[str] | list[str]) -> None:
        normalized = {str(c).strip() for c in coins if str(c).strip()}
        with self._armed_lock:
            if normalized == self._armed_coins:
                return
            self._armed_coins = normalized
            self._resubscribe.set()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_thread, name="hl-trades-watcher", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        self._resubscribe.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._connected.clear()

    def _run_thread(self) -> None:
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        if websockets.connect is None:
            logger.error("websockets package not available; Hyperliquid trades watcher idle")
            while not self._stop.is_set():
                await asyncio.sleep(1.0)
            return

        while not self._stop.is_set():
            try:
                await self._session()
            except Exception as exc:
                logger.warning("Hyperliquid WS session ended: %s", exc)
                self._connected.clear()
                self._last_disconnect_at = asyncio.get_event_loop().time()
            if self._stop.is_set():
                break
            await asyncio.sleep(self.reconnect_delay_seconds)

    async def _session(self) -> None:
        assert websockets.connect is not None
        async with websockets.connect(
            self.ws_url,
            ping_interval=20,
            ping_timeout=20,
            max_queue=1024,
        ) as ws:
            self._connected.set()
            await self._sync_subscriptions(ws, previous=set())
            previous = self.get_armed_coins()
            while not self._stop.is_set():
                if self._resubscribe.is_set():
                    self._resubscribe.clear()
                    current = self.get_armed_coins()
                    await self._sync_subscriptions(ws, previous=previous, current=current)
                    previous = current

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                self._handle_message(raw)

    async def _sync_subscriptions(
        self,
        ws: Any,
        *,
        previous: set[str],
        current: set[str] | None = None,
    ) -> None:
        target = self.get_armed_coins() if current is None else current
        for coin in sorted(previous - target):
            await ws.send(
                json.dumps({"method": "unsubscribe", "subscription": {"type": "trades", "coin": coin}})
            )
        for coin in sorted(target - previous):
            await ws.send(
                json.dumps({"method": "subscribe", "subscription": {"type": "trades", "coin": coin}})
            )

    def _handle_message(self, raw: str | bytes) -> None:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        channel = str(payload.get("channel") or "")
        if channel != "trades":
            return
        data = payload.get("data")
        rows: list[Any]
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = [data]
        else:
            return
        callback = self.on_trade
        if callback is None:
            return
        for row in rows:
            tick = self._parse_trade(row)
            if tick is None:
                continue
            armed = self.get_armed_coins()
            if tick.coin not in armed:
                # HL may still deliver briefly after unsubscribe
                continue
            try:
                callback(tick)
            except Exception:
                logger.exception("on_trade callback failed for coin=%s", tick.coin)

    @staticmethod
    def _parse_trade(row: Any) -> HyperliquidTradeTick | None:
        if not isinstance(row, dict):
            return None
        coin = str(row.get("coin") or "").strip()
        px_raw = row.get("px")
        if not coin or px_raw is None:
            return None
        try:
            price = Decimal(str(px_raw))
        except Exception:
            return None
        time_raw = row.get("time") or row.get("t") or 0
        try:
            time_ms = int(time_raw)
        except (TypeError, ValueError):
            time_ms = 0
        side = row.get("side")
        return HyperliquidTradeTick(
            coin=coin,
            price=price,
            time_ms=time_ms,
            side=str(side) if side is not None else None,
        )

from pydantic import BaseModel

from config.propr_config import ProprConfig

# TODO: Later add a real async websocket connection implementation.
# TODO: Later add reconnect and resubscribe logic.
# TODO: Later add callback-based event processing.
# TODO: Later mutate or reconcile AgentState from websocket events.


class ProprWsEvent(BaseModel):
    event_type: str
    raw_payload: dict


class ProprWebSocketClient:
    def __init__(self, config: ProprConfig) -> None:
        self.config = config

    def build_ws_url(self) -> str:
        return self.config.websocket_url

    def build_auth_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            return {}
        return {"X-API-Key": self.config.api_key}

    def parse_event(self, payload: dict) -> ProprWsEvent:
        event_type = str(payload.get("type") or payload.get("event") or "unknown")
        return ProprWsEvent(event_type=event_type, raw_payload=payload)

    def is_relevant_event(self, event: ProprWsEvent) -> bool:
        return event.event_type in {
            "order.filled",
            "position.updated",
            "trade.created",
        }

    async def connect_stub(self) -> None:
        return None

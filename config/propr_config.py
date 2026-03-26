from pydantic import BaseModel


class ProprConfig(BaseModel):
    environment: str = "beta"
    base_url: str = "https://api.beta.propr.xyz/v1"
    api_key: str | None = None
    websocket_url: str = "wss://api.beta.propr.xyz/ws"

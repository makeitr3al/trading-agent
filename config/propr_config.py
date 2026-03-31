from pydantic import BaseModel, SecretStr


class ProprConfig(BaseModel):
    environment: str = "beta"
    base_url: str = "https://api.beta.propr.xyz/v1"
    api_key: SecretStr | None = None
    websocket_url: str = "wss://api.beta.propr.xyz/ws"

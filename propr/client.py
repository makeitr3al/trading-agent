from typing import Any, Protocol

from config.propr_config import ProprConfig
from utils.http_client import HttpClient


class SupportsHttpClient(Protocol):
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        ...

    def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


class ProprClient:
    def __init__(
        self,
        config: ProprConfig,
        http_client: SupportsHttpClient | None = None,
    ) -> None:
        self.config = config
        self.http_client = http_client or HttpClient()

    def get_auth_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            return {}
        return {"X-API-Key": self.config.api_key.get_secret_value()}

    def _require_auth_headers(self) -> dict[str, str]:
        headers = self.get_auth_headers()
        if not headers:
            raise ValueError("Missing Propr API key")
        return headers

    def health_check(self) -> dict[str, Any]:
        return self.http_client.get(f"{self.config.base_url}/health")

    def get_user_profile(self) -> dict[str, Any]:
        return self.http_client.get(
            f"{self.config.base_url}/users/me",
            headers=self._require_auth_headers(),
        )

    def get_challenge_attempts(self) -> dict[str, Any]:
        return self.http_client.get(
            f"{self.config.base_url}/challenge-attempts",
            headers=self._require_auth_headers(),
        )

    def get_orders(self, account_id: str) -> dict[str, Any]:
        return self.http_client.get(
            f"{self.config.base_url}/accounts/{account_id}/orders",
            headers=self._require_auth_headers(),
        )

    def get_positions(self, account_id: str) -> dict[str, Any]:
        return self.http_client.get(
            f"{self.config.base_url}/accounts/{account_id}/positions",
            headers=self._require_auth_headers(),
        )

    def get_trades(self, account_id: str) -> dict[str, Any]:
        return self.http_client.get(
            f"{self.config.base_url}/accounts/{account_id}/trades",
            headers=self._require_auth_headers(),
        )

    def create_order(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.http_client.post(
            f"{self.config.base_url}/accounts/{account_id}/orders",
            headers=self._require_auth_headers(),
            json=payload,
        )

    def cancel_order(self, account_id: str, order_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.http_client.post(
            f"{self.config.base_url}/accounts/{account_id}/orders/{order_id}/cancel",
            headers=self._require_auth_headers(),
            json=payload,
        )

from __future__ import annotations

from importlib import import_module
from typing import Any

from config.propr_config import ProprConfig

SDKProprClient = None



def _load_sdk_client_class() -> type:
    global SDKProprClient
    if SDKProprClient is not None:
        return SDKProprClient

    try:
        module = import_module("broker.propr_sdk")
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "broker.propr_sdk could not be loaded. Ensure SDK dependencies such as 'ulid' are installed."
        ) from exc

    SDKProprClient = module.ProprClient
    return SDKProprClient



def _parse_numeric_status(response: dict[str, Any]) -> int | None:
    raw_status = response.get("status") or response.get("status_code")
    if raw_status is None:
        return None
    if isinstance(raw_status, int):
        return raw_status

    text = str(raw_status).strip()
    if text.isdigit():
        return int(text)
    return None



def _accept_success_response(response: dict[str, Any] | None) -> dict[str, Any] | None:
    if response is None:
        return None

    status = _parse_numeric_status(response)
    if status is None:
        return response
    if status in {200, 201}:
        return response
    return response


class ProprClient:
    def __init__(self, config: ProprConfig) -> None:
        self.config = config
        sdk_client_class = _load_sdk_client_class()
        self.sdk_client = sdk_client_class(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def get_auth_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            return {}
        return {"X-API-Key": self.config.api_key}

    def _set_account(self, account_id: str) -> None:
        if not account_id or not account_id.strip():
            raise ValueError("account_id is required")
        self.sdk_client.setup(account_id=account_id.strip())

    def _wrap_list_response(self, data: list[dict[str, Any]]) -> dict[str, Any]:
        return {"data": data}

    def health_check(self) -> dict[str, Any]:
        return self.sdk_client.health()

    def health_services(self) -> dict[str, Any]:
        if hasattr(self.sdk_client, "health_services"):
            return self.sdk_client.health_services()
        raise AttributeError("SDK client does not expose health_services")

    def get_user_profile(self) -> dict[str, Any]:
        return self.sdk_client.get_user()

    def get_challenge_attempts(self, **kwargs: Any) -> dict[str, Any]:
        return self._wrap_list_response(self.sdk_client.get_challenge_attempts(**kwargs))

    def get_orders(self, account_id: str) -> dict[str, Any]:
        self._set_account(account_id)
        return self._wrap_list_response(self.sdk_client.get_orders())

    def get_positions(self, account_id: str) -> dict[str, Any]:
        self._set_account(account_id)
        return self._wrap_list_response(self.sdk_client.get_positions())

    def get_trades(self, account_id: str) -> dict[str, Any]:
        self._set_account(account_id)
        return self._wrap_list_response(self.sdk_client.get_trades())

    def get_margin_config(self, account_id: str, asset: str) -> dict[str, Any]:
        self._set_account(account_id)
        return self.sdk_client.get_margin_config(asset)

    def get_effective_leverage_limits(self) -> dict[str, Any]:
        if hasattr(self.sdk_client, "get_leverage_limits"):
            return self.sdk_client.get_leverage_limits()
        raise AttributeError("SDK client does not expose get_leverage_limits")

    def get_leverage_limits(self) -> dict[str, Any]:
        return self.get_effective_leverage_limits()

    def create_order(self, account_id: str, **order_params: Any) -> dict[str, Any]:
        self._set_account(account_id)
        response = self._wrap_list_response(self.sdk_client.create_order(**order_params))
        return _accept_success_response(response) or response

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any] | None:
        self._set_account(account_id)
        response = self.sdk_client.cancel_order(order_id)
        return _accept_success_response(response)


__all__ = ["ProprClient", "SDKProprClient"]

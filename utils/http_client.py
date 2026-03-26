from typing import Any

import requests


class HttpClient:
    def get(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        return dict(response.json())

    def post(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = requests.post(url, headers=headers, json=json, timeout=30)
        response.raise_for_status()
        return dict(response.json())

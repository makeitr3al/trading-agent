import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.propr_sdk import ProprAPIError, ProprClient


def _make_client() -> ProprClient:
    return ProprClient(api_key="pk_beta_test", base_url="https://api.test.example/v1")


def _mock_response(status_code: int, json_body: dict | None = None, headers: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = json_body or {}
    resp.text = ""
    return resp


def test_request_retries_on_429_and_succeeds() -> None:
    client = _make_client()
    fail = _mock_response(429, {"message": "rate limited"})
    ok = _mock_response(200, {"result": "ok"})

    with patch.object(client._session, "request", side_effect=[fail, ok]) as mock_req:
        with patch("broker.propr_sdk.time.sleep") as mock_sleep:
            resp = client._request("GET", "/test")

    assert resp.status_code == 200
    assert mock_req.call_count == 2
    mock_sleep.assert_called_once_with(1.0)  # first backoff: 1s


def test_request_respects_retry_after_header_on_429() -> None:
    client = _make_client()
    fail = _mock_response(429, {"message": "rate limited"}, headers={"Retry-After": "7"})
    ok = _mock_response(200)

    with patch.object(client._session, "request", side_effect=[fail, ok]):
        with patch("broker.propr_sdk.time.sleep") as mock_sleep:
            client._request("GET", "/test")

    mock_sleep.assert_called_once_with(7.0)


def test_request_retries_on_500_with_backoff() -> None:
    client = _make_client()
    fail1 = _mock_response(500, {"message": "server error"})
    fail2 = _mock_response(503, {"message": "unavailable"})
    ok = _mock_response(200)

    with patch.object(client._session, "request", side_effect=[fail1, fail2, ok]):
        with patch("broker.propr_sdk.time.sleep") as mock_sleep:
            resp = client._request("POST", "/orders")

    assert resp.status_code == 200
    assert mock_sleep.call_count == 2
    calls = [c.args[0] for c in mock_sleep.call_args_list]
    assert calls == [1.0, 2.0]  # exponential: 1s, 2s


def test_request_raises_after_max_retries() -> None:
    client = _make_client()
    always_fail = [_mock_response(502, {"message": "bad gateway"})] * 4  # 1 + 3 retries

    with patch.object(client._session, "request", side_effect=always_fail):
        with patch("broker.propr_sdk.time.sleep"):
            with pytest.raises(ProprAPIError) as exc_info:
                client._request("GET", "/positions")

    assert exc_info.value.status_code == 502


def test_request_does_not_retry_on_400_or_404() -> None:
    client = _make_client()
    for status in (400, 401, 403, 404, 422):
        fail = _mock_response(status, {"message": "client error"})
        with patch.object(client._session, "request", return_value=fail):
            with patch("broker.propr_sdk.time.sleep") as mock_sleep:
                with pytest.raises(ProprAPIError) as exc_info:
                    client._request("GET", "/test")
        assert exc_info.value.status_code == status
        mock_sleep.assert_not_called()

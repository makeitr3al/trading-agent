from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.health_guard import (
    HealthGuardResult,
    check_core_service_health,
    fetch_and_check_core_service_health,
    parse_health_services_response,
)


class FakeProprClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.called = False

    def health_services(self) -> dict:
        self.called = True
        return self.payload


def test_parses_services_from_top_level_payload() -> None:
    services = parse_health_services_response({"services": {"core": "OK"}})

    assert services == {"core": "OK"}


def test_parses_services_from_direct_core_payload() -> None:
    services = parse_health_services_response({"core": "OK"})

    assert services == {"core": "OK"}


def test_parses_services_from_nested_data_payload() -> None:
    services = parse_health_services_response({"data": {"services": {"core": "OK"}}})

    assert services == {"core": "OK"}


def test_returns_empty_dict_when_services_are_missing() -> None:
    services = parse_health_services_response({"data": {}})

    assert services == {}


def test_allows_trading_when_core_is_ok() -> None:
    result = check_core_service_health({"services": {"core": "OK"}})

    assert result == HealthGuardResult(allow_trading=True, reason=None, core_status="OK")


def test_blocks_when_core_service_is_missing() -> None:
    result = check_core_service_health({"services": {}})

    assert result.allow_trading is False
    assert result.reason == "core service status missing"
    assert result.core_status is None


def test_blocks_when_core_service_is_not_healthy() -> None:
    result = check_core_service_health({"services": {"core": "ERROR"}})

    assert result.allow_trading is False
    assert result.reason == "core service not healthy"
    assert result.core_status == "ERROR"


def test_fetch_and_check_core_service_health_uses_client_health_services() -> None:
    client = FakeProprClient({"core": "OK"})

    result = fetch_and_check_core_service_health(client)

    assert client.called is True
    assert result.allow_trading is True
    assert result.core_status == "OK"

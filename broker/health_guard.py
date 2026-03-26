from pydantic import BaseModel

from broker.propr_client import ProprClient


class HealthGuardResult(BaseModel):
    allow_trading: bool
    reason: str | None = None
    core_status: str | None = None


def parse_health_services_response(payload: dict) -> dict:
    if "core" in payload:
        return payload

    services = payload.get("services")
    if isinstance(services, dict):
        return services

    data = payload.get("data")
    if isinstance(data, dict):
        if "core" in data:
            return data
        nested_services = data.get("services")
        if isinstance(nested_services, dict):
            return nested_services

    return {}


def check_core_service_health(payload: dict) -> HealthGuardResult:
    services = parse_health_services_response(payload)
    core_status = services.get("core")

    if core_status is None:
        return HealthGuardResult(
            allow_trading=False,
            reason="core service status missing",
            core_status=None,
        )

    if str(core_status) != "OK":
        return HealthGuardResult(
            allow_trading=False,
            reason="core service not healthy",
            core_status=str(core_status),
        )

    return HealthGuardResult(
        allow_trading=True,
        reason=None,
        core_status="OK",
    )


def fetch_and_check_core_service_health(client: ProprClient) -> HealthGuardResult:
    payload = client.health_services()
    return check_core_service_health(payload)

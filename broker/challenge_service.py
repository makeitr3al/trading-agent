from typing import Any

from broker.propr_client import ProprClient
from models.propr_challenge import ActiveChallengeContext, ProprChallengeAttempt


def _get_items(payload: dict | list[dict]) -> list[dict]:
    if isinstance(payload, list):
        return payload
    data = payload.get("data", [])
    if isinstance(data, list):
        return data
    return []


def get_nested(item: dict[str, Any], path: str) -> Any:
    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def get_first_present(item: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = get_nested(item, key) if "." in key else item.get(key)
        if value is not None:
            return value
    return None


def normalize_attempt_payload(item: dict[str, Any]) -> ProprChallengeAttempt:
    account_value = get_first_present(
        item,
        ["account_id", "accountId", "tradingAccountId", "account.id"],
    )
    if account_value is None:
        account_object = item.get("account")
        if isinstance(account_object, dict):
            account_value = account_object.get("id")

    return ProprChallengeAttempt(
        attempt_id=str(get_first_present(item, ["attempt_id", "attemptId", "id"]) or ""),
        account_id=str(account_value or ""),
        status=str(get_first_present(item, ["status"]) or ""),
        current_phase=get_first_present(item, ["current_phase", "currentPhase"]),
        total_profit_loss=get_first_present(item, ["total_profit_loss", "totalProfitLoss"]),
        win_rate=get_first_present(item, ["win_rate", "winRate"]),
        max_drawdown=get_first_present(item, ["max_drawdown", "maxDrawdown"]),
        trading_days=get_first_present(item, ["trading_days", "tradingDays"]),
        failure_reason=get_first_present(item, ["failure_reason", "failureReason"]),
    )


def parse_challenge_attempts(payload: dict | list[dict]) -> list[ProprChallengeAttempt]:
    return [normalize_attempt_payload(item) for item in _get_items(payload)]


def get_active_challenge_context(
    client: ProprClient,
) -> ActiveChallengeContext | None:
    payload = client.get_challenge_attempts()
    attempts = parse_challenge_attempts(payload)
    active_attempts = [attempt for attempt in attempts if attempt.status == "active"]

    if not active_attempts:
        return None

    if len(active_attempts) > 1:
        raise ValueError("Multiple active challenge attempts found")

    attempt = active_attempts[0]
    if not attempt.account_id:
        raise ValueError("Active challenge attempt is missing account_id")

    return ActiveChallengeContext(attempt=attempt, account_id=attempt.account_id)


__all__ = [
    "get_nested",
    "get_first_present",
    "normalize_attempt_payload",
    "parse_challenge_attempts",
    "get_active_challenge_context",
]

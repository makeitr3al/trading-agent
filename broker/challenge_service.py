import logging
from typing import Any

from broker.propr_client import ProprClient
from models.propr_challenge import AccountBalance, ActiveChallengeContext, ProprChallengeAttempt

logger = logging.getLogger(__name__)


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

    challenge_id_value = get_first_present(item, ["challenge_id", "challengeId"])

    return ProprChallengeAttempt(
        attempt_id=str(get_first_present(item, ["attempt_id", "attemptId", "id"]) or ""),
        account_id=str(account_value or ""),
        challenge_id=str(challenge_id_value) if challenge_id_value else None,
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


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def parse_account_balance(attempt_detail: dict[str, Any]) -> AccountBalance | None:
    account = attempt_detail.get("account")
    if not isinstance(account, dict):
        return None

    challenge = attempt_detail.get("challenge")
    initial_balance = 0.0
    if isinstance(challenge, dict):
        initial_balance = _safe_float(challenge.get("initialBalance"))

    balance = _safe_float(account.get("balance"))
    unrealized_pnl = _safe_float(account.get("totalUnrealizedPnl"))
    margin_balance = _safe_float(account.get("marginBalance"))
    available_balance = _safe_float(account.get("availableBalance"))
    high_water_mark = _safe_float(account.get("highWaterMark"))

    if margin_balance == 0.0 and balance > 0.0:
        margin_balance = balance + unrealized_pnl

    return AccountBalance(
        balance=balance,
        total_unrealized_pnl=unrealized_pnl,
        margin_balance=margin_balance,
        available_balance=available_balance,
        high_water_mark=high_water_mark,
        initial_balance=initial_balance,
    )


def _extract_challenge_name(attempt_detail: dict[str, Any]) -> str | None:
    challenge = attempt_detail.get("challenge")
    if isinstance(challenge, dict):
        return challenge.get("name") or challenge.get("title")
    return None


def get_active_challenge_context(
    client: ProprClient,
    challenge_id: str | None = None,
) -> ActiveChallengeContext | None:
    payload = client.get_challenge_attempts()
    attempts = parse_challenge_attempts(payload)
    active_attempts = [attempt for attempt in attempts if attempt.status == "active"]

    if not active_attempts:
        return None

    if challenge_id:
        filtered = [a for a in active_attempts if a.challenge_id == challenge_id]
        if not filtered:
            logger.warning(
                "No active attempt matches PROPR_CHALLENGE_ID=%s (have %d active attempts)",
                challenge_id, len(active_attempts),
            )
            return None
        attempt = filtered[0]
    elif len(active_attempts) == 1:
        attempt = active_attempts[0]
    else:
        logger.warning(
            "Multiple active challenge attempts found (%d). "
            "Set PROPR_CHALLENGE_ID to select one. Using first.",
            len(active_attempts),
        )
        attempt = active_attempts[0]

    if not attempt.account_id:
        raise ValueError("Active challenge attempt is missing account_id")

    account_balance: AccountBalance | None = None
    challenge_name: str | None = None
    if attempt.attempt_id:
        try:
            detail = client.get_challenge_attempt(attempt.attempt_id)
            account_balance = parse_account_balance(detail)
            challenge_name = _extract_challenge_name(detail)
        except Exception:
            logger.warning("Failed to fetch challenge attempt detail for %s", attempt.attempt_id, exc_info=True)

    return ActiveChallengeContext(
        attempt=attempt,
        account_id=attempt.account_id,
        challenge_id=attempt.challenge_id,
        challenge_name=challenge_name,
        account_balance=account_balance,
    )


__all__ = [
    "get_nested",
    "get_first_present",
    "normalize_attempt_payload",
    "parse_challenge_attempts",
    "parse_account_balance",
    "get_active_challenge_context",
]

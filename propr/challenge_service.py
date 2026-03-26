from models.propr_challenge import ActiveChallengeContext, ProprChallengeAttempt
from propr.client import ProprClient


def parse_challenge_attempts(payload: dict) -> list[ProprChallengeAttempt]:
    attempts: list[ProprChallengeAttempt] = []
    for item in payload.get("data", []):
        attempts.append(
            ProprChallengeAttempt(
                attempt_id=str(item.get("attempt_id", item.get("id", ""))),
                account_id=str(item.get("account_id", "")),
                status=str(item.get("status", "")),
                current_phase=item.get("current_phase"),
                total_profit_loss=item.get("total_profit_loss"),
                win_rate=item.get("win_rate"),
                max_drawdown=item.get("max_drawdown"),
                trading_days=item.get("trading_days"),
                failure_reason=item.get("failure_reason"),
            )
        )
    return attempts


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
    return ActiveChallengeContext(attempt=attempt, account_id=attempt.account_id)

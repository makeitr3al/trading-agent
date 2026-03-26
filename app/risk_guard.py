from pydantic import BaseModel

from models.propr_challenge import ActiveChallengeContext

# TODO: Later add min trading days checks.
# TODO: Later add profit target checks.
# TODO: Later add daily loss checks from history.
# TODO: Later add broker-side margin and leverage checks.


class RiskGuardResult(BaseModel):
    allow_execution: bool
    reason: str | None = None


def check_challenge_status_guard(
    challenge_context: ActiveChallengeContext | None,
) -> RiskGuardResult:
    if challenge_context is None:
        return RiskGuardResult(allow_execution=False, reason="no active challenge")
    if challenge_context.attempt.status != "active":
        return RiskGuardResult(allow_execution=False, reason="challenge not active")
    return RiskGuardResult(allow_execution=True, reason=None)


def check_failure_reason_guard(
    challenge_context: ActiveChallengeContext | None,
) -> RiskGuardResult:
    if challenge_context is None:
        return RiskGuardResult(allow_execution=False, reason="no active challenge")
    if challenge_context.attempt.failure_reason and str(challenge_context.attempt.failure_reason).strip():
        return RiskGuardResult(allow_execution=False, reason="challenge has failure reason")
    return RiskGuardResult(allow_execution=True, reason=None)


def check_drawdown_guard(
    challenge_context: ActiveChallengeContext | None,
    max_allowed_drawdown: float | None = None,
) -> RiskGuardResult:
    if challenge_context is None:
        return RiskGuardResult(allow_execution=False, reason="no active challenge")
    if max_allowed_drawdown is None:
        return RiskGuardResult(allow_execution=True, reason=None)
    if challenge_context.attempt.max_drawdown is None:
        return RiskGuardResult(allow_execution=True, reason=None)
    if challenge_context.attempt.max_drawdown >= max_allowed_drawdown:
        return RiskGuardResult(allow_execution=False, reason="max drawdown threshold reached")
    return RiskGuardResult(allow_execution=True, reason=None)


def evaluate_execution_guards(
    challenge_context: ActiveChallengeContext | None,
    max_allowed_drawdown: float | None = None,
) -> RiskGuardResult:
    for guard_result in (
        check_challenge_status_guard(challenge_context),
        check_failure_reason_guard(challenge_context),
        check_drawdown_guard(challenge_context, max_allowed_drawdown=max_allowed_drawdown),
    ):
        if not guard_result.allow_execution:
            return guard_result
    return RiskGuardResult(allow_execution=True, reason=None)

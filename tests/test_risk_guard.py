from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.risk_guard import (
    check_challenge_status_guard,
    check_drawdown_guard,
    check_failure_reason_guard,
    evaluate_execution_guards,
)
from models.propr_challenge import ActiveChallengeContext, ProprChallengeAttempt


def _make_context(
    status: str = "active",
    failure_reason: str | None = None,
    max_drawdown: float | None = None,
) -> ActiveChallengeContext:
    attempt = ProprChallengeAttempt(
        attempt_id="attempt-1",
        account_id="account-1",
        status=status,
        failure_reason=failure_reason,
        max_drawdown=max_drawdown,
    )
    return ActiveChallengeContext(attempt=attempt, account_id="account-1")


def test_challenge_status_guard_blocks_when_no_active_challenge() -> None:
    result = check_challenge_status_guard(None)

    assert result.allow_execution is False
    assert result.reason == "no active challenge"


def test_challenge_status_guard_blocks_when_challenge_status_is_not_active() -> None:
    result = check_challenge_status_guard(_make_context(status="failed"))

    assert result.allow_execution is False
    assert result.reason == "challenge not active"


def test_challenge_status_guard_allows_active_challenge() -> None:
    result = check_challenge_status_guard(_make_context())

    assert result.allow_execution is True
    assert result.reason is None


def test_failure_reason_guard_blocks_when_failure_reason_is_set() -> None:
    result = check_failure_reason_guard(_make_context(failure_reason="max loss"))

    assert result.allow_execution is False
    assert result.reason == "challenge has failure reason"


def test_failure_reason_guard_allows_when_failure_reason_is_empty() -> None:
    result = check_failure_reason_guard(_make_context(failure_reason=""))

    assert result.allow_execution is True
    assert result.reason is None


def test_drawdown_guard_allows_when_no_threshold_is_configured() -> None:
    result = check_drawdown_guard(_make_context(max_drawdown=100.0), max_allowed_drawdown=None)

    assert result.allow_execution is True


def test_drawdown_guard_allows_when_drawdown_is_missing() -> None:
    result = check_drawdown_guard(_make_context(max_drawdown=None), max_allowed_drawdown=100.0)

    assert result.allow_execution is True


def test_drawdown_guard_blocks_when_drawdown_threshold_is_reached() -> None:
    result = check_drawdown_guard(_make_context(max_drawdown=100.0), max_allowed_drawdown=100.0)

    assert result.allow_execution is False
    assert result.reason == "max drawdown threshold reached"


def test_drawdown_guard_allows_when_drawdown_is_below_threshold() -> None:
    result = check_drawdown_guard(_make_context(max_drawdown=90.0), max_allowed_drawdown=100.0)

    assert result.allow_execution is True


def test_evaluate_execution_guards_returns_first_blocking_reason_for_inactive_challenge() -> None:
    result = evaluate_execution_guards(_make_context(status="failed"), max_allowed_drawdown=100.0)

    assert result.allow_execution is False
    assert result.reason == "challenge not active"


def test_evaluate_execution_guards_returns_first_blocking_reason_for_failure_reason() -> None:
    result = evaluate_execution_guards(_make_context(failure_reason="breach"), max_allowed_drawdown=100.0)

    assert result.allow_execution is False
    assert result.reason == "challenge has failure reason"


def test_evaluate_execution_guards_returns_first_blocking_reason_for_drawdown_threshold() -> None:
    result = evaluate_execution_guards(_make_context(max_drawdown=120.0), max_allowed_drawdown=100.0)

    assert result.allow_execution is False
    assert result.reason == "max drawdown threshold reached"


def test_evaluate_execution_guards_allows_when_all_guards_pass() -> None:
    result = evaluate_execution_guards(_make_context(max_drawdown=80.0), max_allowed_drawdown=100.0)

    assert result.allow_execution is True
    assert result.reason is None

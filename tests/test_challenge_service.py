from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from broker.challenge_service import (
    get_active_challenge_context,
    list_active_challenge_contexts,
    parse_challenge_attempts,
)
from models.propr_challenge import ActiveChallengeContext, ProprChallengeAttempt


class FakeProprClient:
    def __init__(self, payload: dict | list[dict], attempt_details: dict | None = None) -> None:
        self.payload = payload
        self.attempt_details = attempt_details or {}

    def get_challenge_attempts(self) -> dict | list[dict]:
        return self.payload

    def get_challenge_attempt(self, attempt_id: str) -> dict:
        return self.attempt_details.get(attempt_id, {})


def test_parse_challenge_attempts_with_empty_data_list() -> None:
    attempts = parse_challenge_attempts({"data": []})

    assert attempts == []


def test_parse_challenge_attempts_with_one_valid_attempt() -> None:
    attempts = parse_challenge_attempts(
        {
            "data": [
                {
                    "attemptId": "attempt-1",
                    "accountId": "account-1",
                    "status": "active",
                    "currentPhase": "phase-1",
                    "totalProfitLoss": 123.45,
                    "winRate": 0.6,
                    "maxDrawdown": 50.0,
                    "tradingDays": 12,
                    "failureReason": None,
                }
            ]
        }
    )

    assert len(attempts) == 1
    assert isinstance(attempts[0], ProprChallengeAttempt)
    assert attempts[0].attempt_id == "attempt-1"
    assert attempts[0].account_id == "account-1"


def test_normalizes_camel_case_fields_to_internal_snake_case_model() -> None:
    attempts = parse_challenge_attempts(
        {
            "data": [
                {
                    "attemptId": "attempt-1",
                    "accountId": "account-1",
                    "status": "active",
                    "currentPhase": "phase-1",
                    "totalProfitLoss": 12.5,
                    "winRate": 0.55,
                    "maxDrawdown": 3.2,
                    "tradingDays": 4,
                    "failureReason": "",
                }
            ]
        }
    )

    attempt = attempts[0]
    assert attempt.attempt_id == "attempt-1"
    assert attempt.account_id == "account-1"
    assert attempt.current_phase == "phase-1"
    assert attempt.total_profit_loss == 12.5
    assert attempt.win_rate == 0.55
    assert attempt.max_drawdown == 3.2
    assert attempt.trading_days == 4
    assert attempt.failure_reason == ""


def test_normalizes_nested_account_id_to_account_id() -> None:
    attempts = parse_challenge_attempts(
        {
            "data": [
                {
                    "attempt_id": "attempt-1",
                    "account": {"id": "account-nested-1"},
                    "status": "active",
                }
            ]
        }
    )

    assert attempts[0].account_id == "account-nested-1"


def test_normalizes_mixed_payload_field_names_correctly() -> None:
    attempts = parse_challenge_attempts(
        {
            "data": [
                {
                    "id": "attempt-mixed-1",
                    "tradingAccountId": "account-mixed-1",
                    "status": "active",
                    "current_phase": "phase-a",
                    "totalProfitLoss": 22.0,
                    "win_rate": 0.7,
                    "maxDrawdown": 5.0,
                    "trading_days": 8,
                    "failureReason": None,
                }
            ]
        }
    )

    attempt = attempts[0]
    assert attempt.attempt_id == "attempt-mixed-1"
    assert attempt.account_id == "account-mixed-1"
    assert attempt.current_phase == "phase-a"
    assert attempt.total_profit_loss == 22.0
    assert attempt.win_rate == 0.7
    assert attempt.max_drawdown == 5.0
    assert attempt.trading_days == 8


def test_get_active_challenge_context_returns_none_when_no_active_attempt_exists() -> None:
    client = FakeProprClient(
        {
            "data": [
                {
                    "attemptId": "attempt-1",
                    "accountId": "account-1",
                    "status": "failed",
                }
            ]
        }
    )

    context = get_active_challenge_context(client)

    assert context is None


def test_get_active_challenge_context_returns_active_attempt_when_exactly_one_exists() -> None:
    client = FakeProprClient(
        {
            "data": [
                {
                    "attemptId": "attempt-1",
                    "accountId": "account-1",
                    "status": "active",
                }
            ]
        }
    )

    context = get_active_challenge_context(client)

    assert isinstance(context, ActiveChallengeContext)
    assert context is not None
    assert context.account_id == "account-1"
    assert context.attempt.attempt_id == "attempt-1"


def test_get_active_challenge_context_returns_normalized_active_challenge_context() -> None:
    client = FakeProprClient(
        {
            "data": [
                {
                    "id": "attempt-normalized-1",
                    "account": {"id": "account-normalized-1"},
                    "status": "active",
                    "currentPhase": "phase-2",
                }
            ]
        }
    )

    context = get_active_challenge_context(client)

    assert context is not None
    assert context.attempt.attempt_id == "attempt-normalized-1"
    assert context.attempt.account_id == "account-normalized-1"
    assert context.attempt.current_phase == "phase-2"


def test_list_active_challenge_contexts_returns_all_active_attempts() -> None:
    client = FakeProprClient(
        {
            "data": [
                {
                    "attemptId": "attempt-1",
                    "accountId": "account-1",
                    "status": "active",
                },
                {
                    "attemptId": "attempt-2",
                    "accountId": "account-2",
                    "status": "active",
                },
            ]
        }
    )
    contexts = list_active_challenge_contexts(client)
    assert len(contexts) == 2
    assert {c.account_id for c in contexts} == {"account-1", "account-2"}


def test_get_active_challenge_context_picks_first_for_multiple_active_attempts() -> None:
    client = FakeProprClient(
        {
            "data": [
                {
                    "attemptId": "attempt-1",
                    "accountId": "account-1",
                    "status": "active",
                },
                {
                    "attemptId": "attempt-2",
                    "accountId": "account-2",
                    "status": "active",
                },
            ]
        }
    )

    context = get_active_challenge_context(client)
    assert context is not None
    assert context.attempt.attempt_id == "attempt-1"
    assert context.account_id == "account-1"


def test_get_active_challenge_context_filters_by_challenge_id() -> None:
    client = FakeProprClient(
        {
            "data": [
                {
                    "attemptId": "attempt-1",
                    "accountId": "account-1",
                    "challengeId": "challenge-A",
                    "status": "active",
                },
                {
                    "attemptId": "attempt-2",
                    "accountId": "account-2",
                    "challengeId": "challenge-B",
                    "status": "active",
                },
            ]
        }
    )

    context = get_active_challenge_context(client, challenge_id="challenge-B")
    assert context is not None
    assert context.attempt.attempt_id == "attempt-2"
    assert context.account_id == "account-2"
    assert context.challenge_id == "challenge-B"


def test_get_active_challenge_context_parses_balance() -> None:
    detail = {
        "account": {
            "balance": "101967.53",
            "totalUnrealizedPnl": "68.40",
            "marginBalance": "102035.93",
            "availableBalance": "97925.84",
            "highWaterMark": "100000",
        },
        "challenge": {
            "name": "Bronze Challenge",
            "initialBalance": "100000",
        },
    }
    client = FakeProprClient(
        {
            "data": [
                {
                    "attemptId": "attempt-1",
                    "accountId": "account-1",
                    "challengeId": "challenge-A",
                    "status": "active",
                },
            ]
        },
        attempt_details={"attempt-1": detail},
    )

    context = get_active_challenge_context(client)
    assert context is not None
    assert context.account_balance is not None
    assert context.account_balance.balance == 101967.53
    assert context.account_balance.margin_balance == 102035.93
    assert context.account_balance.initial_balance == 100000.0
    assert context.challenge_name == "Bronze Challenge"

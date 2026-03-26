from typing import Any

from pydantic import BaseModel

from app.risk_guard import RiskGuardResult, evaluate_execution_guards
from broker.challenge_service import get_active_challenge_context
from broker.execution import (
    safe_replace_pending_order,
    submit_agent_order_if_allowed,
)
from broker.health_guard import HealthGuardResult, fetch_and_check_core_service_health
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.state_sync import sync_agent_state_from_propr
from config.strategy_config import StrategyConfig
from models.candle import Candle
from models.propr_challenge import ActiveChallengeContext
from models.runner_result import StrategyRunResult
from strategy.engine import run_agent_cycle
from strategy.state import AgentState

# TODO: Later add challenge-specific risk limits.
# TODO: Later load account balance directly from Propr.
# TODO: Later add automatic symbol selection.
# TODO: Later add trade close/modify calls to Propr.
# TODO: Later add looping and scheduling.


def _extract_first(payload: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in payload and payload[key] is not None:
            return payload[key]
    return None


def _extract_external_order_id(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None

    direct_value = _extract_first(payload, ["id", "orderId", "order_id"])
    if direct_value is not None:
        text = str(direct_value).strip()
        return text or None

    nested_payload = payload.get("data")
    if isinstance(nested_payload, list) and nested_payload:
        first_item = nested_payload[0]
        if isinstance(first_item, dict):
            nested_value = _extract_first(first_item, ["id", "orderId", "order_id"])
            if nested_value is not None:
                text = str(nested_value).strip()
                return text or None

    if isinstance(nested_payload, dict):
        nested_value = _extract_first(nested_payload, ["id", "orderId", "order_id"])
        if nested_value is not None:
            text = str(nested_value).strip()
            return text or None

    return None


class AppCycleResult(BaseModel):
    challenge_context: ActiveChallengeContext | None
    synced_state: AgentState | None
    strategy_result: StrategyRunResult | None
    post_cycle_state: AgentState | None
    execution_response: dict | None = None
    submitted_order: bool = False
    replaced_order: bool = False
    skipped_reason: str | None = None
    risk_guard_result: RiskGuardResult | None = None
    health_guard_result: HealthGuardResult | None = None


def run_app_cycle(
    client: ProprClient,
    order_service: ProprOrderService,
    symbol: str,
    candles: list[Candle],
    config: StrategyConfig,
    account_balance: float,
    previous_state: AgentState | None = None,
    max_allowed_drawdown: float | None = None,
    require_healthy_core: bool = True,
    allow_execution: bool = True,
) -> AppCycleResult:
    health_guard_result: HealthGuardResult | None = None
    if require_healthy_core:
        health_guard_result = fetch_and_check_core_service_health(client)
        if not health_guard_result.allow_trading:
            return AppCycleResult(
                challenge_context=None,
                synced_state=None,
                strategy_result=None,
                post_cycle_state=None,
                execution_response=None,
                submitted_order=False,
                replaced_order=False,
                skipped_reason=health_guard_result.reason,
                risk_guard_result=None,
                health_guard_result=health_guard_result,
            )

    challenge_context = get_active_challenge_context(client)
    if challenge_context is None:
        risk_guard_result = evaluate_execution_guards(None, max_allowed_drawdown=max_allowed_drawdown)
        return AppCycleResult(
            challenge_context=None,
            synced_state=None,
            strategy_result=None,
            post_cycle_state=None,
            skipped_reason="no active challenge",
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
        )

    account_id = challenge_context.account_id
    synced_state = sync_agent_state_from_propr(client, account_id, previous_state)
    strategy_result, post_cycle_state = run_agent_cycle(
        candles=candles,
        config=config,
        account_balance=account_balance,
        state=synced_state,
    )
    risk_guard_result = evaluate_execution_guards(
        challenge_context,
        max_allowed_drawdown=max_allowed_drawdown,
    )

    execution_response: dict | None = None
    submitted_order = False
    replaced_order = False

    if not risk_guard_result.allow_execution:
        return AppCycleResult(
            challenge_context=challenge_context,
            synced_state=synced_state,
            strategy_result=strategy_result,
            post_cycle_state=post_cycle_state,
            execution_response=None,
            submitted_order=False,
            replaced_order=False,
            skipped_reason=risk_guard_result.reason,
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
        )

    if not allow_execution:
        return AppCycleResult(
            challenge_context=challenge_context,
            synced_state=synced_state,
            strategy_result=strategy_result,
            post_cycle_state=post_cycle_state,
            execution_response=None,
            submitted_order=False,
            replaced_order=False,
            skipped_reason=None,
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
        )

    if post_cycle_state.pending_order is not None:
        if synced_state.pending_order is not None:
            execution_response = safe_replace_pending_order(
                order_service=order_service,
                account_id=account_id,
                symbol=symbol,
                state=synced_state,
                new_order=post_cycle_state.pending_order,
            )
            replaced_order = True
            if isinstance(execution_response, dict):
                submit_response = execution_response.get("submit")
                post_cycle_state = post_cycle_state.copy(
                    update={
                        "pending_order_id": _extract_external_order_id(submit_response),
                    }
                )
        else:
            execution_response = submit_agent_order_if_allowed(
                order_service=order_service,
                account_id=account_id,
                symbol=symbol,
                state=synced_state,
                order=post_cycle_state.pending_order,
            )
            if execution_response is not None:
                submitted_order = True
                post_cycle_state = post_cycle_state.copy(
                    update={
                        "pending_order_id": _extract_external_order_id(execution_response),
                    }
                )

    return AppCycleResult(
        challenge_context=challenge_context,
        synced_state=synced_state,
        strategy_result=strategy_result,
        post_cycle_state=post_cycle_state,
        execution_response=execution_response,
        submitted_order=submitted_order,
        replaced_order=replaced_order,
        skipped_reason=None,
        risk_guard_result=risk_guard_result,
        health_guard_result=health_guard_result,
    )

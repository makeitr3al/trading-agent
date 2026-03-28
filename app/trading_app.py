from typing import Any

from pydantic import BaseModel

from app.risk_guard import RiskGuardResult, evaluate_execution_guards
from broker.asset_guard import AssetGuardResult, evaluate_asset_execution_guard
from broker.challenge_service import get_active_challenge_context
from broker.execution import (
    manage_active_trade_exit_orders,
    safe_replace_pending_order,
    submit_active_trade_close_if_allowed,
    submit_agent_order_if_allowed,
)
from broker.health_guard import HealthGuardResult, fetch_and_check_core_service_health
from broker.order_service import ProprOrderService, apply_symbol_spec_to_order
from broker.propr_client import ProprClient
from broker.state_sync import sync_agent_state_from_propr
from config.strategy_config import StrategyConfig
from models.candle import Candle
from models.order import Order
from models.propr_challenge import ActiveChallengeContext
from models.runner_result import StrategyRunResult
from models.symbol_spec import SymbolSpec
from strategy.engine import run_agent_cycle
from strategy.position_sizer import calculate_position_size
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



def _apply_symbol_specific_position_size(
    order: Order,
    config: StrategyConfig,
    account_balance: float,
    desired_leverage: int,
    symbol_spec: SymbolSpec,
) -> Order:
    sizing_result = calculate_position_size(
        entry=order.entry,
        stop_loss=order.stop_loss,
        account_balance=account_balance,
        risk_per_trade_pct=config.risk_per_trade_pct,
        desired_leverage=desired_leverage,
        symbol_spec=symbol_spec,
    )
    prepared_order = order
    if sizing_result.position_size is not None:
        prepared_order = order.copy(update={"position_size": sizing_result.position_size})
    return apply_symbol_spec_to_order(prepared_order, symbol_spec)



def _derive_outside_band_sweet_spot(symbol_spec: SymbolSpec | None) -> float:
    if symbol_spec is None or symbol_spec.price_decimals is None:
        return 0.0
    return 2 * (10 ** (-symbol_spec.price_decimals))


class AppCycleResult(BaseModel):
    challenge_context: ActiveChallengeContext | None
    synced_state: AgentState | None
    strategy_result: StrategyRunResult | None
    post_cycle_state: AgentState | None
    execution_response: dict | None = None
    submitted_order: bool = False
    replaced_order: bool = False
    closed_trade: bool = False
    managed_exit_orders: bool = False
    skipped_reason: str | None = None
    risk_guard_result: RiskGuardResult | None = None
    health_guard_result: HealthGuardResult | None = None
    asset_guard_result: AssetGuardResult | None = None
    symbol_spec_loaded: bool = False



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
    desired_leverage: int = 1,
    symbol_spec: SymbolSpec | None = None,
    data_source: str = "live",
) -> AppCycleResult:
    health_guard_result: HealthGuardResult | None = None
    config = config.copy(update={"outside_band_sweet_spot": _derive_outside_band_sweet_spot(symbol_spec)})
    symbol_spec_loaded = symbol_spec is not None
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
                closed_trade=False,
                managed_exit_orders=False,
                skipped_reason=health_guard_result.reason,
                risk_guard_result=None,
                health_guard_result=health_guard_result,
                asset_guard_result=None,
                symbol_spec_loaded=symbol_spec_loaded,
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
            asset_guard_result=None,
            symbol_spec_loaded=symbol_spec_loaded,
        )

    account_id = challenge_context.account_id
    synced_state = sync_agent_state_from_propr(client, account_id, previous_state)
    strategy_result, post_cycle_state = run_agent_cycle(
        candles=candles,
        config=config,
        account_balance=account_balance,
        state=synced_state,
    )

    if symbol_spec is not None and post_cycle_state.pending_order is not None:
        resized_order = _apply_symbol_specific_position_size(
            order=post_cycle_state.pending_order,
            config=config,
            account_balance=account_balance,
            desired_leverage=desired_leverage,
            symbol_spec=symbol_spec,
        )
        post_cycle_state = post_cycle_state.copy(update={"pending_order": resized_order})
        if strategy_result.order is not None:
            strategy_result = strategy_result.copy(update={"order": resized_order})

    risk_guard_result = evaluate_execution_guards(
        challenge_context,
        max_allowed_drawdown=max_allowed_drawdown,
    )

    execution_response: dict | None = None
    submitted_order = False
    replaced_order = False
    closed_trade = False
    managed_exit_orders = False
    asset_guard_result: AssetGuardResult | None = None

    if not risk_guard_result.allow_execution:
        return AppCycleResult(
            challenge_context=challenge_context,
            synced_state=synced_state,
            strategy_result=strategy_result,
            post_cycle_state=post_cycle_state,
            execution_response=None,
            submitted_order=False,
            replaced_order=False,
            closed_trade=False,
            managed_exit_orders=False,
            skipped_reason=risk_guard_result.reason,
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
            asset_guard_result=None,
            symbol_spec_loaded=symbol_spec_loaded,
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
            closed_trade=False,
            managed_exit_orders=False,
            skipped_reason=None,
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
            asset_guard_result=None,
            symbol_spec_loaded=symbol_spec_loaded,
        )

    close_requested = strategy_result.close_active_trade and synced_state.active_trade is not None
    pending_order_requested = post_cycle_state.pending_order is not None
    exit_order_update_requested = (
        synced_state.active_trade is not None
        and post_cycle_state.active_trade is not None
        and strategy_result.updated_trade is not None
        and not strategy_result.close_active_trade
    )

    if (pending_order_requested or close_requested or exit_order_update_requested) and data_source == "golden":
        return AppCycleResult(
            challenge_context=challenge_context,
            synced_state=synced_state,
            strategy_result=strategy_result,
            post_cycle_state=post_cycle_state,
            execution_response=None,
            submitted_order=False,
            replaced_order=False,
            closed_trade=False,
            managed_exit_orders=False,
            skipped_reason="submit is not allowed with golden data source",
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
            asset_guard_result=None,
            symbol_spec_loaded=symbol_spec_loaded,
        )

    if (
        pending_order_requested
        and data_source == "live"
        and allow_execution
        and isinstance(client, ProprClient)
        and symbol_spec is None
    ):
        return AppCycleResult(
            challenge_context=challenge_context,
            synced_state=synced_state,
            strategy_result=strategy_result,
            post_cycle_state=post_cycle_state,
            execution_response=None,
            submitted_order=False,
            replaced_order=False,
            closed_trade=False,
            managed_exit_orders=False,
            skipped_reason="missing symbol spec for live execution",
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
            asset_guard_result=None,
            symbol_spec_loaded=symbol_spec_loaded,
        )

    if close_requested:
        execution_response = submit_active_trade_close_if_allowed(
            order_service=order_service,
            account_id=account_id,
            symbol=symbol,
            state=synced_state,
            close_active_trade=True,
        )
        closed_trade = execution_response is not None
        return AppCycleResult(
            challenge_context=challenge_context,
            synced_state=synced_state,
            strategy_result=strategy_result,
            post_cycle_state=post_cycle_state,
            execution_response=execution_response,
            submitted_order=False,
            replaced_order=False,
            closed_trade=closed_trade,
            managed_exit_orders=False,
            skipped_reason=None,
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
            asset_guard_result=None,
            symbol_spec_loaded=symbol_spec_loaded,
        )

    if exit_order_update_requested:
        execution_response = manage_active_trade_exit_orders(
            order_service=order_service,
            account_id=account_id,
            symbol=symbol,
            state=synced_state,
            updated_trade=post_cycle_state.active_trade,
            buy_spread=config.buy_spread,
        )
        managed_exit_orders = execution_response is not None
        if execution_response is not None:
            stop_loss_payload = (
                execution_response.get("stop_loss")
                if isinstance(execution_response, dict)
                else None
            )
            take_profit_payload = (
                execution_response.get("take_profit")
                if isinstance(execution_response, dict)
                else None
            )
            post_cycle_state = post_cycle_state.copy(
                update={
                    "stop_loss_order_id": (stop_loss_payload or {}).get("order_id"),
                    "take_profit_order_id": (take_profit_payload or {}).get("order_id"),
                }
            )
        return AppCycleResult(
            challenge_context=challenge_context,
            synced_state=synced_state,
            strategy_result=strategy_result,
            post_cycle_state=post_cycle_state,
            execution_response=execution_response,
            submitted_order=False,
            replaced_order=False,
            closed_trade=False,
            managed_exit_orders=managed_exit_orders,
            skipped_reason=None,
            risk_guard_result=risk_guard_result,
            health_guard_result=health_guard_result,
            asset_guard_result=None,
            symbol_spec_loaded=symbol_spec_loaded,
        )

    if pending_order_requested:
        asset_guard_result = evaluate_asset_execution_guard(
            client=client,
            account_id=account_id,
            symbol=symbol,
            desired_leverage=desired_leverage,
        )
        if not asset_guard_result.allow_execution:
            return AppCycleResult(
                challenge_context=challenge_context,
                synced_state=synced_state,
                strategy_result=strategy_result,
                post_cycle_state=post_cycle_state,
                execution_response=None,
                submitted_order=False,
                replaced_order=False,
                closed_trade=False,
                managed_exit_orders=False,
                skipped_reason=asset_guard_result.reason,
                risk_guard_result=risk_guard_result,
                health_guard_result=health_guard_result,
                asset_guard_result=asset_guard_result,
                symbol_spec_loaded=symbol_spec_loaded,
            )

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
        closed_trade=closed_trade,
        managed_exit_orders=managed_exit_orders,
        skipped_reason=None,
        risk_guard_result=risk_guard_result,
        health_guard_result=health_guard_result,
        asset_guard_result=asset_guard_result,
        symbol_spec_loaded=symbol_spec_loaded,
    )

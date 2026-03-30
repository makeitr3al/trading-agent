from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.journal import append_journal_entries, build_journal_entries
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
from models.journal import JournalEntry
from models.order import Order, OrderType
from models.propr_challenge import ActiveChallengeContext
from models.runner_result import StrategyRunResult
from models.symbol_spec import SymbolSpec
from strategy.engine import run_agent_cycle
from strategy.position_sizer import calculate_position_size, evaluate_position_size_execution
from strategy.state import AgentState

# TODO: Later add challenge-specific risk limits.
# TODO: Later load account balance directly from Propr.
# TODO: Later add automatic symbol selection.
# TODO: Later add trade close/modify calls to Propr.
# TODO: Later add looping and scheduling.


MAX_OPEN_ORDER_TRADE_SLOTS = 3


def _beta_blocks_standalone_entry_order(order: Order | None, environment: str | None) -> bool:
    if (environment or "").strip().lower() != "beta" or order is None:
        return False
    return order.order_type in {OrderType.BUY_STOP, OrderType.SELL_STOP}


def _count_open_order_trade_slots(state: AgentState | None) -> int:
    if state is None:
        return 0

    return (
        int(getattr(state, "account_open_entry_orders_count", 0) or 0)
        + int(getattr(state, "account_open_positions_count", 0) or 0)
    )


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
    prepared_order = order.model_copy(update={"position_size": sizing_result.position_size})
    return apply_symbol_spec_to_order(prepared_order, symbol_spec)



def _validate_pending_order_execution_size(
    order: Order,
    account_balance: float,
    desired_leverage: int,
    symbol_spec: SymbolSpec | None,
) -> str | None:
    if order.position_size is None:
        return "position size unavailable"

    sizing_execution_result = evaluate_position_size_execution(
        entry=order.entry,
        position_size=order.position_size,
        account_balance=account_balance,
        desired_leverage=desired_leverage,
        max_leverage=symbol_spec.max_leverage if symbol_spec is not None else None,
    )
    return sizing_execution_result.reason



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
    journal_entries: list[JournalEntry] = Field(default_factory=list)
    journal_path: str | None = None


def _build_app_cycle_result(
    symbol: str,
    environment: str | None,
    candles: list[Candle],
    journal_path: str | Path | None,
    challenge_context: ActiveChallengeContext | None,
    synced_state: AgentState | None,
    strategy_result: StrategyRunResult | None,
    post_cycle_state: AgentState | None,
    execution_response: dict | None = None,
    submitted_order: bool = False,
    replaced_order: bool = False,
    closed_trade: bool = False,
    managed_exit_orders: bool = False,
    skipped_reason: str | None = None,
    risk_guard_result: RiskGuardResult | None = None,
    health_guard_result: HealthGuardResult | None = None,
    asset_guard_result: AssetGuardResult | None = None,
    symbol_spec_loaded: bool = False,
) -> AppCycleResult:
    result = AppCycleResult(
        challenge_context=challenge_context,
        synced_state=synced_state,
        strategy_result=strategy_result,
        post_cycle_state=post_cycle_state,
        execution_response=execution_response,
        submitted_order=submitted_order,
        replaced_order=replaced_order,
        closed_trade=closed_trade,
        managed_exit_orders=managed_exit_orders,
        skipped_reason=skipped_reason,
        risk_guard_result=risk_guard_result,
        health_guard_result=health_guard_result,
        asset_guard_result=asset_guard_result,
        symbol_spec_loaded=symbol_spec_loaded,
        journal_path=str(journal_path) if journal_path is not None else None,
    )

    if strategy_result is None or not candles:
        return result

    cycle_timestamp = candles[-1].timestamp.isoformat()
    journal_entries = build_journal_entries(
        symbol=symbol,
        environment=environment,
        cycle_timestamp=cycle_timestamp,
        strategy_result=strategy_result,
        synced_active_trade=synced_state.active_trade if synced_state is not None else None,
        pending_order=post_cycle_state.pending_order if post_cycle_state is not None else None,
        submitted_order=submitted_order,
        replaced_order=replaced_order,
        closed_trade=closed_trade,
        skipped_reason=skipped_reason,
        exit_price=float(candles[-1].close),
    )
    result = result.model_copy(update={"journal_entries": journal_entries})

    if journal_path is not None and journal_entries:
        append_journal_entries(journal_path, journal_entries)

    return result



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
    journal_path: str | Path | None = None,
) -> AppCycleResult:
    health_guard_result: HealthGuardResult | None = None
    environment = getattr(getattr(client, "config", None), "environment", None)
    config = config.model_copy(update={"outside_band_sweet_spot": _derive_outside_band_sweet_spot(symbol_spec)})
    symbol_spec_loaded = symbol_spec is not None
    if require_healthy_core:
        health_guard_result = fetch_and_check_core_service_health(client)
        if not health_guard_result.allow_trading:
            return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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
        return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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
    try:
        synced_state = sync_agent_state_from_propr(client, account_id, previous_state, symbol=symbol)
    except TypeError as exc:
        if "unexpected keyword argument 'symbol'" not in str(exc):
            raise
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
        post_cycle_state = post_cycle_state.model_copy(update={"pending_order": resized_order})
        if strategy_result.order is not None:
            strategy_result = strategy_result.model_copy(update={"order": resized_order})

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
        return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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
        return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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
        return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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
        return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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
        return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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
            post_cycle_state = post_cycle_state.model_copy(
                update={
                    "stop_loss_order_id": (stop_loss_payload or {}).get("order_id"),
                    "take_profit_order_id": (take_profit_payload or {}).get("order_id"),
                }
            )
        return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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
        open_order_trade_slots = _count_open_order_trade_slots(synced_state)
        new_entry_requested = synced_state.pending_order is None
        if new_entry_requested and open_order_trade_slots >= MAX_OPEN_ORDER_TRADE_SLOTS:
            return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
                challenge_context=challenge_context,
                synced_state=synced_state,
                strategy_result=strategy_result,
                post_cycle_state=post_cycle_state,
                execution_response=None,
                submitted_order=False,
                replaced_order=False,
                closed_trade=False,
                managed_exit_orders=False,
                skipped_reason=f"max open orders/trades reached ({open_order_trade_slots}/{MAX_OPEN_ORDER_TRADE_SLOTS})",
                risk_guard_result=risk_guard_result,
                health_guard_result=health_guard_result,
                asset_guard_result=None,
                symbol_spec_loaded=symbol_spec_loaded,
            )

        if _beta_blocks_standalone_entry_order(post_cycle_state.pending_order, environment):
            return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
                challenge_context=challenge_context,
                synced_state=synced_state,
                strategy_result=strategy_result,
                post_cycle_state=post_cycle_state,
                execution_response=None,
                submitted_order=False,
                replaced_order=False,
                closed_trade=False,
                managed_exit_orders=False,
                skipped_reason="beta does not support standalone stop entries",
                risk_guard_result=risk_guard_result,
                health_guard_result=health_guard_result,
                asset_guard_result=None,
                symbol_spec_loaded=symbol_spec_loaded,
            )

        asset_guard_result = evaluate_asset_execution_guard(
            client=client,
            account_id=account_id,
            symbol=symbol,
            desired_leverage=desired_leverage,
        )
        if not asset_guard_result.allow_execution:
            return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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

        pending_order_size_reason = _validate_pending_order_execution_size(
            order=post_cycle_state.pending_order,
            account_balance=account_balance,
            desired_leverage=desired_leverage,
            symbol_spec=symbol_spec,
        )
        if pending_order_size_reason is not None:
            return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
                challenge_context=challenge_context,
                synced_state=synced_state,
                strategy_result=strategy_result,
                post_cycle_state=post_cycle_state,
                execution_response=None,
                submitted_order=False,
                replaced_order=False,
                closed_trade=False,
                managed_exit_orders=False,
                skipped_reason=pending_order_size_reason,
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
                post_cycle_state = post_cycle_state.model_copy(
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
                post_cycle_state = post_cycle_state.model_copy(
                    update={
                        "pending_order_id": _extract_external_order_id(execution_response),
                    }
                )

    return _build_app_cycle_result(
                symbol=symbol,
                environment=environment,
                candles=candles,
                journal_path=journal_path,
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


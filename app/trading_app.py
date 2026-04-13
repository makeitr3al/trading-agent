from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from app.app_cycle_helpers import (
    _apply_symbol_specific_position_size,
    _beta_blocks_standalone_entry_order,
    _count_open_order_trade_slots,
    _validate_pending_order_execution_size,
)
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
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.state_sync import sync_agent_state_from_propr
from config.strategy_config import StrategyConfig
from models.candle import Candle
from models.journal import JournalEntry
from models.order import Order
from models.propr_challenge import ActiveChallengeContext
from models.runner_result import StrategyRunResult
from models.symbol_spec import SymbolSpec
from strategy.engine import run_agent_cycle
from strategy.state import AgentState
from utils.propr_response import extract_external_order_id

# TODO: Later add challenge-specific risk limits.
# TODO: Later load account balance directly from Propr.
# TODO: Later add automatic symbol selection.
# TODO: Later add trade close/modify calls to Propr.
# TODO: Later add looping and scheduling.


MAX_OPEN_ORDER_TRADE_SLOTS = 3


def _stable_intent_seed_for_entry_order(
    *,
    account_id: str,
    symbol: str,
    executed_at: str | None,
    order: Order,
) -> str | None:
    if executed_at is None or not str(executed_at).strip():
        return None
    return (
        f"{account_id}|{symbol}|{str(executed_at).strip()}|{order.order_type}|{order.entry}|"
        f"{order.stop_loss}|{order.take_profit}|{order.position_size}|{order.signal_source}"
    )


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
    previous_state: AgentState | None = None,
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
    executed_at: str | None = None,
    journal_emit_pending_order: bool = True,
    scan_effective_submit_allowed: bool | None = None,
    scan_cycle_phase: str | None = None,
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
    if executed_at is None:
        executed_at = datetime.now(timezone.utc).isoformat()
    signal_lifecycle_id = (
        post_cycle_state.signal_lifecycle_id if post_cycle_state is not None else None
    )
    journal_entries = build_journal_entries(
        symbol=symbol,
        environment=environment,
        cycle_timestamp=cycle_timestamp,
        executed_at=executed_at,
        strategy_result=strategy_result,
        synced_state=synced_state,
        post_cycle_state=post_cycle_state,
        previous_state=previous_state,
        submitted_order=submitted_order,
        replaced_order=replaced_order,
        closed_trade=closed_trade,
        skipped_reason=skipped_reason,
        exit_price=float(candles[-1].close),
        journal_emit_pending_order=journal_emit_pending_order,
        signal_lifecycle_id=signal_lifecycle_id,
        managed_exit_orders=managed_exit_orders,
        scan_effective_submit_allowed=scan_effective_submit_allowed,
        scan_cycle_phase=scan_cycle_phase,
    )
    result = result.model_copy(update={"journal_entries": journal_entries})

    if journal_path is not None and journal_entries:
        append_journal_entries(journal_path, journal_entries)

    return result



@dataclass
class _CycleContext:
    """Accumulated state flowing through the phases of run_app_cycle."""

    # Inputs — set once at construction
    client: ProprClient
    order_service: ProprOrderService
    symbol: str
    candles: list[Candle]
    config: StrategyConfig
    account_balance: float
    previous_state: AgentState | None
    max_allowed_drawdown: float | None
    require_healthy_core: bool
    allow_execution: bool
    desired_leverage: int
    symbol_spec: SymbolSpec | None
    data_source: str
    journal_path: str | Path | None
    environment: str | None
    symbol_spec_loaded: bool
    challenge_id: str | None = None
    journal_emit_pending_order: bool = True
    scan_effective_submit_allowed: bool | None = None
    scan_cycle_phase: str | None = None
    resolved_balance: float | None = None

    # Accumulated state — mutated by phases
    challenge_context: ActiveChallengeContext | None = None
    synced_state: AgentState | None = None
    strategy_result: StrategyRunResult | None = None
    post_cycle_state: AgentState | None = None
    execution_response: dict | None = None
    submitted_order: bool = False
    replaced_order: bool = False
    closed_trade: bool = False
    managed_exit_orders: bool = False
    skipped_reason: str | None = None
    risk_guard_result: RiskGuardResult | None = None
    health_guard_result: HealthGuardResult | None = None
    asset_guard_result: AssetGuardResult | None = None
    close_requested: bool = False
    pending_order_requested: bool = False
    exit_order_update_requested: bool = False
    executed_at: str | None = None

    def build_result(self) -> AppCycleResult:
        return _build_app_cycle_result(
            symbol=self.symbol,
            environment=self.environment,
            candles=self.candles,
            journal_path=self.journal_path,
            challenge_context=self.challenge_context,
            synced_state=self.synced_state,
            strategy_result=self.strategy_result,
            post_cycle_state=self.post_cycle_state,
            previous_state=self.previous_state,
            execution_response=self.execution_response,
            submitted_order=self.submitted_order,
            replaced_order=self.replaced_order,
            closed_trade=self.closed_trade,
            managed_exit_orders=self.managed_exit_orders,
            skipped_reason=self.skipped_reason,
            risk_guard_result=self.risk_guard_result,
            health_guard_result=self.health_guard_result,
            asset_guard_result=self.asset_guard_result,
            symbol_spec_loaded=self.symbol_spec_loaded,
            executed_at=self.executed_at,
            journal_emit_pending_order=self.journal_emit_pending_order,
            scan_effective_submit_allowed=self.scan_effective_submit_allowed,
            scan_cycle_phase=self.scan_cycle_phase,
        )


def _phase_health_guard(ctx: _CycleContext) -> AppCycleResult | None:
    if not ctx.require_healthy_core:
        return None
    ctx.health_guard_result = fetch_and_check_core_service_health(ctx.client)
    if not ctx.health_guard_result.allow_trading:
        ctx.skipped_reason = ctx.health_guard_result.reason
        return ctx.build_result()
    return None


def _phase_challenge_validation(ctx: _CycleContext) -> AppCycleResult | None:
    ctx.challenge_context = get_active_challenge_context(ctx.client, challenge_id=ctx.challenge_id)
    if ctx.challenge_context is None:
        ctx.risk_guard_result = evaluate_execution_guards(
            None, max_allowed_drawdown=ctx.max_allowed_drawdown,
        )
        ctx.skipped_reason = "no active challenge"
        return ctx.build_result()

    if ctx.challenge_context.account_balance is not None:
        ctx.resolved_balance = ctx.challenge_context.account_balance.margin_balance
    return None


def _phase_strategy_execution(ctx: _CycleContext) -> AppCycleResult | None:
    account_id = ctx.challenge_context.account_id
    try:
        ctx.synced_state = sync_agent_state_from_propr(
            ctx.client, account_id, ctx.previous_state, symbol=ctx.symbol,
        )
    except TypeError as exc:
        if "unexpected keyword argument 'symbol'" not in str(exc):
            raise
        ctx.synced_state = sync_agent_state_from_propr(
            ctx.client, account_id, ctx.previous_state,
        )

    effective_balance = ctx.resolved_balance or ctx.account_balance

    ctx.strategy_result, ctx.post_cycle_state = run_agent_cycle(
        candles=ctx.candles,
        config=ctx.config,
        account_balance=effective_balance,
        state=ctx.synced_state,
    )

    if ctx.symbol_spec is not None and ctx.post_cycle_state.pending_order is not None:
        resized_order = _apply_symbol_specific_position_size(
            order=ctx.post_cycle_state.pending_order,
            config=ctx.config,
            account_balance=effective_balance,
            desired_leverage=ctx.desired_leverage,
            symbol_spec=ctx.symbol_spec,
        )
        ctx.post_cycle_state = ctx.post_cycle_state.model_copy(update={"pending_order": resized_order})
        if ctx.strategy_result.order is not None:
            ctx.strategy_result = ctx.strategy_result.model_copy(update={"order": resized_order})

    return None


def _phase_guard_checks(ctx: _CycleContext) -> AppCycleResult | None:
    ctx.risk_guard_result = evaluate_execution_guards(
        ctx.challenge_context,
        max_allowed_drawdown=ctx.max_allowed_drawdown,
    )
    if not ctx.risk_guard_result.allow_execution:
        ctx.skipped_reason = ctx.risk_guard_result.reason
        return ctx.build_result()
    if not ctx.allow_execution:
        return ctx.build_result()
    return None


def _phase_precondition_checks(ctx: _CycleContext) -> AppCycleResult | None:
    ctx.close_requested = (
        ctx.strategy_result.close_active_trade
        and ctx.synced_state.active_trade is not None
    )
    ctx.pending_order_requested = ctx.post_cycle_state.pending_order is not None
    ctx.exit_order_update_requested = (
        ctx.synced_state.active_trade is not None
        and ctx.post_cycle_state.active_trade is not None
        and ctx.strategy_result.updated_trade is not None
        and not ctx.strategy_result.close_active_trade
    )

    if (ctx.pending_order_requested or ctx.close_requested or ctx.exit_order_update_requested) and ctx.data_source == "golden":
        ctx.skipped_reason = "submit is not allowed with golden data source"
        return ctx.build_result()

    if (
        ctx.pending_order_requested
        and ctx.data_source == "live"
        and ctx.allow_execution
        and isinstance(ctx.client, ProprClient)
        and ctx.symbol_spec is None
    ):
        ctx.skipped_reason = "missing symbol spec for live execution"
        return ctx.build_result()

    return None


def _phase_close_trade(ctx: _CycleContext) -> AppCycleResult | None:
    if not ctx.close_requested:
        return None
    account_id = ctx.challenge_context.account_id
    ctx.execution_response = submit_active_trade_close_if_allowed(
        order_service=ctx.order_service,
        account_id=account_id,
        symbol=ctx.symbol,
        state=ctx.synced_state,
        close_active_trade=True,
    )
    ctx.closed_trade = ctx.execution_response is not None
    return ctx.build_result()


def _phase_exit_orders(ctx: _CycleContext) -> AppCycleResult | None:
    if not ctx.exit_order_update_requested:
        return None
    account_id = ctx.challenge_context.account_id
    ctx.execution_response = manage_active_trade_exit_orders(
        order_service=ctx.order_service,
        account_id=account_id,
        symbol=ctx.symbol,
        state=ctx.synced_state,
        updated_trade=ctx.post_cycle_state.active_trade,
        buy_spread=ctx.config.buy_spread,
    )
    ctx.managed_exit_orders = ctx.execution_response is not None
    if ctx.execution_response is not None:
        stop_loss_payload = (
            ctx.execution_response.get("stop_loss")
            if isinstance(ctx.execution_response, dict)
            else None
        )
        take_profit_payload = (
            ctx.execution_response.get("take_profit")
            if isinstance(ctx.execution_response, dict)
            else None
        )
        ctx.post_cycle_state = ctx.post_cycle_state.model_copy(
            update={
                "stop_loss_order_id": (stop_loss_payload or {}).get("order_id"),
                "take_profit_order_id": (take_profit_payload or {}).get("order_id"),
            }
        )
    return ctx.build_result()


def _phase_pending_order(ctx: _CycleContext) -> AppCycleResult | None:
    if not ctx.pending_order_requested:
        return None

    account_id = ctx.challenge_context.account_id
    open_order_trade_slots = _count_open_order_trade_slots(ctx.synced_state)
    new_entry_requested = ctx.synced_state.pending_order is None

    if new_entry_requested and open_order_trade_slots >= MAX_OPEN_ORDER_TRADE_SLOTS:
        ctx.skipped_reason = (
            f"max open orders/trades reached ({open_order_trade_slots}/{MAX_OPEN_ORDER_TRADE_SLOTS})"
        )
        return ctx.build_result()

    if _beta_blocks_standalone_entry_order(ctx.post_cycle_state.pending_order, ctx.environment):
        ctx.skipped_reason = "beta does not support standalone stop entries"
        return ctx.build_result()

    ctx.asset_guard_result = evaluate_asset_execution_guard(
        client=ctx.client,
        account_id=account_id,
        symbol=ctx.symbol,
        desired_leverage=ctx.desired_leverage,
    )
    if not ctx.asset_guard_result.allow_execution:
        ctx.skipped_reason = ctx.asset_guard_result.reason
        return ctx.build_result()

    effective_balance = ctx.resolved_balance or ctx.account_balance
    effective_leverage = ctx.asset_guard_result.effective_leverage
    pending_order_size_reason = _validate_pending_order_execution_size(
        order=ctx.post_cycle_state.pending_order,
        account_balance=effective_balance,
        desired_leverage=effective_leverage,
        symbol_spec=ctx.symbol_spec,
    )
    if pending_order_size_reason is not None:
        ctx.skipped_reason = pending_order_size_reason
        return ctx.build_result()

    stable_seed = _stable_intent_seed_for_entry_order(
        account_id=account_id,
        symbol=ctx.symbol,
        executed_at=ctx.executed_at,
        order=ctx.post_cycle_state.pending_order,
    )

    if ctx.synced_state.pending_order is not None:
        ctx.execution_response = safe_replace_pending_order(
            order_service=ctx.order_service,
            account_id=account_id,
            symbol=ctx.symbol,
            state=ctx.synced_state,
            new_order=ctx.post_cycle_state.pending_order,
            stable_intent_seed=stable_seed,
        )
        ctx.replaced_order = True
        if isinstance(ctx.execution_response, dict):
            submit_response = ctx.execution_response.get("submit")
            ctx.post_cycle_state = ctx.post_cycle_state.model_copy(
                update={
                    "pending_order_id": extract_external_order_id(submit_response),
                }
            )
    else:
        submit_outcome = submit_agent_order_if_allowed(
            order_service=ctx.order_service,
            account_id=account_id,
            symbol=ctx.symbol,
            state=ctx.synced_state,
            order=ctx.post_cycle_state.pending_order,
            stable_intent_seed=stable_seed,
        )
        ctx.execution_response = submit_outcome.response
        if submit_outcome.response is not None:
            ctx.submitted_order = True
            ctx.post_cycle_state = ctx.post_cycle_state.model_copy(
                update={
                    "pending_order_id": extract_external_order_id(submit_outcome.response),
                }
            )
        elif submit_outcome.existing_external_order_id is not None:
            ctx.post_cycle_state = ctx.post_cycle_state.model_copy(
                update={"pending_order_id": submit_outcome.existing_external_order_id},
            )
        elif ctx.skipped_reason is None and submit_outcome.skip_reason is not None:
            ctx.skipped_reason = submit_outcome.skip_reason

    return None


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
    executed_at: str | None = None,
    challenge_id: str | None = None,
    journal_emit_pending_order: bool = True,
    scan_effective_submit_allowed: bool | None = None,
    scan_cycle_phase: str | None = None,
) -> AppCycleResult:
    if executed_at is None:
        executed_at = datetime.now(timezone.utc).isoformat()

    ctx = _CycleContext(
        client=client,
        order_service=order_service,
        symbol=symbol,
        candles=candles,
        config=config,
        account_balance=account_balance,
        previous_state=previous_state,
        max_allowed_drawdown=max_allowed_drawdown,
        require_healthy_core=require_healthy_core,
        allow_execution=allow_execution,
        desired_leverage=desired_leverage,
        symbol_spec=symbol_spec,
        data_source=data_source,
        journal_path=journal_path,
        environment=getattr(getattr(client, "config", None), "environment", None),
        symbol_spec_loaded=symbol_spec is not None,
        executed_at=executed_at,
        challenge_id=challenge_id,
        journal_emit_pending_order=journal_emit_pending_order,
        scan_effective_submit_allowed=scan_effective_submit_allowed,
        scan_cycle_phase=scan_cycle_phase,
    )

    for phase in [
        _phase_health_guard,
        _phase_challenge_validation,
        _phase_strategy_execution,
        _phase_guard_checks,
        _phase_precondition_checks,
        _phase_close_trade,
        _phase_exit_orders,
        _phase_pending_order,
    ]:
        result = phase(ctx)
        if result is not None:
            return result

    return ctx.build_result()


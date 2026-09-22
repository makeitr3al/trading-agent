"""Runtime helpers for virtual-stop watch: trade touch, candle catch-up, submit."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.armed_stop_submit import execute_armed_stop_market_bracket
from broker.asset_guard import evaluate_asset_execution_guard
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from models.agent_state import AgentState
from models.candle import Candle
from models.order import Order, OrderType
from models.symbol_spec import SymbolSpec
from strategy.trigger_eval import is_stop_trigger_touched, is_stop_trigger_touched_by_trade


@dataclass(frozen=True)
class ArmedStopTouchOutcome:
    submitted: bool
    disarmed: bool
    skipped_reason: str | None = None
    response: dict[str, Any] | None = None
    pending_order_id: str | None = None
    order: Order | None = None
    signal_lifecycle_id: str | None = None
    decision_detail: str | None = None


def _broker_has_resting_entry(state: AgentState) -> bool:
    if state.pending_order_id is not None and str(state.pending_order_id).strip():
        return True
    pending = state.pending_order
    if pending is None:
        return False
    return pending.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}


def try_submit_on_trade_print(
    *,
    client: ProprClient,
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    state: AgentState,
    trade_price: Decimal | float | str,
    account_balance: float,
    desired_leverage: int = 1,
    symbol_spec: SymbolSpec | None = None,
    buy_spread: float = 0.0,
    asset_guard_result: Any | None = None,
) -> ArmedStopTouchOutcome:
    order = state.pending_order
    if order is None or order.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        return ArmedStopTouchOutcome(submitted=False, disarmed=True, skipped_reason="no stop pending")
    if _broker_has_resting_entry(state):
        return ArmedStopTouchOutcome(submitted=False, disarmed=False, skipped_reason="broker resting entry")
    if not is_stop_trigger_touched_by_trade(order, trade_price):
        return ArmedStopTouchOutcome(submitted=False, disarmed=False)

    result = execute_armed_stop_market_bracket(
        client=client,
        order_service=order_service,
        account_id=account_id,
        symbol=symbol,
        order=order,
        synced_state=state,
        signal_lifecycle_id=state.signal_lifecycle_id,
        account_balance=account_balance,
        desired_leverage=desired_leverage,
        symbol_spec=symbol_spec,
        buy_spread=buy_spread,
        asset_guard_result=asset_guard_result,
        trigger_price=trade_price,
    )
    return ArmedStopTouchOutcome(
        submitted=result.submitted,
        disarmed=result.disarmed or result.submitted,
        skipped_reason=result.skipped_reason,
        response=result.response,
        pending_order_id=result.pending_order_id,
        order=order,
        signal_lifecycle_id=state.signal_lifecycle_id,
        decision_detail=result.decision_detail,
    )


def try_submit_on_candle_touch(
    *,
    client: ProprClient,
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    state: AgentState,
    candle: Candle,
    account_balance: float,
    desired_leverage: int = 1,
    symbol_spec: SymbolSpec | None = None,
    buy_spread: float = 0.0,
    asset_guard_result: Any | None = None,
) -> ArmedStopTouchOutcome:
    order = state.pending_order
    if order is None or order.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        return ArmedStopTouchOutcome(submitted=False, disarmed=True, skipped_reason="no stop pending")
    if _broker_has_resting_entry(state):
        return ArmedStopTouchOutcome(submitted=False, disarmed=False, skipped_reason="broker resting entry")
    if not is_stop_trigger_touched(order, candle):
        return ArmedStopTouchOutcome(submitted=False, disarmed=False)

    trigger_price = candle.high if order.order_type == OrderType.BUY_STOP else candle.low
    result = execute_armed_stop_market_bracket(
        client=client,
        order_service=order_service,
        account_id=account_id,
        symbol=symbol,
        order=order,
        synced_state=state,
        signal_lifecycle_id=state.signal_lifecycle_id,
        account_balance=account_balance,
        desired_leverage=desired_leverage,
        symbol_spec=symbol_spec,
        buy_spread=buy_spread,
        asset_guard_result=asset_guard_result,
        trigger_price=trigger_price,
    )
    return ArmedStopTouchOutcome(
        submitted=result.submitted,
        disarmed=result.disarmed or result.submitted,
        skipped_reason=result.skipped_reason,
        response=result.response,
        pending_order_id=result.pending_order_id,
        order=order,
        signal_lifecycle_id=state.signal_lifecycle_id,
        decision_detail=result.decision_detail,
    )


def warm_asset_guard(
    *,
    client: ProprClient,
    account_id: str,
    symbol: str,
    desired_leverage: int,
):
    return evaluate_asset_execution_guard(
        client=client,
        account_id=account_id,
        symbol=symbol,
        desired_leverage=desired_leverage,
    )

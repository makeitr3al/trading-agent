"""Submit a market-entry bracket when a locally held stop entry is touched.

Single owner for virtual-stop execution (last_candle poll and ws watcher).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.app_cycle_helpers import (
    _count_open_order_trade_slots,
    _validate_pending_order_execution_size,
)
from broker.asset_guard import AssetGuardResult, evaluate_asset_execution_guard
from broker.execution import open_position_probe_for_symbol
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from models.agent_state import AgentState
from models.order import Order, OrderType
from models.symbol_spec import SymbolSpec
from strategy.trigger_eval import is_stop_gap_exceeded, mark_order_triggered
from utils.propr_response import extract_external_order_id

MAX_OPEN_ORDER_TRADE_SLOTS = 3

_GLOBAL_SUBMIT_LOCK = threading.Lock()


@dataclass(frozen=True)
class ArmedStopSubmitResult:
    submitted: bool
    skipped_reason: str | None = None
    response: dict[str, Any] | None = None
    disarmed: bool = False
    pending_order_id: str | None = None
    decision_detail: str | None = None


def trend_stop_trigger_mode() -> str:
    return (os.getenv("TREND_STOP_TRIGGER_MODE") or "last_candle").strip().lower()


def max_gap_excursion_ratio() -> float | None:
    """Max overshoot past entry as a fraction of |entry−SL|; ``None`` disables the guard."""
    raw = (os.getenv("TREND_STOP_MAX_GAP_R_RATIO") or "0.5").strip()
    if not raw or raw.upper() in {"OFF", "DISABLED", "NONE", "NO"}:
        return None
    try:
        value = float(raw)
    except ValueError:
        return 0.5
    if value < 0:
        return None
    return value


def stable_intent_seed_for_armed_stop(
    *,
    account_id: str,
    symbol: str,
    signal_lifecycle_id: str | None,
    order: Order,
) -> str | None:
    lifecycle = (signal_lifecycle_id or "").strip()
    if not lifecycle:
        return None
    return (
        f"{account_id}|{symbol}|{lifecycle}|{order.order_type}|{order.entry}|"
        f"{order.stop_loss}|{order.take_profit}|{order.position_size}|{order.signal_source}"
    )


def stable_intent_seed_for_entry_order(
    *,
    account_id: str,
    symbol: str,
    executed_at: str | None,
    order: Order,
) -> str | None:
    """Legacy seed used by non-stop pending submits (includes executed_at)."""
    if executed_at is None or not str(executed_at).strip():
        return None
    return (
        f"{account_id}|{symbol}|{str(executed_at).strip()}|{order.order_type}|{order.entry}|"
        f"{order.stop_loss}|{order.take_profit}|{order.position_size}|{order.signal_source}"
    )


def execute_armed_stop_market_bracket(
    *,
    client: ProprClient,
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    order: Order,
    synced_state: AgentState,
    signal_lifecycle_id: str | None,
    account_balance: float,
    desired_leverage: int = 1,
    symbol_spec: SymbolSpec | None = None,
    buy_spread: float = 0.0,
    asset_guard_result: AssetGuardResult | None = None,
    trigger_price: Decimal | float | int | str | None = None,
    skip_position_probe: bool = False,
) -> ArmedStopSubmitResult:
    """Submit market+exits for a touched BUY_STOP/SELL_STOP. Thread-safe across symbols."""
    if order.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        return ArmedStopSubmitResult(submitted=False, skipped_reason="not a stop entry")

    with _GLOBAL_SUBMIT_LOCK:
        if synced_state.pending_order is not None and synced_state.pending_order.order_type not in {
            OrderType.BUY_STOP,
            OrderType.SELL_STOP,
        }:
            return ArmedStopSubmitResult(
                submitted=False,
                skipped_reason="broker already has a pending entry",
            )
        if synced_state.pending_order_id is not None and str(synced_state.pending_order_id).strip():
            return ArmedStopSubmitResult(
                submitted=False,
                skipped_reason="broker already has a pending entry id",
            )

        if trigger_price is not None:
            gap_ratio = max_gap_excursion_ratio()
            if gap_ratio is not None and is_stop_gap_exceeded(order, trigger_price, gap_ratio):
                return ArmedStopSubmitResult(
                    submitted=False,
                    skipped_reason=(
                        f"stop gap exceeded (max_r={gap_ratio}, trigger={trigger_price})"
                    ),
                    disarmed=True,
                    decision_detail="trend_stop_gap_skipped",
                )

        open_order_trade_slots = _count_open_order_trade_slots(synced_state)
        if open_order_trade_slots >= MAX_OPEN_ORDER_TRADE_SLOTS:
            return ArmedStopSubmitResult(
                submitted=False,
                skipped_reason=(
                    f"max open orders/trades reached ({open_order_trade_slots}/{MAX_OPEN_ORDER_TRADE_SLOTS})"
                ),
                disarmed=True,
            )

        if synced_state.has_open_broker_position_for_symbol:
            return ArmedStopSubmitResult(
                submitted=False,
                skipped_reason="open position present at broker for symbol",
                disarmed=True,
            )
        if not skip_position_probe and open_position_probe_for_symbol(order_service, account_id, symbol) > 0:
            return ArmedStopSubmitResult(
                submitted=False,
                skipped_reason="open position present at broker for symbol",
                disarmed=True,
            )

        guard = asset_guard_result
        if guard is None:
            guard = evaluate_asset_execution_guard(
                client=client,
                account_id=account_id,
                symbol=symbol,
                desired_leverage=desired_leverage,
            )
        if not guard.allow_execution:
            return ArmedStopSubmitResult(
                submitted=False,
                skipped_reason=guard.reason,
                disarmed=True,
            )

        effective_leverage = guard.effective_leverage
        size_reason = _validate_pending_order_execution_size(
            order=order,
            account_balance=account_balance,
            desired_leverage=effective_leverage,
            symbol_spec=symbol_spec,
        )
        if size_reason is not None:
            return ArmedStopSubmitResult(
                submitted=False,
                skipped_reason=size_reason,
                disarmed=True,
            )

        stable_seed = stable_intent_seed_for_armed_stop(
            account_id=account_id,
            symbol=symbol,
            signal_lifecycle_id=signal_lifecycle_id,
            order=order,
        )
        submit_order = mark_order_triggered(order)
        response = order_service.submit_market_entry_bracket_with_exits(
            account_id,
            submit_order,
            symbol,
            symbol_spec=symbol_spec,
            stable_intent_seed=stable_seed,
            buy_spread=float(buy_spread),
        )
        external_id = extract_external_order_id(response)
        return ArmedStopSubmitResult(
            submitted=True,
            response=response if isinstance(response, dict) else {"data": response},
            pending_order_id=external_id,
            decision_detail="trend_stop_triggered",
            disarmed=True,
        )

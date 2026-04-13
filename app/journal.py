from __future__ import annotations

import json
from pathlib import Path

from models.agent_state import AgentState
from models.journal import JournalEntry, JournalSignalRecord, JournalUnusedSignalRecord
from models.order import Order, OrderType
from models.runner_result import StrategyRunResult
from models.trade import Trade, TradeDirection

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRADING_JOURNAL_PATH = PROJECT_ROOT / "artifacts" / "trading_journal_beta.jsonl"


def _model_to_dict(model: object) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    raise TypeError(f"Unsupported journal model: {type(model)!r}")


def _entry_date(timestamp: str) -> str:
    return timestamp.split("T", 1)[0] if "T" in timestamp else timestamp


def _direction_from_order(order: Order | None) -> str | None:
    if order is None:
        return None
    if order.order_type in {OrderType.BUY_STOP, OrderType.BUY_LIMIT}:
        return TradeDirection.LONG.value
    return TradeDirection.SHORT.value


def _received_signals(strategy_result: StrategyRunResult | None) -> list[JournalSignalRecord]:
    if strategy_result is None:
        return []

    records: list[JournalSignalRecord] = []
    for signal in [strategy_result.trend_signal, strategy_result.countertrend_signal]:
        if signal is None:
            continue
        records.append(
            JournalSignalRecord(
                signal_type=signal.signal_type.value,
                is_valid=signal.is_valid,
                reason=signal.reason,
            )
        )
    return records


def _used_signals(strategy_result: StrategyRunResult | None) -> list[str]:
    if strategy_result is None or strategy_result.decision.selected_signal_type is None:
        return []
    return [strategy_result.decision.selected_signal_type]


def _unused_signals(strategy_result: StrategyRunResult | None) -> list[JournalUnusedSignalRecord]:
    if strategy_result is None:
        return []

    selected_signal_type = strategy_result.decision.selected_signal_type
    records: list[JournalUnusedSignalRecord] = []
    for signal in [strategy_result.trend_signal, strategy_result.countertrend_signal]:
        if signal is None:
            continue
        if signal.signal_type.value == selected_signal_type:
            continue

        if signal.is_valid:
            reason = f"not selected by decision: {strategy_result.decision.reason}"
        else:
            reason = signal.reason

        records.append(
            JournalUnusedSignalRecord(
                signal_type=signal.signal_type.value,
                reason=reason,
            )
        )
    return records


def _trade_pnl(active_trade: Trade | None, exit_price: float | None) -> float | None:
    if active_trade is None or active_trade.quantity is None or exit_price is None:
        return None
    if active_trade.direction == TradeDirection.LONG:
        return round((exit_price - active_trade.entry) * active_trade.quantity, 8)
    return round((active_trade.entry - exit_price) * active_trade.quantity, 8)


def _resolve_broker_pending_order_id(
    post_cycle_state: AgentState | None,
    synced_state: AgentState | None,
) -> str | None:
    for state in (post_cycle_state, synced_state):
        if state is None:
            continue
        raw = state.pending_order_id
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _derive_order_journal_status(
    *,
    skipped_reason: str | None,
    replaced_order: bool,
    submitted_order: bool,
    broker_pending_order_id: str | None,
    synced_state: AgentState | None,
) -> str:
    if skipped_reason is not None:
        return "not_executed"
    if replaced_order:
        return "replaced"
    if submitted_order:
        return "submitted"
    if broker_pending_order_id is not None or (
        synced_state is not None and synced_state.pending_order is not None
    ):
        return "resting"
    return "prepared"


def _should_emit_broker_sync_fill(
    previous_state: AgentState | None,
    synced_state: AgentState | None,
    strategy_result: StrategyRunResult | None,
) -> bool:
    if strategy_result is None:
        return False
    if strategy_result.filled_trade is not None:
        return False
    if previous_state is None or synced_state is None:
        return False
    had_pending = previous_state.pending_order is not None or (
        previous_state.pending_order_id is not None and bool(str(previous_state.pending_order_id).strip())
    )
    if not had_pending:
        return False
    if previous_state.active_trade is not None:
        return False
    if synced_state.active_trade is None:
        return False
    if synced_state.pending_order is not None:
        return False
    if synced_state.pending_order_id is not None and str(synced_state.pending_order_id).strip():
        return False
    return True


def build_journal_entries(
    symbol: str,
    environment: str | None,
    cycle_timestamp: str,
    strategy_result: StrategyRunResult | None,
    synced_state: AgentState | None,
    post_cycle_state: AgentState | None,
    previous_state: AgentState | None,
    submitted_order: bool,
    replaced_order: bool,
    closed_trade: bool,
    skipped_reason: str | None,
    exit_price: float | None,
    executed_at: str | None = None,
    journal_emit_pending_order: bool = True,
    signal_lifecycle_id: str | None = None,
    managed_exit_orders: bool = False,
    scan_effective_submit_allowed: bool | None = None,
    scan_cycle_phase: str | None = None,
) -> list[JournalEntry]:
    timestamp = cycle_timestamp
    entry_date = _entry_date(timestamp)
    cycle_lifecycle_id = f"{symbol}_{timestamp}"
    synced_active_trade = synced_state.active_trade if synced_state is not None else None
    pending_order = post_cycle_state.pending_order if post_cycle_state is not None else None

    entries = [
        JournalEntry(
            entry_type="cycle",
            entry_date=entry_date,
            entry_timestamp=timestamp,
            executed_at=executed_at,
            symbol=symbol,
            environment=environment,
            decision_action=strategy_result.decision.action.value if strategy_result is not None else None,
            skipped_reason=skipped_reason,
            received_signals=_received_signals(strategy_result),
            used_signals=_used_signals(strategy_result),
            unused_signals=_unused_signals(strategy_result),
            notes=strategy_result.decision.reason if strategy_result is not None else skipped_reason,
            lifecycle_id=cycle_lifecycle_id,
            signal_lifecycle_id=signal_lifecycle_id,
            scan_effective_submit_allowed=scan_effective_submit_allowed,
            scan_cycle_phase=scan_cycle_phase,
        )
    ]

    if pending_order is not None and journal_emit_pending_order:
        broker_pending_order_id = _resolve_broker_pending_order_id(post_cycle_state, synced_state)
        order_status = _derive_order_journal_status(
            skipped_reason=skipped_reason,
            replaced_order=replaced_order,
            submitted_order=submitted_order,
            broker_pending_order_id=broker_pending_order_id,
            synced_state=synced_state,
        )
        order_lifecycle_id = broker_pending_order_id or cycle_lifecycle_id

        order_notes = f"pending order via {pending_order.signal_source}"
        if skipped_reason:
            order_notes = f"{order_notes}; {skipped_reason}"

        entries.append(
            JournalEntry(
                entry_type="order",
                entry_date=entry_date,
                entry_timestamp=timestamp,
                executed_at=executed_at,
                symbol=symbol,
                environment=environment,
                direction=_direction_from_order(pending_order),
                fill_timestamp=None,
                position_size=pending_order.position_size,
                entry_price=float(pending_order.entry) if pending_order.entry is not None else None,
                stop_loss=float(pending_order.stop_loss) if pending_order.stop_loss is not None else None,
                take_profit=float(pending_order.take_profit) if pending_order.take_profit is not None else None,
                close_price=None,
                pnl=None,
                status=order_status,
                source_signal_type=(strategy_result.decision.selected_signal_type if strategy_result is not None else None),
                notes=order_notes,
                lifecycle_id=cycle_lifecycle_id,
                external_order_id=broker_pending_order_id,
                broker_pending_order_id=broker_pending_order_id,
                order_lifecycle_id=order_lifecycle_id,
                signal_lifecycle_id=signal_lifecycle_id,
            )
        )

    if strategy_result is not None and strategy_result.filled_trade is not None:
        ft = strategy_result.filled_trade
        trade_lifecycle = f"{symbol}_{ft.opened_at or timestamp}"
        entries.append(
            JournalEntry(
                entry_type="trade",
                entry_date=entry_date,
                entry_timestamp=timestamp,
                executed_at=executed_at,
                symbol=symbol,
                environment=environment,
                direction=ft.direction.value,
                fill_timestamp=ft.opened_at or timestamp,
                position_size=ft.quantity,
                entry_price=float(ft.entry) if ft.entry is not None else None,
                stop_loss=float(ft.stop_loss) if ft.stop_loss is not None else None,
                take_profit=float(ft.take_profit) if ft.take_profit is not None else None,
                close_price=None,
                pnl=None,
                status="filled",
                source_signal_type=(strategy_result.decision.selected_signal_type if strategy_result is not None else None),
                notes="pending order filled into active trade",
                lifecycle_id=trade_lifecycle,
                external_order_id=ft.position_id,
                order_lifecycle_id=trade_lifecycle,
                signal_lifecycle_id=signal_lifecycle_id,
            )
        )

    if _should_emit_broker_sync_fill(previous_state, synced_state, strategy_result):
        trade = synced_state.active_trade
        assert trade is not None
        trade_lifecycle = f"{symbol}_{trade.opened_at or trade.position_id or timestamp}"
        entries.append(
            JournalEntry(
                entry_type="trade",
                entry_date=entry_date,
                entry_timestamp=timestamp,
                executed_at=executed_at,
                symbol=symbol,
                environment=environment,
                direction=trade.direction.value,
                fill_timestamp=trade.opened_at or timestamp,
                position_size=trade.quantity,
                entry_price=float(trade.entry) if trade.entry is not None else None,
                stop_loss=float(trade.stop_loss) if trade.stop_loss is not None else None,
                take_profit=float(trade.take_profit) if trade.take_profit is not None else None,
                close_price=None,
                pnl=None,
                status="filled",
                source_signal_type=(strategy_result.decision.selected_signal_type if strategy_result is not None else None),
                notes="broker sync: pending entry cleared, active position opened",
                lifecycle_id=trade_lifecycle,
                external_order_id=trade.position_id,
                order_lifecycle_id=trade_lifecycle,
                signal_lifecycle_id=signal_lifecycle_id,
            )
        )

    if (
        managed_exit_orders
        and synced_state is not None
        and synced_state.active_trade is not None
        and post_cycle_state is not None
        and post_cycle_state.active_trade is not None
    ):
        old_t = synced_state.active_trade
        new_t = post_cycle_state.active_trade
        notes = (
            f"exit orders updated: SL {old_t.stop_loss}->{new_t.stop_loss}, "
            f"TP {old_t.take_profit}->{new_t.take_profit}"
        )
        entries.append(
            JournalEntry(
                entry_type="trade_management",
                entry_date=entry_date,
                entry_timestamp=timestamp,
                executed_at=executed_at,
                symbol=symbol,
                environment=environment,
                direction=old_t.direction.value,
                fill_timestamp=None,
                position_size=new_t.quantity,
                entry_price=float(new_t.entry) if new_t.entry is not None else None,
                stop_loss=float(new_t.stop_loss) if new_t.stop_loss is not None else None,
                take_profit=float(new_t.take_profit) if new_t.take_profit is not None else None,
                close_price=None,
                pnl=None,
                status="managed",
                source_signal_type=(
                    strategy_result.decision.selected_signal_type if strategy_result is not None else None
                ),
                notes=notes,
                lifecycle_id=f"{symbol}_{new_t.position_id or timestamp}",
                external_order_id=new_t.position_id,
                signal_lifecycle_id=signal_lifecycle_id,
            )
        )

    if closed_trade and synced_active_trade is not None:
        entries.append(
            JournalEntry(
                entry_type="trade",
                entry_date=entry_date,
                entry_timestamp=timestamp,
                executed_at=executed_at,
                symbol=symbol,
                environment=environment,
                direction=synced_active_trade.direction.value,
                fill_timestamp=synced_active_trade.opened_at,
                close_timestamp=timestamp,
                position_size=synced_active_trade.quantity,
                entry_price=float(synced_active_trade.entry) if synced_active_trade.entry is not None else None,
                stop_loss=float(synced_active_trade.stop_loss) if synced_active_trade.stop_loss is not None else None,
                take_profit=float(synced_active_trade.take_profit) if synced_active_trade.take_profit is not None else None,
                close_price=float(exit_price) if exit_price is not None else None,
                pnl=_trade_pnl(synced_active_trade, exit_price),
                status="closed",
                source_signal_type=(strategy_result.decision.selected_signal_type if strategy_result is not None else None),
                notes="active trade close executed",
                lifecycle_id=f"{symbol}_{synced_active_trade.opened_at or timestamp}",
                external_order_id=synced_active_trade.position_id,
                signal_lifecycle_id=signal_lifecycle_id,
            )
        )

    return entries


def append_journal_entries(path: str | Path, entries: list[JournalEntry]) -> Path:
    journal_path = Path(path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(_model_to_dict(entry), ensure_ascii=True) + "\n")
    return journal_path

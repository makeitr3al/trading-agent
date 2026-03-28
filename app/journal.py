from __future__ import annotations

import json
from pathlib import Path

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


def build_journal_entries(
    symbol: str,
    environment: str | None,
    cycle_timestamp: str,
    strategy_result: StrategyRunResult | None,
    synced_active_trade: Trade | None,
    pending_order: Order | None,
    submitted_order: bool,
    replaced_order: bool,
    closed_trade: bool,
    skipped_reason: str | None,
    exit_price: float | None,
) -> list[JournalEntry]:
    timestamp = cycle_timestamp
    entry_date = _entry_date(timestamp)

    entries = [
        JournalEntry(
            entry_type="cycle",
            entry_date=entry_date,
            entry_timestamp=timestamp,
            symbol=symbol,
            environment=environment,
            decision_action=strategy_result.decision.action.value if strategy_result is not None else None,
            skipped_reason=skipped_reason,
            received_signals=_received_signals(strategy_result),
            used_signals=_used_signals(strategy_result),
            unused_signals=_unused_signals(strategy_result),
            notes=strategy_result.decision.reason if strategy_result is not None else skipped_reason,
        )
    ]

    if pending_order is not None:
        order_status = "prepared"
        if replaced_order:
            order_status = "replaced"
        elif submitted_order:
            order_status = "submitted"
        elif skipped_reason is not None:
            order_status = "not_executed"

        entries.append(
            JournalEntry(
                entry_type="order",
                entry_date=entry_date,
                entry_timestamp=timestamp,
                symbol=symbol,
                environment=environment,
                direction=_direction_from_order(pending_order),
                fill_timestamp=None,
                position_size=pending_order.position_size,
                pnl=None,
                status=order_status,
                source_signal_type=(strategy_result.decision.selected_signal_type if strategy_result is not None else None),
                notes=f"pending order via {pending_order.signal_source}",
            )
        )

    if strategy_result is not None and strategy_result.filled_trade is not None:
        entries.append(
            JournalEntry(
                entry_type="trade",
                entry_date=entry_date,
                entry_timestamp=timestamp,
                symbol=symbol,
                environment=environment,
                direction=strategy_result.filled_trade.direction.value,
                fill_timestamp=strategy_result.filled_trade.opened_at or timestamp,
                position_size=strategy_result.filled_trade.quantity,
                pnl=None,
                status="filled",
                source_signal_type=(strategy_result.decision.selected_signal_type if strategy_result is not None else None),
                notes="pending order filled into active trade",
            )
        )

    if closed_trade and synced_active_trade is not None:
        entries.append(
            JournalEntry(
                entry_type="trade",
                entry_date=entry_date,
                entry_timestamp=timestamp,
                symbol=symbol,
                environment=environment,
                direction=synced_active_trade.direction.value,
                fill_timestamp=synced_active_trade.opened_at,
                close_timestamp=timestamp,
                position_size=synced_active_trade.quantity,
                pnl=_trade_pnl(synced_active_trade, exit_price),
                status="closed",
                source_signal_type=(strategy_result.decision.selected_signal_type if strategy_result is not None else None),
                notes="active trade close executed",
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

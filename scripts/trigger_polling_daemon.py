from __future__ import annotations

import os
import signal
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import sleep
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.trading_app import run_app_cycle
from broker.asset_registry import AssetRegistry
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.symbol_service import HyperliquidSymbolService
from models.agent_state import AgentState
from models.order import OrderType
from scripts.scan_core import (
    ArmedMarketEntry,
    build_data_batch_and_config,
    build_scan_context,
    execute_candidates,
    extract_armed_stop_markets,
    scan_markets_once,
)
from scripts.trigger_polling_store import (
    load_agent_state,
    load_armed_markets,
    parse_armed_markets,
    save_agent_state,
    save_armed_markets,
)
from utils.env_loader import (
    load_data_source_settings_from_env,
    load_multi_market_scan_settings_from_env,
    load_propr_config_from_env,
)
from utils.runtime_status import utc_now_iso, write_runtime_status


_shutdown_requested = False


def _on_signal(_signum: int, _frame: object | None) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def should_run_daily_scan(now_utc: datetime, target_hh_mm: str, last_scan_date: date | None) -> bool:
    target_time = datetime.strptime(target_hh_mm, "%H:%M").time()
    if last_scan_date == now_utc.date():
        return False
    return now_utc.time() >= target_time


def _effective_poll_interval_seconds() -> int:
    raw = (os.getenv("RUNNER_INTERVAL_SECONDS") or "").strip()
    try:
        v = int(raw) if raw else 60
    except ValueError:
        v = 60
    return max(5, v)


def _schedule_time_hhmm() -> str:
    return (os.getenv("OPERATOR_SCHEDULE_TIME") or "07:00").strip()


def _resolve_runtime_status_path() -> str:
    return (os.getenv("RUNNER_STATUS_PATH") or "artifacts/runtime_status_daemon.json").strip()


@dataclass(frozen=True)
class ArmedMarketsSnapshot:
    scan_ts: str | None
    ttl_hours: int
    markets: list[ArmedMarketEntry]


def _next_daily_scan_dt(now_utc: datetime, schedule_time_hhmm: str, last_scan_date: date | None) -> datetime:
    target_time = datetime.strptime(schedule_time_hhmm, "%H:%M").time()
    candidate = datetime.combine(now_utc.date(), target_time, tzinfo=timezone.utc)
    if last_scan_date == now_utc.date() or now_utc >= candidate:
        candidate = datetime.combine(now_utc.date() + timedelta(days=1), target_time, tzinfo=timezone.utc)
    return candidate


def _load_armed_snapshot() -> ArmedMarketsSnapshot:
    payload = load_armed_markets()
    scan_ts, ttl_hours, markets = parse_armed_markets(payload)
    return ArmedMarketsSnapshot(scan_ts=scan_ts, ttl_hours=int(ttl_hours or 24), markets=markets)


def _is_armed_snapshot_fresh(snapshot: ArmedMarketsSnapshot, now_utc: datetime) -> bool:
    scan_dt = _parse_iso_dt(snapshot.scan_ts)
    if scan_dt is None:
        return False
    return now_utc - scan_dt <= timedelta(hours=snapshot.ttl_hours)


def _write_heartbeat(
    *,
    runner_state: str,
    armed_count: int,
    last_scan_at: str | None,
    next_scheduled_scan_at: str | None,
) -> None:
    path = _resolve_runtime_status_path()
    payload = {
        "runner_state": runner_state,
        "armed_markets_count": int(armed_count),
        "last_scan_at": last_scan_at,
        "last_poll_tick_at": utc_now_iso(),
        "next_scheduled_scan_at": next_scheduled_scan_at,
    }
    write_runtime_status(path, payload)


def run_full_scan_cycle(*, now_utc: datetime) -> ArmedMarketsSnapshot:
    propr_config = load_propr_config_from_env()
    data_source_settings = load_data_source_settings_from_env()
    scan_settings = load_multi_market_scan_settings_from_env()

    if data_source_settings.data_source != "live":
        raise ValueError("Trigger polling daemon requires DATA_SOURCE=live")

    client = ProprClient(propr_config)
    order_service = ProprOrderService(client)
    symbol_service = HyperliquidSymbolService()
    registry = AssetRegistry()
    ctx = build_scan_context(
        environment=propr_config.environment,
        data_source_settings=data_source_settings,
        scan_settings=scan_settings,
        propr_client=client,
        order_service=order_service,
        symbol_service=symbol_service,
        registry=registry,
    )

    scan_ts = now_utc.isoformat()
    print(f"Daily scan started at {scan_ts}")
    scan_results = scan_markets_once(ctx, executed_at=scan_ts, scan_cycle_phase="dry_run")

    # Execute only non-stop candidates (stop pendings are skipped inside execute_candidates).
    execute_candidates(ctx, scan_results, executed_at=scan_ts)

    armed = extract_armed_stop_markets(scan_results, scan_ts=scan_ts)
    save_armed_markets(scan_ts=scan_ts, ttl_hours=24, markets=armed)

    # Persist per-symbol state so pending_order survives across poll ticks / restarts.
    for row in scan_results:
        if row.result is None:
            continue
        post_cycle_state = getattr(row.result, "post_cycle_state", None)
        if post_cycle_state is None:
            continue
        try:
            state = AgentState.model_validate(post_cycle_state)
        except Exception:
            continue
        save_agent_state(row.symbol, state)

    print(f"Daily scan finished: armed_markets={len(armed)}")
    return ArmedMarketsSnapshot(scan_ts=scan_ts, ttl_hours=24, markets=armed)


def _should_remove_from_armed(result: Any) -> bool:
    """
    Keep an armed market unless we have a concrete reason to disarm it.

    Important: During fast polling on the same signal bar (1d), strategy evaluation can
    temporarily yield a state without pending_order even though the stop-intent should
    remain armed until bar close / next daily scan. Therefore, pending_order==None is
    *not* a disarm condition by itself.
    """
    post_cycle_state = getattr(result, "post_cycle_state", None)
    if post_cycle_state is None:
        return False

    if getattr(post_cycle_state, "active_trade", None) is not None:
        return True

    if getattr(post_cycle_state, "pending_order_id", None):
        return True

    pending = getattr(post_cycle_state, "pending_order", None)
    if pending is None:
        return False

    if getattr(pending, "order_type", None) not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        return True

    return False


def _merge_preserving_stop_pending(previous: AgentState, updated: AgentState) -> AgentState:
    """
    If a poll tick did not submit but the updated state drops the stop-pending intent,
    keep the previous stop-pending order so the market remains armed until it triggers
    or expires.
    """
    prev_pending = previous.pending_order
    if (
        prev_pending is not None
        and prev_pending.order_type in {OrderType.BUY_STOP, OrderType.SELL_STOP}
        and updated.pending_order is None
        and not updated.pending_order_id
        and updated.active_trade is None
    ):
        updated.pending_order = prev_pending
        if previous.pending_entry_signal_bar_ts and not updated.pending_entry_signal_bar_ts:
            updated.pending_entry_signal_bar_ts = previous.pending_entry_signal_bar_ts
        if previous.last_signal_type and not updated.last_signal_type:
            updated.last_signal_type = previous.last_signal_type
    return updated


def poll_armed_markets(snapshot: ArmedMarketsSnapshot, *, now_utc: datetime) -> ArmedMarketsSnapshot:
    if not snapshot.markets:
        return snapshot

    propr_config = load_propr_config_from_env()
    data_source_settings = load_data_source_settings_from_env()
    scan_settings = load_multi_market_scan_settings_from_env()

    client = ProprClient(propr_config)
    order_service = ProprOrderService(client)
    symbol_service = HyperliquidSymbolService()
    registry = AssetRegistry()
    ctx = build_scan_context(
        environment=propr_config.environment,
        data_source_settings=data_source_settings,
        scan_settings=scan_settings,
        propr_client=client,
        order_service=order_service,
        symbol_service=symbol_service,
        registry=registry,
    )

    scan_dt = _parse_iso_dt(snapshot.scan_ts) or now_utc
    ttl_delta = timedelta(hours=snapshot.ttl_hours)

    kept: list[ArmedMarketEntry] = []
    for entry in snapshot.markets:
        if _shutdown_requested:
            break

        if now_utc - scan_dt > ttl_delta:
            print(f"Armed timeout: symbol={entry.symbol} scan_ts={snapshot.scan_ts}")
            continue

        previous_state = load_agent_state(entry.symbol) or AgentState()
        data_batch, strategy_config, live_buy_spread = build_data_batch_and_config(
            data_source="live",
            golden_scenario=None,
            hyperliquid_base_config=ctx.hyperliquid_base_config,
            coin=entry.coin,
            require_for_execution=True,
        )

        symbol_spec = None
        try:
            symbol_spec = symbol_service.get_symbol_spec(entry.symbol)
        except Exception:
            symbol_spec = None

        result = run_app_cycle(
            client=client,
            order_service=order_service,
            symbol=entry.symbol,
            candles=data_batch.candles,
            config=strategy_config,
            account_balance=data_batch.account_balance or 10000.0,
            previous_state=previous_state,
            require_healthy_core=scan_settings.require_healthy_core,
            allow_execution=True,
            desired_leverage=scan_settings.leverage,
            symbol_spec=symbol_spec,
            data_source="live",
            journal_path=scan_settings.journal_path,
            executed_at=now_utc.isoformat(),
            challenge_id=scan_settings.challenge_id,
            challenge_attempt_id=scan_settings.challenge_attempt_id,
            scan_effective_submit_allowed=True,
            scan_cycle_phase="trigger_poll",
        )

        post_cycle_state = getattr(result, "post_cycle_state", None)
        if post_cycle_state is not None:
            try:
                updated_state = AgentState.model_validate(post_cycle_state)
                merged_state = _merge_preserving_stop_pending(previous_state, updated_state)
                save_agent_state(entry.symbol, merged_state)
            except Exception:
                pass

        if getattr(result, "submitted_order", False):
            print(f"Trigger touched: symbol={entry.symbol} submitted=true")
        else:
            print(f"Market tick: symbol={entry.symbol} submitted=false")

        if _should_remove_from_armed(result):
            continue
        kept.append(entry)

    new_snapshot = ArmedMarketsSnapshot(scan_ts=snapshot.scan_ts, ttl_hours=snapshot.ttl_hours, markets=kept)
    if snapshot.scan_ts:
        save_armed_markets(scan_ts=snapshot.scan_ts, ttl_hours=snapshot.ttl_hours, markets=kept)
    return new_snapshot


def main() -> None:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    poll_interval = _effective_poll_interval_seconds()
    schedule_time = _schedule_time_hhmm()

    now_utc = datetime.now(timezone.utc)
    snapshot = _load_armed_snapshot()
    last_scan_date: date | None = _parse_iso_dt(snapshot.scan_ts).date() if snapshot.scan_ts else None

    if not snapshot.markets or not _is_armed_snapshot_fresh(snapshot, now_utc):
        snapshot = run_full_scan_cycle(now_utc=now_utc)
        last_scan_date = now_utc.date()

    print(f"Trigger polling daemon started. poll_interval={poll_interval}s schedule_time={schedule_time} armed={len(snapshot.markets)}")

    while not _shutdown_requested:
        now_utc = datetime.now(timezone.utc)
        next_scan_dt = _next_daily_scan_dt(now_utc, schedule_time, last_scan_date)
        next_scheduled_scan_at = next_scan_dt.isoformat()
        _write_heartbeat(
            runner_state="daemon_polling",
            armed_count=len(snapshot.markets),
            last_scan_at=snapshot.scan_ts,
            next_scheduled_scan_at=next_scheduled_scan_at,
        )

        if should_run_daily_scan(now_utc, schedule_time, last_scan_date):
            _write_heartbeat(
                runner_state="daemon_scanning",
                armed_count=len(snapshot.markets),
                last_scan_at=snapshot.scan_ts,
                next_scheduled_scan_at=None,
            )
            snapshot = run_full_scan_cycle(now_utc=now_utc)
            last_scan_date = now_utc.date()

        if snapshot.markets:
            print(f"Polling tick: armed={len(snapshot.markets)}")
            snapshot = poll_armed_markets(snapshot, now_utc=now_utc)
            sleep(poll_interval)
            continue

        # No armed markets: go idle until next scheduled scan time.
        seconds_to_scan = max(0.0, (next_scan_dt - now_utc).total_seconds())
        print(f"Polling idle: armed=0; sleeping_until_scan_s={int(seconds_to_scan)}")
        _write_heartbeat(
            runner_state="daemon_idle",
            armed_count=0,
            last_scan_at=snapshot.scan_ts,
            next_scheduled_scan_at=next_scheduled_scan_at,
        )
        # Sleep in chunks so SIGTERM is handled quickly.
        remaining = seconds_to_scan
        while remaining > 0 and not _shutdown_requested:
            chunk = min(300.0, remaining)
            sleep(chunk)
            remaining -= chunk

    _write_heartbeat(
        runner_state="stopped",
        armed_count=len(snapshot.markets),
        last_scan_at=snapshot.scan_ts,
        next_scheduled_scan_at=None,
    )
    print("Trigger polling daemon stopped.")


if __name__ == "__main__":
    main()


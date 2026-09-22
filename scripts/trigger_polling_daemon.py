from __future__ import annotations

import json
import os
import signal
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import subprocess
from queue import Empty, Queue
from time import monotonic, sleep
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.armed_stop_submit import trend_stop_trigger_mode
from app.journal import append_journal_entries
from app.trading_app import run_app_cycle
from broker.asset_registry import AssetRegistry
from broker.challenge_service import get_active_challenge_context
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.symbol_service import HyperliquidSymbolService
from data.providers.hyperliquid_ws import HyperliquidTradeTick, HyperliquidTradesWatcher
from models.agent_state import AgentState
from models.journal import JournalEntry
from models.order import Order
from models.order import OrderType
from scripts.armed_stop_runtime import try_submit_on_candle_touch, try_submit_on_trade_print
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
from utils.bar_time import floor_bar_open_utc
from utils.env_loader import (
    load_data_source_settings_from_env,
    load_hyperliquid_config_from_env,
    load_multi_market_scan_settings_from_env,
    load_propr_config_from_env,
)
from utils.journal_table import build_journal_table
from utils.runtime_status import utc_now_iso, write_runtime_status


_shutdown_requested = False
_last_live_status_sync_m: float = 0.0


def _safe_float(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _resolve_last_candle_prices(candles: list[Any]) -> tuple[str | None, float | None, float | None, float | None, float | None]:
    if not candles:
        return None, None, None, None, None
    last = candles[-1]
    ts = getattr(last, "timestamp", None)
    ts_str = ts.isoformat() if hasattr(ts, "isoformat") else (str(ts) if ts is not None else None)
    return (
        ts_str,
        _safe_float(getattr(last, "open", None)),
        _safe_float(getattr(last, "high", None)),
        _safe_float(getattr(last, "low", None)),
        _safe_float(getattr(last, "close", None)),
    )


def _entry_date(timestamp: str) -> str:
    return timestamp.split("T", 1)[0] if "T" in timestamp else timestamp


def _append_order_protocol_entry(
    *,
    journal_path: str | None,
    symbol: str,
    environment: str | None,
    status: str,
    executed_at: str,
    signal_lifecycle_id: str | None,
    order: Order | None,
    notes: str,
    source_signal_type: str | None = None,
    external_order_id: str | None = None,
) -> None:
    if not journal_path:
        return
    if not signal_lifecycle_id or not str(signal_lifecycle_id).strip():
        # Lifecycle protocol needs a stable signal id; skip rather than polluting journal.
        return

    entry_timestamp = executed_at
    if order is not None and getattr(order, "created_at", None):
        entry_timestamp = str(order.created_at)

    entry = JournalEntry(
        entry_type="order",
        entry_date=_entry_date(entry_timestamp),
        entry_timestamp=entry_timestamp,
        executed_at=executed_at,
        symbol=symbol,
        environment=environment,
        direction=("LONG" if order and order.order_type in {OrderType.BUY_STOP, OrderType.BUY_LIMIT} else "SHORT")
        if order is not None
        else None,
        entry_price=float(order.entry) if order is not None else None,
        stop_loss=float(order.stop_loss) if order is not None else None,
        take_profit=float(order.take_profit) if order is not None else None,
        status=status,
        notes=notes,
        source_signal_type=source_signal_type,
        external_order_id=external_order_id,
        broker_pending_order_id=external_order_id,
        lifecycle_id=f"{symbol}_{entry_timestamp}",
        order_lifecycle_id=external_order_id or f"{symbol}_{entry_timestamp}",
        signal_lifecycle_id=str(signal_lifecycle_id).strip(),
    )
    append_journal_entries(journal_path, [entry])


def _emit_arm_disarm_protocol_entries(
    *,
    journal_path: str | None,
    environment: str | None,
    executed_at: str,
    prev_armed_symbols: set[str],
    new_armed_symbols: set[str],
) -> None:
    removed = prev_armed_symbols - new_armed_symbols
    for symbol in sorted(removed):
        state = load_agent_state(symbol)
        if state is None:
            continue
        pending = state.pending_order
        _append_order_protocol_entry(
            journal_path=journal_path,
            symbol=symbol,
            environment=environment,
            status="disarmed",
            executed_at=executed_at,
            signal_lifecycle_id=state.signal_lifecycle_id,
            order=pending,
            notes="disarmed internal intent (not present in latest scan)",
            source_signal_type=state.last_signal_type,
            external_order_id=state.pending_order_id,
        )


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


def _resolve_operator_env() -> str:
    return (os.getenv("OPERATOR_ENVIRONMENT") or os.getenv("PROPR_ENV") or "unknown").strip().lower()


def _resolve_operator_journal_path() -> str | None:
    raw = (os.getenv("OPERATOR_JOURNAL_PATH") or os.getenv("TRADING_JOURNAL_PATH") or "").strip()
    return raw or None


def _resolve_operator_journal_table_path() -> str | None:
    raw = (os.getenv("OPERATOR_JOURNAL_TABLE_PATH") or "").strip()
    return raw or None


def _resolve_operator_live_status_path() -> str | None:
    raw = (os.getenv("OPERATOR_LIVE_STATUS_PATH") or os.getenv("TRADING_AGENT_LIVE_STATUS_PATH") or "").strip()
    return raw or None


def _refresh_panel_live_status(*, min_interval_s: float = 0.0, force: bool = False) -> None:
    """
    Write live_status.json via REST (same as run.sh) and mirror to HA www for /local/trading-agent/.
    Without this, trigger-polling mode only refreshed journal_table — Open PnL / balances stayed stale.
    """
    global _last_live_status_sync_m
    now_m = monotonic()
    if not force and min_interval_s > 0 and (now_m - _last_live_status_sync_m) < min_interval_s:
        return

    out_raw = _resolve_operator_live_status_path()
    if not out_raw:
        return

    script = _PROJECT_ROOT / "scripts" / "sync_live_status.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--output-path", out_raw],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(
            f"sync_live_status failed (non-fatal) rc={proc.returncode}: {proc.stderr or proc.stdout}",
            file=sys.stderr,
            flush=True,
        )

    _last_live_status_sync_m = monotonic()
    env_name = _resolve_operator_env()
    panel_dir = Path("/config/www/trading-agent")
    try:
        src = Path(out_raw)
        if not src.is_file():
            return
        text = src.read_text(encoding="utf-8")
        panel_dir.mkdir(parents=True, exist_ok=True)
        (panel_dir / "live_status.json").write_text(text, encoding="utf-8")
        if env_name and env_name != "unknown":
            (panel_dir / f"live_status_{env_name}.json").write_text(text, encoding="utf-8")
    except Exception as exc:
        print(f"Live status panel copy failed (non-fatal): {exc}", file=sys.stderr, flush=True)


def _refresh_panel_journal_table(*, journal_path: str) -> None:
    """
    In one-shot mode, run.sh updates journal_table.json at process end.
    In daemon mode, the process does not exit, so we refresh these artifacts here.
    """
    payload = build_journal_table(path=journal_path)
    rendered = json.dumps(payload, ensure_ascii=True)

    # 1) Write to the operator path if present (share path; used by HA sensors/scripts).
    operator_out = _resolve_operator_journal_table_path()
    if operator_out:
        p = Path(operator_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rendered + "\n", encoding="utf-8")

    # 2) Also update panel directory directly (HA serves /local/trading-agent/* from /config/www/trading-agent).
    panel_dir = Path("/config/www/trading-agent")
    try:
        panel_dir.mkdir(parents=True, exist_ok=True)
        (panel_dir / "journal_table.json").write_text(rendered + "\n", encoding="utf-8")
        env_name = _resolve_operator_env()
        if env_name:
            (panel_dir / f"journal_table_{env_name}.json").write_text(rendered + "\n", encoding="utf-8")
    except Exception:
        # Non-fatal: daemon should continue even if HA panel path is not writable in some envs.
        pass


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

    # Read previous armed list before overwrite (for disarm protocol entries).
    prev_payload = load_armed_markets()
    _prev_scan_ts, _prev_ttl, prev_armed = parse_armed_markets(prev_payload)
    prev_armed_symbols = {m.symbol for m in prev_armed if m.symbol}

    scan_results = scan_markets_once(ctx, executed_at=scan_ts, scan_cycle_phase="dry_run")

    # Execute only non-stop candidates (stop pendings are skipped inside execute_candidates).
    execute_candidates(ctx, scan_results, executed_at=scan_ts)

    armed = extract_armed_stop_markets(scan_results, scan_ts=scan_ts)
    save_armed_markets(scan_ts=scan_ts, ttl_hours=24, markets=armed)
    new_armed_symbols = {m.symbol for m in armed if m.symbol}

    # Emit disarm protocol entries for removed symbols (internal "löschen").
    _emit_arm_disarm_protocol_entries(
        journal_path=scan_settings.journal_path,
        environment=propr_config.environment,
        executed_at=scan_ts,
        prev_armed_symbols=prev_armed_symbols,
        new_armed_symbols=new_armed_symbols,
    )

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

    # Emit arm protocol entries for newly armed stop-intents.
    for market in armed:
        state = load_agent_state(market.symbol)
        if state is None or state.pending_order is None:
            continue
        if state.pending_order.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
            continue
        _append_order_protocol_entry(
            journal_path=scan_settings.journal_path,
            symbol=market.symbol,
            environment=propr_config.environment,
            status="armed",
            executed_at=scan_ts,
            signal_lifecycle_id=state.signal_lifecycle_id,
            order=state.pending_order,
            notes="armed internal stop-intent; waiting for touch",
            source_signal_type=market.selected_signal_type,
            external_order_id=state.pending_order_id,
        )

    # Refresh panel artifacts so scan results become visible without daemon exit.
    journal_path = _resolve_operator_journal_path()
    if journal_path:
        try:
            _refresh_panel_journal_table(journal_path=journal_path)
        except Exception as exc:
            print(f"Journal table refresh failed (non-fatal): {exc}")
    _refresh_panel_live_status(force=True)

    print(f"Daily scan finished: armed_markets={len(armed)}")
    return ArmedMarketsSnapshot(scan_ts=scan_ts, ttl_hours=24, markets=armed)


def _should_remove_from_armed(result: Any) -> bool:
    """Disarm when submitted, position open, or strategy dropped the stop intent."""
    post_cycle_state = getattr(result, "post_cycle_state", None)
    if post_cycle_state is None:
        return False

    if getattr(post_cycle_state, "active_trade", None) is not None:
        return True

    if getattr(post_cycle_state, "pending_order_id", None):
        return True

    pending = getattr(post_cycle_state, "pending_order", None)
    if pending is None:
        return True

    if getattr(pending, "order_type", None) not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        return True

    return False


def _merge_preserving_stop_pending(previous: AgentState, updated: AgentState) -> AgentState:
    """No-op identity merge.

    Broker-less virtual stops are preserved inside ``build_agent_state_from_propr_data``.
    Restoring a stop after the strategy cleared ``pending_order`` would override intentional
    cancels (trend invalid / countertrend expiry) — that must not happen.
    """
    del previous  # retained for call-site compatibility
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
    any_submitted = False
    for entry in snapshot.markets:
        if _shutdown_requested:
            break

        if now_utc - scan_dt > ttl_delta:
            print(f"Armed timeout: symbol={entry.symbol} scan_ts={snapshot.scan_ts}")
            continue

        try:
            previous_state = load_agent_state(entry.symbol) or AgentState()
            data_batch, strategy_config, live_buy_spread = build_data_batch_and_config(
                data_source="live",
                golden_scenario=None,
                hyperliquid_base_config=ctx.hyperliquid_base_config,
                coin=entry.coin,
                require_for_execution=True,
            )

            candle_ts, candle_o, candle_h, candle_l, candle_c = _resolve_last_candle_prices(
                getattr(data_batch, "candles", [])
            )
            target_price = _safe_float(getattr(entry, "entry", None))

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
            merged_state: AgentState | None = None
            if post_cycle_state is not None:
                try:
                    updated_state = AgentState.model_validate(post_cycle_state)
                    merged_state = _merge_preserving_stop_pending(previous_state, updated_state)
                    save_agent_state(entry.symbol, merged_state)
                except Exception:
                    pass

            if getattr(result, "submitted_order", False):
                any_submitted = True
                print(
                    "Trigger touched: "
                    f"symbol={entry.symbol} submitted=true "
                    f"target={target_price} actual_close={candle_c} "
                    f"candle_ts={candle_ts} high={candle_h} low={candle_l}"
                )
                # Lifecycle protocol entry for internal trigger -> effective Propr submit.
                if merged_state is None:
                    merged_state = previous_state
                _append_order_protocol_entry(
                    journal_path=scan_settings.journal_path,
                    symbol=entry.symbol,
                    environment=propr_config.environment,
                    status="trigger_submitted",
                    executed_at=now_utc.isoformat(),
                    signal_lifecycle_id=merged_state.signal_lifecycle_id if merged_state is not None else None,
                    order=merged_state.pending_order if merged_state is not None else None,
                    notes=(
                        "trigger touched; submitted bracket to Propr "
                        f"(target={target_price} candle_ts={candle_ts} high={candle_h} low={candle_l} close={candle_c})"
                    ),
                    source_signal_type=getattr(entry, "selected_signal_type", None),
                    external_order_id=(merged_state.pending_order_id if merged_state is not None else None),
                )
            else:
                print(
                    "Market tick: "
                    f"symbol={entry.symbol} submitted=false "
                    f"target={target_price} actual_close={candle_c} "
                    f"candle_ts={candle_ts} high={candle_h} low={candle_l}"
                )

            if _should_remove_from_armed(result):
                continue
            kept.append(entry)
        except Exception as exc:
            # Defensive isolation: a single market's transient HL/Propr failure must not
            # kill the long-running daemon. Keep the market armed and retry next tick.
            print(
                "Armed poll skipped (kept armed for next tick): "
                f"symbol={entry.symbol} coin={entry.coin} "
                f"error_class={exc.__class__.__name__} error={exc}",
                file=sys.stderr,
                flush=True,
            )
            kept.append(entry)
            continue

    new_snapshot = ArmedMarketsSnapshot(scan_ts=snapshot.scan_ts, ttl_hours=snapshot.ttl_hours, markets=kept)
    if snapshot.scan_ts:
        save_armed_markets(scan_ts=snapshot.scan_ts, ttl_hours=snapshot.ttl_hours, markets=kept)

    if any_submitted:
        journal_path = _resolve_operator_journal_path()
        if journal_path:
            try:
                _refresh_panel_journal_table(journal_path=journal_path)
            except Exception as exc:
                print(f"Journal table refresh failed (non-fatal): {exc}")
    # Open PnL / balances: refresh every poll tick (journal alone is insufficient).
    _refresh_panel_live_status(force=True)
    return new_snapshot


def _hyperliquid_interval() -> str:
    try:
        return load_hyperliquid_config_from_env().interval
    except Exception:
        return (os.getenv("HYPERLIQUID_INTERVAL") or "1h").strip() or "1h"


def _apply_touch_outcome_to_state(
    *,
    symbol: str,
    state: AgentState,
    outcome: Any,
    journal_path: str | None,
    environment: str | None,
    executed_at: str,
    selected_signal_type: str | None,
) -> AgentState:
    if outcome.submitted:
        updated = state.model_copy(
            update={
                "pending_order_id": outcome.pending_order_id,
            }
        )
        save_agent_state(symbol, updated)
        _append_order_protocol_entry(
            journal_path=journal_path,
            symbol=symbol,
            environment=environment,
            status="trigger_submitted",
            executed_at=executed_at,
            signal_lifecycle_id=outcome.signal_lifecycle_id or state.signal_lifecycle_id,
            order=outcome.order or state.pending_order,
            notes=f"virtual stop touched; submitted market bracket ({outcome.decision_detail or 'triggered'})",
            source_signal_type=selected_signal_type or state.last_signal_type,
            external_order_id=outcome.pending_order_id,
        )
        return updated
    if outcome.disarmed:
        updated = state.model_copy(update={"pending_order": None, "pending_order_id": None})
        save_agent_state(symbol, updated)
        if outcome.skipped_reason:
            _append_order_protocol_entry(
                journal_path=journal_path,
                symbol=symbol,
                environment=environment,
                status="trigger_skipped",
                executed_at=executed_at,
                signal_lifecycle_id=outcome.signal_lifecycle_id or state.signal_lifecycle_id,
                order=outcome.order or state.pending_order,
                notes=f"virtual stop disarmed: {outcome.skipped_reason}",
                source_signal_type=selected_signal_type or state.last_signal_type,
                external_order_id=None,
            )
        return updated
    return state


def catch_up_then_revalidate_armed_markets(
    snapshot: ArmedMarketsSnapshot,
    *,
    now_utc: datetime,
) -> ArmedMarketsSnapshot:
    """At a strategy bar boundary: catch-up on the frozen entry, then strategy refresh/cancel."""
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

    challenge = get_active_challenge_context(
        client,
        attempt_id=scan_settings.challenge_attempt_id,
        challenge_id=scan_settings.challenge_id,
    )
    account_id = challenge.account_id if challenge is not None else ""
    account_balance = 10000.0
    if challenge is not None and challenge.account_balance is not None:
        account_balance = float(challenge.account_balance.margin_balance)

    kept: list[ArmedMarketEntry] = []
    any_submitted = False
    for entry in snapshot.markets:
        if _shutdown_requested:
            kept.append(entry)
            continue
        try:
            previous_state = load_agent_state(entry.symbol) or AgentState()
            data_batch, strategy_config, live_buy_spread = build_data_batch_and_config(
                data_source="live",
                golden_scenario=None,
                hyperliquid_base_config=ctx.hyperliquid_base_config,
                coin=entry.coin,
                require_for_execution=True,
            )
            candles = list(getattr(data_batch, "candles", []) or [])
            if len(candles) < 2:
                kept.append(entry)
                continue

            # Closed bar for catch-up = previous fully closed candle (candles[-2] when [-1] is forming).
            closed_candle = candles[-2]
            symbol_spec = None
            try:
                symbol_spec = symbol_service.get_symbol_spec(entry.symbol)
            except Exception:
                symbol_spec = None

            if account_id and previous_state.pending_order is not None:
                catch_up = try_submit_on_candle_touch(
                    client=client,
                    order_service=order_service,
                    account_id=account_id,
                    symbol=entry.symbol,
                    state=previous_state,
                    candle=closed_candle,
                    account_balance=account_balance,
                    desired_leverage=scan_settings.leverage,
                    symbol_spec=symbol_spec,
                    buy_spread=float(live_buy_spread or strategy_config.buy_spread),
                )
                previous_state = _apply_touch_outcome_to_state(
                    symbol=entry.symbol,
                    state=previous_state,
                    outcome=catch_up,
                    journal_path=scan_settings.journal_path,
                    environment=propr_config.environment,
                    executed_at=now_utc.isoformat(),
                    selected_signal_type=getattr(entry, "selected_signal_type", None),
                )
                if catch_up.submitted:
                    any_submitted = True
                    continue
                if catch_up.disarmed:
                    continue

            # Strategy refresh / CT expiry — only after catch-up on the frozen level.
            result = run_app_cycle(
                client=client,
                order_service=order_service,
                symbol=entry.symbol,
                candles=candles,
                config=strategy_config,
                account_balance=data_batch.account_balance or account_balance,
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
                scan_cycle_phase="bar_boundary",
            )
            post_cycle_state = getattr(result, "post_cycle_state", None)
            if post_cycle_state is not None:
                try:
                    updated_state = AgentState.model_validate(post_cycle_state)
                    save_agent_state(entry.symbol, updated_state)
                except Exception:
                    updated_state = previous_state
            else:
                updated_state = previous_state

            if getattr(result, "submitted_order", False):
                any_submitted = True
                continue
            if _should_remove_from_armed(result):
                continue
            pending = getattr(updated_state, "pending_order", None)
            if pending is None or pending.order_type not in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
                continue
            kept.append(entry)
        except Exception as exc:
            print(
                "Bar-boundary revalidate skipped (kept armed): "
                f"symbol={entry.symbol} error={exc.__class__.__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            kept.append(entry)

    save_armed_markets(scan_ts=snapshot.scan_ts or now_utc.isoformat(), ttl_hours=snapshot.ttl_hours, markets=kept)
    if any_submitted:
        journal_path = _resolve_operator_journal_path()
        if journal_path:
            try:
                _refresh_panel_journal_table(journal_path=journal_path)
            except Exception as exc:
                print(f"Journal table refresh failed (non-fatal): {exc}")
    _refresh_panel_live_status(force=True)
    return ArmedMarketsSnapshot(scan_ts=snapshot.scan_ts, ttl_hours=snapshot.ttl_hours, markets=kept)


def _process_trade_tick(
    *,
    tick: HyperliquidTradeTick,
    snapshot: ArmedMarketsSnapshot,
    coin_to_entry: dict[str, ArmedMarketEntry],
    client: ProprClient,
    order_service: ProprOrderService,
    account_id: str,
    account_balance: float,
    scan_settings: Any,
    propr_config: Any,
    symbol_service: HyperliquidSymbolService,
    hyperliquid_base_config: Any,
) -> ArmedMarketsSnapshot:
    entry = coin_to_entry.get(tick.coin)
    if entry is None:
        return snapshot
    state = load_agent_state(entry.symbol) or AgentState()
    symbol_spec = None
    try:
        symbol_spec = symbol_service.get_symbol_spec(entry.symbol)
    except Exception:
        symbol_spec = None
    buy_spread = 0.0
    try:
        _batch, strategy_config, live_buy_spread = build_data_batch_and_config(
            data_source="live",
            golden_scenario=None,
            hyperliquid_base_config=hyperliquid_base_config,
            coin=entry.coin,
            require_for_execution=False,
        )
        buy_spread = float(live_buy_spread or strategy_config.buy_spread)
    except Exception:
        buy_spread = 0.0

    outcome = try_submit_on_trade_print(
        client=client,
        order_service=order_service,
        account_id=account_id,
        symbol=entry.symbol,
        state=state,
        trade_price=tick.price,
        account_balance=account_balance,
        desired_leverage=scan_settings.leverage,
        symbol_spec=symbol_spec,
        buy_spread=buy_spread,
    )
    if not outcome.submitted and not outcome.disarmed:
        return snapshot

    _apply_touch_outcome_to_state(
        symbol=entry.symbol,
        state=state,
        outcome=outcome,
        journal_path=scan_settings.journal_path,
        environment=propr_config.environment,
        executed_at=datetime.now(timezone.utc).isoformat(),
        selected_signal_type=getattr(entry, "selected_signal_type", None),
    )
    kept = [m for m in snapshot.markets if m.symbol != entry.symbol]
    save_armed_markets(
        scan_ts=snapshot.scan_ts or datetime.now(timezone.utc).isoformat(),
        ttl_hours=snapshot.ttl_hours,
        markets=kept,
    )
    if outcome.submitted:
        journal_path = _resolve_operator_journal_path()
        if journal_path:
            try:
                _refresh_panel_journal_table(journal_path=journal_path)
            except Exception:
                pass
        print(
            f"WS trigger: symbol={entry.symbol} coin={tick.coin} px={tick.price} submitted=true"
        )
    return ArmedMarketsSnapshot(scan_ts=snapshot.scan_ts, ttl_hours=snapshot.ttl_hours, markets=kept)


def run_ws_watch_loop(
    *,
    snapshot: ArmedMarketsSnapshot,
    last_scan_date: date | None,
    schedule_time: str,
) -> tuple[ArmedMarketsSnapshot, date | None]:
    """Event-driven watch: HL trades + bar-boundary revalidate + daily universe scan."""
    trade_queue: Queue[HyperliquidTradeTick] = Queue()
    watcher = HyperliquidTradesWatcher(
        on_trade=lambda tick: trade_queue.put(tick),
    )
    watcher.set_armed_coins({m.coin for m in snapshot.markets})
    watcher.start()

    interval = _hyperliquid_interval()
    last_bar_open = floor_bar_open_utc(datetime.now(timezone.utc), interval)
    propr_config = load_propr_config_from_env()
    data_source_settings = load_data_source_settings_from_env()
    scan_settings = load_multi_market_scan_settings_from_env()
    client = ProprClient(propr_config)
    order_service = ProprOrderService(client)
    symbol_service = HyperliquidSymbolService()
    hyperliquid_base_config = load_hyperliquid_config_from_env()

    try:
        while not _shutdown_requested:
            now_utc = datetime.now(timezone.utc)
            next_scan_dt = _next_daily_scan_dt(now_utc, schedule_time, last_scan_date)
            _write_heartbeat(
                runner_state="daemon_ws_watching",
                armed_count=len(snapshot.markets),
                last_scan_at=snapshot.scan_ts,
                next_scheduled_scan_at=next_scan_dt.isoformat(),
            )

            if should_run_daily_scan(now_utc, schedule_time, last_scan_date):
                snapshot = run_full_scan_cycle(now_utc=now_utc)
                last_scan_date = now_utc.date()
                watcher.set_armed_coins({m.coin for m in snapshot.markets})
                last_bar_open = floor_bar_open_utc(now_utc, interval)
                continue

            current_bar_open = floor_bar_open_utc(now_utc, interval)
            if current_bar_open > last_bar_open and snapshot.markets:
                print(
                    f"Bar boundary: interval={interval} open={current_bar_open.isoformat()} "
                    f"armed={len(snapshot.markets)}"
                )
                snapshot = catch_up_then_revalidate_armed_markets(snapshot, now_utc=now_utc)
                watcher.set_armed_coins({m.coin for m in snapshot.markets})
                last_bar_open = current_bar_open
                continue

            if not snapshot.markets:
                remaining = max(0.0, (next_scan_dt - now_utc).total_seconds())
                sleep(min(5.0, remaining if remaining > 0 else 5.0))
                _refresh_panel_live_status(min_interval_s=55.0, force=False)
                continue

            if not watcher.is_connected:
                # Fallback: candle OHLC catch-up while WS is down (does not use mid alone).
                snapshot = poll_armed_markets(snapshot, now_utc=now_utc)
                watcher.set_armed_coins({m.coin for m in snapshot.markets})
                sleep(1.0)
                continue

            challenge = get_active_challenge_context(
                client,
                attempt_id=scan_settings.challenge_attempt_id,
                challenge_id=scan_settings.challenge_id,
            )
            if challenge is None:
                sleep(1.0)
                continue
            account_balance = 10000.0
            if challenge.account_balance is not None:
                account_balance = float(challenge.account_balance.margin_balance)

            coin_to_entry = {m.coin: m for m in snapshot.markets}
            try:
                tick = trade_queue.get(timeout=1.0)
            except Empty:
                _refresh_panel_live_status(min_interval_s=55.0, force=False)
                continue

            snapshot = _process_trade_tick(
                tick=tick,
                snapshot=snapshot,
                coin_to_entry=coin_to_entry,
                client=client,
                order_service=order_service,
                account_id=challenge.account_id,
                account_balance=account_balance,
                scan_settings=scan_settings,
                propr_config=propr_config,
                symbol_service=symbol_service,
                hyperliquid_base_config=hyperliquid_base_config,
            )
            watcher.set_armed_coins({m.coin for m in snapshot.markets})
    finally:
        watcher.stop()

    return snapshot, last_scan_date


def main() -> None:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    poll_interval = _effective_poll_interval_seconds()
    schedule_time = _schedule_time_hhmm()
    trigger_mode = trend_stop_trigger_mode()

    now_utc = datetime.now(timezone.utc)
    snapshot = _load_armed_snapshot()
    last_scan_date: date | None = _parse_iso_dt(snapshot.scan_ts).date() if snapshot.scan_ts else None

    if not snapshot.markets or not _is_armed_snapshot_fresh(snapshot, now_utc):
        snapshot = run_full_scan_cycle(now_utc=now_utc)
        last_scan_date = now_utc.date()

    print(
        "Trigger polling daemon started. "
        f"mode={trigger_mode} poll_interval={poll_interval}s schedule_time={schedule_time} "
        f"armed={len(snapshot.markets)}"
    )

    if trigger_mode == "ws":
        snapshot, last_scan_date = run_ws_watch_loop(
            snapshot=snapshot,
            last_scan_date=last_scan_date,
            schedule_time=schedule_time,
        )
        _write_heartbeat(
            runner_state="stopped",
            armed_count=len(snapshot.markets),
            last_scan_at=snapshot.scan_ts,
            next_scheduled_scan_at=None,
        )
        print("Trigger polling daemon stopped.")
        return

    interval = _hyperliquid_interval()
    last_bar_open = floor_bar_open_utc(datetime.now(timezone.utc), interval)

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
            last_bar_open = floor_bar_open_utc(now_utc, interval)

        current_bar_open = floor_bar_open_utc(now_utc, interval)
        if current_bar_open > last_bar_open and snapshot.markets:
            print(
                f"Bar boundary: interval={interval} open={current_bar_open.isoformat()} "
                f"armed={len(snapshot.markets)}"
            )
            snapshot = catch_up_then_revalidate_armed_markets(snapshot, now_utc=now_utc)
            last_bar_open = current_bar_open
            continue

        if snapshot.markets:
            print(f"Polling tick: armed={len(snapshot.markets)}")
            snapshot = poll_armed_markets(snapshot, now_utc=now_utc)
            sleep(poll_interval)
            continue

        seconds_to_scan = max(0.0, (next_scan_dt - now_utc).total_seconds())
        print(f"Polling idle: armed=0; sleeping_until_scan_s={int(seconds_to_scan)}")
        _write_heartbeat(
            runner_state="daemon_idle",
            armed_count=0,
            last_scan_at=snapshot.scan_ts,
            next_scheduled_scan_at=next_scheduled_scan_at,
        )
        remaining = seconds_to_scan
        while remaining > 0 and not _shutdown_requested:
            chunk = min(60.0, remaining)
            sleep(chunk)
            remaining -= chunk
            _refresh_panel_live_status(min_interval_s=55.0, force=False)

    _write_heartbeat(
        runner_state="stopped",
        armed_count=len(snapshot.markets),
        last_scan_at=snapshot.scan_ts,
        next_scheduled_scan_at=None,
    )
    print("Trigger polling daemon stopped.")


if __name__ == "__main__":
    main()


"""Verify bot sizing and SL/TP adjustment against live Propr (beta only).

**Signals:** Real strategy signals are **not** used. The script fabricates a
trend or countertrend ``SignalState`` + ``DecisionResult`` and then runs the
**production sizing + submit path** of the bot:

  ``build_order_from_decision`` → ``_apply_symbol_specific_position_size`` →
  ``_validate_pending_order_execution_size`` → ``submit_agent_order_if_allowed``
  (with ``_stable_intent_seed_for_entry_order``), which submits an **entry + SL + TP**
  bracket batch via Propr ``orderGroupId`` (same path as ``run_app_cycle``).

**Prices (open):** By default, ``entry`` / ``stop_loss`` / ``take_profit`` are
**bot-detector geometry** computed from live Hyperliquid candles and the same
``StrategyConfig`` Bollinger settings (closed-bar view via ``_signal_candles_only``):

- Trend long:   entry = ``bb_upper``, stop = ``bb_middle``, tp = entry + rr·(entry−mid)
- Trend short:  entry = ``bb_lower``, stop = ``bb_middle``, tp = entry − rr·(mid−entry)
- CT long:      entry = ``close``, stop = close−(mid−close), tp = ``bb_middle``
- CT short:     entry = ``close``, stop = close+(close−mid), tp = ``bb_middle``

Pass ``--entry-price``, ``--stop-loss`` and ``--take-profit`` **together** to override.

**Phase ``open``** submits a **bracket batch** (entry + ``stop_market`` + ``take_profit_limit``)
via ``submit_agent_order_if_allowed`` / ``submit_bracket_entry_with_exits`` — the
same production mechanism as the managed runner (Propr ``orderGroupId``).

**Phase ``manage``** - ``sync_agent_state_from_propr``, then real
``update_active_trade`` (``strategy/trade_manager``), then
``manage_active_trade_exit_orders``. Requires ``MANUAL_ALLOW_SUBMIT=YES``.

**Phase ``observe``** - dry-run: only ``update_active_trade`` and print level
diffs (no Propr writes; ``MANUAL_ALLOW_SUBMIT`` not required).

Requires ``PROPR_ENV=beta``, ``.env`` with beta + Hyperliquid settings,
``PROPR_SYMBOL`` (via ``load_manual_test_settings_from_env``), active challenge,
and for any submit: ``MANUAL_ALLOW_SUBMIT=YES``.

Examples::

  .\\.venv\\Scripts\\python.exe scripts/verify_size_and_adjust.py open ^
    --trade-type countertrend --direction short

  .\\.venv\\Scripts\\python.exe scripts/verify_size_and_adjust.py manage --trade-type countertrend --latest-bb-middle 100250 --latest-close 100150

  .\\.venv\\Scripts\\python.exe scripts/verify_size_and_adjust.py observe --trade-type trend
"""

from __future__ import annotations

import argparse
import math
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Literal

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading_app import (
    _apply_symbol_specific_position_size,
    _stable_intent_seed_for_entry_order,
    _validate_pending_order_execution_size,
)
from broker.challenge_service import get_active_challenge_context
from broker.execution import manage_active_trade_exit_orders, should_manage_exit_orders, submit_agent_order_if_allowed
from broker.health_guard import fetch_and_check_core_service_health
from broker.order_service import (
    ProprOrderService,
    build_market_entry_bracket_previews,
    build_order_submission_preview,
    build_sdk_create_order_params,
    extract_order_id_from_submit_response,
)
from broker.propr_client import ProprClient
from broker.propr_client import _to_sdk_order_payload
from broker.state_sync import sync_agent_state_from_propr
from broker.symbol_service import HyperliquidSymbolService
from config.strategy_config import StrategyConfig, build_strategy_config
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from indicators.bollinger import compute_bollinger_bands
from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.signal import SignalState, SignalType
from models.trade import Trade, TradeDirection, TradeType
from strategy.order_manager import build_order_from_decision
from strategy.strategy_runner import _signal_candles_only
from strategy.trade_manager import update_active_trade
from utils.asset_normalizer import normalize_asset
from utils.env_loader import (
    load_hyperliquid_config_from_env,
    load_manual_test_settings_from_env,
    load_propr_config_from_env,
)

TradeKind = Literal["trend", "countertrend"]
DirKind = Literal["long", "short"]


def _pair_symbol(raw: str) -> str:
    trimmed = (raw or "").strip()
    if "/" in trimmed:
        base = trimmed.split("/", 1)[0].strip().upper()
        if not base:
            raise ValueError("Invalid PROPR_SYMBOL pair")
        return f"{base}/USDC"
    info = normalize_asset(trimmed)
    return f"{info.base}/{info.quote}"


def _resolve_live_buy_spread(hyperliquid_config: Any, *, require_for_execution: bool) -> float:
    provider = HyperliquidHistoricalProvider(hyperliquid_config)
    try:
        return provider.fetch_current_spread()
    except Exception as exc:
        if require_for_execution:
            raise ValueError(f"Failed to fetch live spread from Hyperliquid: {exc}") from exc
        print(f"Live spread: unavailable ({exc}); using 0.0")
        return 0.0


def _resolve_account_balance(client: ProprClient | None, override: float | None) -> float:
    if override is not None:
        return float(override)
    if client is None:
        return 10_000.0
    ctx = get_active_challenge_context(client)
    if ctx is not None and ctx.account_balance is not None:
        return float(ctx.account_balance.margin_balance)
    return 10_000.0


def _default_bb_middle_and_close(
    candles: list[Any],
    config: StrategyConfig,
    *,
    trade_type: TradeKind,
) -> tuple[float, float]:
    """Match strategy_runner: trend uses last bar of full series; countertrend uses bollinger_sig last."""
    if not candles:
        raise ValueError("candles required")
    closes_all = pd.Series([float(c.close) for c in candles], dtype=float)
    bollinger_all = compute_bollinger_bands(
        closes=closes_all,
        period=config.bollinger_period,
        std_dev=config.bollinger_std_dev,
    )
    effective_now = datetime.now(timezone.utc)
    signal_candles = _signal_candles_only(candles, now=effective_now)
    if len(signal_candles) < config.bollinger_period:
        signal_candles = candles
    closes_sig = pd.Series([float(c.close) for c in signal_candles], dtype=float)
    bollinger_sig = compute_bollinger_bands(
        closes=closes_sig,
        period=config.bollinger_period,
        std_dev=config.bollinger_std_dev,
    )
    latest_close = float(candles[-1].close)
    if trade_type == "countertrend":
        mid = float(bollinger_sig.iloc[-1]["bb_middle"])
    else:
        mid = float(bollinger_all.iloc[-1]["bb_middle"])
    return mid, latest_close


def _last_closed_bollinger_sig(
    candles: list[Any],
    config: StrategyConfig,
) -> tuple[float, float, float, float]:
    """Return (bb_middle, bb_upper, bb_lower, last_raw_close) for the signal (closed-bar) frame."""
    if not candles:
        raise ValueError("candles required")
    effective_now = datetime.now(timezone.utc)
    signal_candles = _signal_candles_only(candles, now=effective_now)
    if len(signal_candles) < config.bollinger_period:
        signal_candles = candles
    closes_sig = pd.Series([float(c.close) for c in signal_candles], dtype=float)
    bb = compute_bollinger_bands(
        closes=closes_sig,
        period=config.bollinger_period,
        std_dev=config.bollinger_std_dev,
    )
    row = bb.iloc[-1]
    mid = float(row["bb_middle"])
    upper = float(row["bb_upper"])
    lower = float(row["bb_lower"])
    if any(math.isnan(x) for x in (mid, upper, lower)):
        raise ValueError("Bollinger row contains NaN; need more HL history for this symbol/interval")
    last_close = float(candles[-1].close)
    return mid, upper, lower, last_close


def _derive_detector_levels(
    *,
    trade_type: TradeKind,
    direction: DirKind,
    candles: list[Any],
    config: StrategyConfig,
) -> tuple[float, float, float]:
    """Mirror bot detector geometry exactly (no spread on TP — same as detect_*_signal).

    Trend (``strategy/trend_signal_detector.py``):
      - long:  entry=bb_upper, stop_loss=bb_middle, take_profit=entry + rr*(entry-bb_middle)
      - short: entry=bb_lower, stop_loss=bb_middle, take_profit=entry - rr*(bb_middle-entry)

    Counter-trend (``strategy/countertrend_signal_detector.py``):
      - long:  entry=close, stop_loss=close - (bb_middle-close), take_profit=bb_middle
      - short: entry=close, stop_loss=close + (close-bb_middle), take_profit=bb_middle
    """
    mid, upper, lower, close = _last_closed_bollinger_sig(candles, config)
    rr = float(config.trend_tp_rr)

    if trade_type == "trend" and direction == "long":
        entry = upper
        stop_loss = mid
        risk = entry - stop_loss
        if risk <= 0:
            raise ValueError("Trend long needs bb_upper > bb_middle (check Bollinger)")
        take_profit = entry + rr * risk
        return entry, stop_loss, take_profit

    if trade_type == "trend" and direction == "short":
        entry = lower
        stop_loss = mid
        risk = stop_loss - entry
        if risk <= 0:
            raise ValueError("Trend short needs bb_lower < bb_middle (check Bollinger)")
        take_profit = entry - rr * risk
        return entry, stop_loss, take_profit

    if trade_type == "countertrend" and direction == "long":
        entry = close
        stop_loss = entry - (mid - entry)
        take_profit = mid
        if not (stop_loss < entry < take_profit):
            raise ValueError(
                "Counter-trend long requires close < bb_middle (close currently not below middle band)"
            )
        return entry, stop_loss, take_profit

    if trade_type == "countertrend" and direction == "short":
        entry = close
        stop_loss = entry + (entry - mid)
        take_profit = mid
        if not (take_profit < entry < stop_loss):
            raise ValueError(
                "Counter-trend short requires close > bb_middle (close currently not above middle band)"
            )
        return entry, stop_loss, take_profit

    raise ValueError(f"Unsupported trade_type/direction: {trade_type}/{direction}")


def _resolve_open_levels(
    args: argparse.Namespace,
    *,
    candles: list[Any],
    strategy_config: StrategyConfig,
) -> tuple[float, float, float]:
    has_e = args.entry_price is not None
    has_s = args.stop_loss is not None
    has_t = args.take_profit is not None
    if has_e != has_s or has_s != has_t:
        print(
            "Provide all three of --entry-price, --stop-loss, --take-profit together, "
            "or omit all three to use bot-detector geometry from Hyperliquid + Bollinger."
        )
        raise SystemExit(1)
    if not has_e:
        return _derive_detector_levels(
            trade_type=args.trade_type,
            direction=args.direction,
            candles=candles,
            config=strategy_config,
        )
    return float(args.entry_price), float(args.stop_loss), float(args.take_profit)


def _synthetic_signals_and_decision(
    *,
    trade_type: TradeKind,
    direction: DirKind,
    entry: float,
    stop_loss: float,
    take_profit: float,
) -> tuple[SignalState | None, SignalState | None, DecisionResult, float]:
    """Return (trend_signal, counter_signal, decision, current_price for sizing)."""
    if trade_type == "trend" and direction == "long":
        trend = SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=True,
            reason="verify_size_and_adjust synthetic trend long",
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        counter = SignalState(
            signal_type=SignalType.COUNTERTREND_SHORT,
            is_valid=False,
            reason="ignored",
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        decision = DecisionResult(
            action=DecisionAction.PREPARE_TREND_ORDER,
            reason="synthetic",
            selected_signal_type=SignalType.TREND_LONG.value,
        )
        return trend, counter, decision, entry

    if trade_type == "trend" and direction == "short":
        trend = SignalState(
            signal_type=SignalType.TREND_SHORT,
            is_valid=True,
            reason="verify_size_and_adjust synthetic trend short",
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        counter = SignalState(
            signal_type=SignalType.COUNTERTREND_LONG,
            is_valid=False,
            reason="ignored",
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        decision = DecisionResult(
            action=DecisionAction.PREPARE_TREND_ORDER,
            reason="synthetic",
            selected_signal_type=SignalType.TREND_SHORT.value,
        )
        return trend, counter, decision, entry

    if trade_type == "countertrend" and direction == "long":
        # Force BUY_LIMIT path: current_price >= entry
        current_price = entry + max(abs(entry) * 1e-6, 0.01)
        trend = SignalState(
            signal_type=SignalType.TREND_LONG,
            is_valid=False,
            reason="ignored",
            entry=entry * 1.01,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        counter = SignalState(
            signal_type=SignalType.COUNTERTREND_LONG,
            is_valid=True,
            reason="verify_size_and_adjust synthetic countertrend long",
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        decision = DecisionResult(
            action=DecisionAction.PREPARE_COUNTERTREND_ORDER,
            reason="synthetic",
            selected_signal_type=SignalType.COUNTERTREND_LONG.value,
        )
        return trend, counter, decision, current_price

    if trade_type == "countertrend" and direction == "short":
        current_price = entry - max(abs(entry) * 1e-6, 0.01)
        trend = SignalState(
            signal_type=SignalType.TREND_SHORT,
            is_valid=False,
            reason="ignored",
            entry=entry * 0.99,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        counter = SignalState(
            signal_type=SignalType.COUNTERTREND_SHORT,
            is_valid=True,
            reason="verify_size_and_adjust synthetic countertrend short",
            entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        decision = DecisionResult(
            action=DecisionAction.PREPARE_COUNTERTREND_ORDER,
            reason="synthetic",
            selected_signal_type=SignalType.COUNTERTREND_SHORT.value,
        )
        return trend, counter, decision, current_price

    raise ValueError(f"Unsupported trade_type/direction: {trade_type}/{direction}")


def _trade_type_enum(kind: TradeKind) -> TradeType:
    return TradeType.COUNTERTREND if kind == "countertrend" else TradeType.TREND


def _direction_enum(d: DirKind) -> TradeDirection:
    return TradeDirection.LONG if d == "long" else TradeDirection.SHORT


def cmd_open(args: argparse.Namespace) -> int:
    manual = load_manual_test_settings_from_env()
    propr_config = load_propr_config_from_env()
    if propr_config.environment != "beta":
        print("verify_size_and_adjust: only PROPR_ENV=beta is allowed.")
        return 1

    allow_submit = (manual.manual_allow_submit or "").strip().upper() == "YES"
    hl_config = load_hyperliquid_config_from_env()
    pair_symbol = _pair_symbol(manual.symbol)
    symbol_spec = HyperliquidSymbolService().get_symbol_spec(pair_symbol)

    hl_batch = HyperliquidHistoricalProvider(hl_config).fetch_candles()
    candles = hl_batch.candles
    if not candles:
        print("No Hyperliquid candles; cannot size or derive levels.")
        return 1
    strategy_overrides = hl_batch.config.model_dump() if hl_batch.config is not None else {}
    strategy_config = build_strategy_config(**strategy_overrides)
    live_buy_spread = _resolve_live_buy_spread(hl_config, require_for_execution=allow_submit)
    spread_for_sizing = float(args.buy_spread) if args.buy_spread is not None else live_buy_spread
    strategy_config = build_strategy_config(**{**strategy_config.model_dump(), "buy_spread": spread_for_sizing})

    if args.risk_pct is not None:
        strategy_config = build_strategy_config(**{**strategy_config.model_dump(), "risk_per_trade_pct": float(args.risk_pct)})

    entry, stop_loss, take_profit = _resolve_open_levels(
        args,
        candles=candles,
        strategy_config=strategy_config,
    )
    if args.entry_price is None and args.stop_loss is None and args.take_profit is None:
        print(
            "Derived bot-detector levels from Hyperliquid + StrategyConfig Bollinger "
            f"(closed-bar signal frame): entry={entry} stop_loss={stop_loss} take_profit={take_profit}"
        )

    client: ProprClient | None = None
    if allow_submit:
        client = ProprClient(propr_config)
        if manual.require_healthy_core:
            health = fetch_and_check_core_service_health(client)
            if not health.allow_trading:
                print(f"Health guard blocked: {health.reason}")
                return 1

    account_balance = _resolve_account_balance(client, args.account_balance)

    trend, counter, decision, current_price = _synthetic_signals_and_decision(
        trade_type=args.trade_type,
        direction=args.direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
    )

    order = build_order_from_decision(
        decision=decision,
        trend_signal=trend,
        countertrend_signal=counter,
        current_price=current_price,
        account_balance=account_balance,
        risk_per_trade_pct=strategy_config.risk_per_trade_pct,
        buy_spread=strategy_config.buy_spread,
    )
    if order is None:
        print("build_order_from_decision returned None (check levels / signals).")
        return 1

    sized = _apply_symbol_specific_position_size(
        order=order,
        config=strategy_config,
        account_balance=account_balance,
        desired_leverage=manual.leverage,
        symbol_spec=symbol_spec,
    )

    skip = _validate_pending_order_execution_size(
        order=sized,
        account_balance=account_balance,
        desired_leverage=manual.leverage,
        symbol_spec=symbol_spec,
    )

    print("\n=== Phase open: sizing (bot path) ===")
    print(f"pair: {pair_symbol}  entry/stop/tp: {sized.entry} / {sized.stop_loss} / {sized.take_profit}")
    print(f"order_type: {sized.order_type.value}")
    print(f"position_size (after symbol sizing): {sized.position_size}")
    print(f"execution check: {skip or 'ok'}")
    if skip:
        print("Abort: size validation failed.")
        return 1

    preview = build_order_submission_preview(sized, symbol_spec.asset, symbol_spec=symbol_spec)
    print("submission_preview quantity:", preview.get("quantity"))

    if not allow_submit:
        print("\nDry-run only (set MANUAL_ALLOW_SUBMIT=YES in .env to submit).")
        return 0

    assert client is not None
    ctx = get_active_challenge_context(client)
    if ctx is None:
        print("No active challenge; cannot submit.")
        return 1

    state0 = sync_agent_state_from_propr(client, ctx.account_id, symbol=manual.symbol)
    if state0.active_trade is not None:
        print("Abort: an open position already exists for this symbol. Use `manage` or close manually first.")
        return 1

    order_service = ProprOrderService(client)
    executed_at = datetime.now(timezone.utc).isoformat()
    stable_seed = _stable_intent_seed_for_entry_order(
        account_id=ctx.account_id,
        symbol=manual.symbol,
        executed_at=executed_at,
        order=sized,
    )
    group_id, previews = build_market_entry_bracket_previews(
        sized,
        symbol_spec.asset,
        symbol_spec=symbol_spec,
        stable_intent_seed=stable_seed,
        buy_spread=float(strategy_config.buy_spread),
    )
    sdk_orders = [
        _to_sdk_order_payload(build_sdk_create_order_params(p), account_id=ctx.account_id)
        for p in previews
    ]
    response = client.create_orders_batch_raw(ctx.account_id, sdk_orders, order_group_id=group_id)
    print("\n=== create_orders_batch_raw (market entry bracket: entry + SL + TP) ===")
    print("orderGroupId:", group_id)
    print("response:", response)
    if isinstance(response, dict):
        data = response.get("data")
        if isinstance(data, list):
            print("bracket_leg_count:", len(data))
            if data:
                print("entry_order_id:", extract_order_id_from_submit_response({"data": [data[0]]}))
    return 0


def cmd_manage_or_observe(args: argparse.Namespace, *, observe_only: bool) -> int:
    manual = load_manual_test_settings_from_env()
    propr_config = load_propr_config_from_env()
    if propr_config.environment != "beta":
        print("verify_size_and_adjust: only PROPR_ENV=beta is allowed.")
        return 1

    allow_submit = (manual.manual_allow_submit or "").strip().upper() == "YES"
    if not observe_only and not allow_submit:
        print("Phase manage requires MANUAL_ALLOW_SUBMIT=YES (API writes).")
        return 1

    hl_config = load_hyperliquid_config_from_env()
    pair_symbol = _pair_symbol(manual.symbol)
    symbol_spec = HyperliquidSymbolService().get_symbol_spec(pair_symbol)
    hl_batch = HyperliquidHistoricalProvider(hl_config).fetch_candles()
    candles = hl_batch.candles
    strategy_overrides = hl_batch.config.model_dump() if hl_batch.config is not None else {}
    strategy_config = build_strategy_config(**strategy_overrides)
    live_spread = _resolve_live_buy_spread(hl_config, require_for_execution=False)
    buy_spread = float(args.buy_spread) if args.buy_spread is not None else live_spread

    if args.latest_bb_middle is not None and args.latest_close is not None:
        mid, close = float(args.latest_bb_middle), float(args.latest_close)
    else:
        mid, close = _default_bb_middle_and_close(candles, strategy_config, trade_type=args.trade_type)

    client = ProprClient(propr_config)
    if manual.require_healthy_core:
        health = fetch_and_check_core_service_health(client)
        if not health.allow_trading:
            print(f"Health guard blocked: {health.reason}")
            return 1

    ctx = get_active_challenge_context(client)
    if ctx is None:
        print("No active challenge.")
        return 1

    state = sync_agent_state_from_propr(client, ctx.account_id, symbol=manual.symbol)
    if state.active_trade is None:
        print("No open position for this symbol (phase manage needs an active trade).")
        return 1

    active = state.active_trade
    tt = _trade_type_enum(args.trade_type)
    working = active.model_copy(update={"trade_type": tt})

    print("\n=== Before update_active_trade ===")
    print(f"stop_loss={working.stop_loss} take_profit={working.take_profit} break_even={working.break_even_activated}")

    updated = update_active_trade(
        working,
        latest_bb_middle=mid,
        latest_close=close,
        buy_spread=buy_spread,
    )

    print(f"inputs: latest_bb_middle={mid} latest_close={close} buy_spread={buy_spread}")
    print("\n=== After update_active_trade (bot math) ===")
    print(f"stop_loss={updated.stop_loss} take_profit={updated.take_profit} break_even={updated.break_even_activated}")

    if observe_only:
        print("\n(observe: no API writes)")
        return 0

    print("\n=== should_manage_exit_orders ===", should_manage_exit_orders(state, updated))
    if not should_manage_exit_orders(state, updated):
        print("No exit-order replace needed (levels unchanged vs broker state / missing delta).")
        return 0

    order_service = ProprOrderService(client)
    ex = manage_active_trade_exit_orders(
        order_service,
        ctx.account_id,
        symbol_spec.asset,
        state,
        updated,
        buy_spread=buy_spread,
    )
    print("manage_active_trade_exit_orders:", ex)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def _open_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--trade-type", choices=("trend", "countertrend"), required=True)
        p.add_argument("--direction", choices=("long", "short"), required=True)
        p.add_argument("--entry-price", type=float, default=None, help="With --stop-loss and --take-profit: full override; omit all three to derive from HL + Bollinger")
        p.add_argument("--stop-loss", type=float, default=None)
        p.add_argument("--take-profit", type=float, default=None)
        p.add_argument("--risk-pct", type=float, default=None, help="Override StrategyConfig risk_per_trade_pct")
        p.add_argument("--account-balance", type=float, default=None, help="Override sizing balance")
        p.add_argument("--buy-spread", type=float, default=None, help="Override strategy buy_spread for sizing")

    p_open = sub.add_parser("open", help="Size (and optionally open) a position")
    _open_flags(p_open)

    p_manage = sub.add_parser("manage", help="update_active_trade + manage_active_trade_exit_orders")
    p_manage.add_argument("--trade-type", choices=("trend", "countertrend"), required=True)
    p_manage.add_argument("--latest-bb-middle", type=float, default=None)
    p_manage.add_argument("--latest-close", type=float, default=None)
    p_manage.add_argument("--buy-spread", type=float, default=None)

    p_obs = sub.add_parser("observe", help="Dry-run: update_active_trade only")
    p_obs.add_argument("--trade-type", choices=("trend", "countertrend"), required=True)
    p_obs.add_argument("--latest-bb-middle", type=float, default=None)
    p_obs.add_argument("--latest-close", type=float, default=None)
    p_obs.add_argument("--buy-spread", type=float, default=None)

    args = parser.parse_args()
    try:
        if args.command == "open":
            return cmd_open(args)
        if args.command == "manage":
            return cmd_manage_or_observe(args, observe_only=False)
        if args.command == "observe":
            return cmd_manage_or_observe(args, observe_only=True)
    except Exception as exc:
        print(f"verify_size_and_adjust failed: {exc}")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

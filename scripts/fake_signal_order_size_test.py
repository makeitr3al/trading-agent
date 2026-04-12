"""Live-chart order sizing (default) or optional synthetic fixtures.

**Default (live):** loads the same Hyperliquid candles and strategy path as
``scripts/propr_live_app_cycle.py``, runs **one** ``run_app_cycle``, and prints
at most **one** pending entry (the order the bot would place this bar). With
``--submit`` it sends **only that** order (requires ``MANUAL_ALLOW_SUBMIT=YES``).

**Fixtures mode:** ``--fixtures`` prints synthetic trend/countertrend scenarios
for debugging sizing math **without** live candles. Use ``--fixtures-submit``
to submit a single chosen synthetic scenario (still requires
``MANUAL_ALLOW_SUBMIT=YES``).

Requires ``PROPR_ENV=beta`` and ``.env`` with beta + Hyperliquid settings.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading_app import _apply_symbol_specific_position_size, _validate_pending_order_execution_size, run_app_cycle
from broker.challenge_service import get_active_challenge_context
from broker.health_guard import fetch_and_check_core_service_health
from broker.order_service import ProprOrderService, build_order_submission_preview, extract_order_id_from_submit_response
from broker.propr_client import ProprClient
from broker.symbol_service import HyperliquidSymbolService
from config.strategy_config import StrategyConfig, build_strategy_config
from data.providers import get_data_provider
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from models.decision import DecisionAction, DecisionResult
from models.order import Order, OrderType
from models.signal import SignalState, SignalType
from strategy.order_manager import build_order_from_decision
from utils.asset_normalizer import normalize_asset
from utils.env_loader import load_hyperliquid_config_from_env, load_manual_test_settings_from_env, load_propr_config_from_env


Scenario = Literal["trend-long", "trend-short", "countertrend-long", "countertrend-short"]


def _pair_symbol(raw: str) -> str:
    trimmed = (raw or "").strip()
    if "/" in trimmed:
        base = trimmed.split("/", 1)[0].strip().upper()
        if not base:
            raise ValueError("Invalid PROPR_SYMBOL pair")
        return f"{base}/USDC"
    info = normalize_asset(trimmed)
    return f"{info.base}/{info.quote}"


def _resolve_live_buy_spread(hyperliquid_config, require_for_execution: bool) -> float:
    provider = HyperliquidHistoricalProvider(hyperliquid_config)
    try:
        return provider.fetch_current_spread()
    except Exception as exc:
        if require_for_execution:
            raise ValueError(f"Failed to fetch live spread from Hyperliquid: {exc}") from exc
        print(f"Live spread: unavailable ({exc}); using 0.0 for dry-run")
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


def _print_live_pending_order(
    *,
    pending: Order,
    symbol_spec,
    account_balance: float,
    desired_leverage: int,
) -> None:
    """``pending`` is already post-``run_app_cycle`` (includes symbol sizing in live path)."""
    skip_reason = _validate_pending_order_execution_size(
        order=pending,
        account_balance=account_balance,
        desired_leverage=desired_leverage,
        symbol_spec=symbol_spec,
    )
    preview_symbol = symbol_spec.asset
    preview = build_order_submission_preview(pending, preview_symbol, symbol_spec=symbol_spec)

    print("\n=== Live strategy pending order (this bar only) ===")
    print(f"order_type: {pending.order_type.value}")
    print(f"signal_source: {pending.signal_source}")
    print(f"entry / stop / tp: {pending.entry} / {pending.stop_loss} / {pending.take_profit}")
    print(f"position_size (after symbol sizing): {pending.position_size}")
    print(f"leverage / execution check: {skip_reason or 'ok'}")
    print("submission_preview quantity:", preview.get("quantity"))
    print("submission_preview (full):")
    for k, v in sorted(preview.items()):
        print(f"  {k}: {v}")
    if pending.order_type in {OrderType.BUY_STOP, OrderType.SELL_STOP}:
        print(
            "Note: standalone stop entry may be rejected on Propr beta "
            "(see trading_app _beta_blocks_standalone_entry_order)."
        )


def _run_live_path(
    *,
    args: argparse.Namespace,
    manual,
    propr_config,
    pair_symbol: str,
    symbol_spec,
    allow_execution: bool,
) -> int:
    hyperliquid_config = load_hyperliquid_config_from_env()
    data_provider = get_data_provider("live", None, hyperliquid_config=hyperliquid_config)
    data_batch = data_provider.get_data()
    strategy_overrides = data_batch.config.model_dump() if data_batch.config is not None else {}
    strategy_config = build_strategy_config(**strategy_overrides)

    live_buy_spread = _resolve_live_buy_spread(
        hyperliquid_config,
        require_for_execution=allow_execution,
    )
    strategy_config = build_strategy_config(
        **{**strategy_config.model_dump(), "buy_spread": live_buy_spread},
    )

    client = ProprClient(propr_config)
    account_balance = _resolve_account_balance(client, args.account_balance)

    if manual.require_healthy_core:
        health = fetch_and_check_core_service_health(client)
        if not health.allow_trading:
            raise ValueError(f"Health guard: {health.reason}")

    if allow_execution and (manual.manual_allow_submit or "").strip().upper() != "YES":
        raise ValueError("Live submit requires MANUAL_ALLOW_SUBMIT=YES in .env")

    print("Live order size test (single app cycle, single possible submit)")
    print(f"environment: {propr_config.environment}")
    print(f"symbol: {manual.symbol} (Hyperliquid: {hyperliquid_config.coin}, interval={hyperliquid_config.interval})")
    print(f"last_candle_close: {data_batch.candles[-1].close}")
    print(f"account_balance (sizing): {account_balance}")
    print(f"live_buy_spread: {live_buy_spread}")
    print(f"quantity_decimals: {symbol_spec.quantity_decimals}")

    order_service = ProprOrderService(client)
    result = run_app_cycle(
        client=client,
        order_service=order_service,
        symbol=manual.symbol,
        candles=data_batch.candles,
        config=strategy_config,
        account_balance=account_balance,
        require_healthy_core=manual.require_healthy_core,
        allow_execution=allow_execution,
        desired_leverage=manual.leverage,
        symbol_spec=symbol_spec,
        data_source="live",
        journal_path=None,
    )

    sr = result.strategy_result
    if sr is None:
        print("No strategy result.")
        return 1

    print(f"\ndecision_action: {sr.decision.action.value}")
    print(f"decision_reason: {sr.decision.reason}")
    print(f"selected_signal_type: {sr.decision.selected_signal_type}")

    pending = result.post_cycle_state.pending_order if result.post_cycle_state else None
    if pending is None:
        print("\nNo pending entry order this bar (NO_ACTION or blocked path). Nothing to submit.")
        if result.skipped_reason:
            print(f"skipped_reason: {result.skipped_reason}")
        return 0 if not allow_execution else 1

    _print_live_pending_order(
        pending=pending,
        symbol_spec=symbol_spec,
        account_balance=account_balance,
        desired_leverage=manual.leverage,
    )

    if allow_execution:
        if result.submitted_order or result.replaced_order:
            print("\nSubmit/replace executed by run_app_cycle.")
            print("execution_response:", result.execution_response)
        elif result.skipped_reason:
            print(f"\nOrder was not submitted: {result.skipped_reason}")
        else:
            print("\nNo submit this cycle (unexpected if pending order was present).")
    return 0


# --- Optional synthetic fixtures (same as previous script revision) ---


def _fake_trend_long() -> tuple[SignalState, SignalState, DecisionResult]:
    trend = SignalState(
        signal_type=SignalType.TREND_LONG,
        is_valid=True,
        reason="fake trend long for sizing test",
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
    )
    counter = SignalState(
        signal_type=SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="fake countertrend (not selected)",
        entry=105.0,
        stop_loss=115.0,
        take_profit=95.0,
    )
    decision = DecisionResult(
        action=DecisionAction.PREPARE_TREND_ORDER,
        reason="fake: prepare trend",
        selected_signal_type=SignalType.TREND_LONG.value,
    )
    return trend, counter, decision


def _fake_trend_short() -> tuple[SignalState, SignalState, DecisionResult]:
    trend = SignalState(
        signal_type=SignalType.TREND_SHORT,
        is_valid=True,
        reason="fake trend short for sizing test",
        entry=90.0,
        stop_loss=100.0,
        take_profit=70.0,
    )
    counter = SignalState(
        signal_type=SignalType.COUNTERTREND_LONG,
        is_valid=True,
        reason="fake countertrend (not selected)",
        entry=95.0,
        stop_loss=85.0,
        take_profit=110.0,
    )
    decision = DecisionResult(
        action=DecisionAction.PREPARE_TREND_ORDER,
        reason="fake: prepare trend",
        selected_signal_type=SignalType.TREND_SHORT.value,
    )
    return trend, counter, decision


def _fake_countertrend_long() -> tuple[SignalState, SignalState, DecisionResult]:
    trend = SignalState(
        signal_type=SignalType.TREND_LONG,
        is_valid=False,
        reason="fake invalid trend",
        entry=110.0,
        stop_loss=100.0,
        take_profit=130.0,
    )
    counter = SignalState(
        signal_type=SignalType.COUNTERTREND_LONG,
        is_valid=True,
        reason="fake countertrend long for sizing test",
        entry=99_000.0,
        stop_loss=98_500.0,
        take_profit=100_000.0,
    )
    decision = DecisionResult(
        action=DecisionAction.PREPARE_COUNTERTREND_ORDER,
        reason="fake: prepare countertrend",
        selected_signal_type=SignalType.COUNTERTREND_LONG.value,
    )
    return trend, counter, decision


def _fake_countertrend_short() -> tuple[SignalState, SignalState, DecisionResult]:
    trend = SignalState(
        signal_type=SignalType.TREND_SHORT,
        is_valid=False,
        reason="fake invalid trend",
        entry=90.0,
        stop_loss=100.0,
        take_profit=70.0,
    )
    counter = SignalState(
        signal_type=SignalType.COUNTERTREND_SHORT,
        is_valid=True,
        reason="fake countertrend short for sizing test",
        entry=101_000.0,
        stop_loss=101_500.0,
        take_profit=100_000.0,
    )
    decision = DecisionResult(
        action=DecisionAction.PREPARE_COUNTERTREND_ORDER,
        reason="fake: prepare countertrend",
        selected_signal_type=SignalType.COUNTERTREND_SHORT.value,
    )
    return trend, counter, decision


_SCENARIO_BUILDERS: dict[str, object] = {
    "trend-long": _fake_trend_long,
    "trend-short": _fake_trend_short,
    "countertrend-long": _fake_countertrend_long,
    "countertrend-short": _fake_countertrend_short,
}


def _current_price_for_scenario(scenario: Scenario) -> float:
    if scenario == "countertrend-long":
        return 100_000.0
    if scenario == "countertrend-short":
        return 102_000.0
    return 100.0


def _run_one_fixture_scenario(
    *,
    scenario: Scenario,
    pair_symbol: str,
    config: StrategyConfig,
    account_balance: float,
    desired_leverage: int,
    symbol_spec,
) -> None:
    trend, counter, decision = _SCENARIO_BUILDERS[scenario]()
    current_price = _current_price_for_scenario(scenario)
    order = build_order_from_decision(
        decision=decision,
        trend_signal=trend,
        countertrend_signal=counter,
        current_price=current_price,
        account_balance=account_balance,
        risk_per_trade_pct=config.risk_per_trade_pct,
        buy_spread=config.buy_spread,
    )
    print(f"\n=== Fixture ({scenario}) ===")
    if order is None:
        print("No order built.")
        return

    sized = _apply_symbol_specific_position_size(
        order=order,
        config=config,
        account_balance=account_balance,
        desired_leverage=desired_leverage,
        symbol_spec=symbol_spec,
    )
    skip_reason = _validate_pending_order_execution_size(
        order=sized,
        account_balance=account_balance,
        desired_leverage=desired_leverage,
        symbol_spec=symbol_spec,
    )
    preview_symbol = symbol_spec.asset
    preview = build_order_submission_preview(sized, preview_symbol, symbol_spec=symbol_spec)

    print(f"current_price (fixture): {current_price}")
    print(f"order_type: {sized.order_type.value}")
    print(f"entry / stop / tp: {sized.entry} / {sized.stop_loss} / {sized.take_profit}")
    print(f"position_size: {sized.position_size}")
    print(f"execution check: {skip_reason or 'ok'}")
    print("quantity:", preview.get("quantity"))


def _parse_fixture_scenario(raw: str) -> Scenario:
    key = str(raw).strip().lower().replace("_", "-")
    if key not in _SCENARIO_BUILDERS:
        raise ValueError(f"Unknown scenario {raw!r}; choose from {sorted(_SCENARIO_BUILDERS)}")
    return key  # type: ignore[return-value]


def _run_fixtures_path(
    *,
    args: argparse.Namespace,
    manual,
    propr_config,
    pair_symbol: str,
    symbol_spec,
) -> int:
    config = StrategyConfig()
    client: ProprClient | None = None
    account_balance = float(args.account_balance) if args.account_balance is not None else 10_000.0

    if args.fixtures_submit:
        if (manual.manual_allow_submit or "").strip().upper() != "YES":
            raise ValueError("Fixture submit requires MANUAL_ALLOW_SUBMIT=YES in .env")
        client = ProprClient(propr_config)
        if manual.require_healthy_core:
            health = fetch_and_check_core_service_health(client)
            if not health.allow_trading:
                raise ValueError(f"Health guard: {health.reason}")
        ctx = get_active_challenge_context(client)
        if ctx is None:
            raise ValueError("No active challenge; cannot submit")
        if args.account_balance is None and ctx.account_balance is not None:
            account_balance = float(ctx.account_balance.margin_balance)

    print("Fixture order size check (synthetic levels, not live candles)")
    print(f"environment: {propr_config.environment}")
    print(f"symbol: {manual.symbol} -> pair {pair_symbol}")
    print(f"account_balance (sizing): {account_balance}")

    if args.fixtures_submit:
        submit_scenario = _parse_fixture_scenario(args.fixtures_submit)
        assert client is not None
        ctx = get_active_challenge_context(client)
        assert ctx is not None
        _run_one_fixture_scenario(
            scenario=submit_scenario,
            pair_symbol=pair_symbol,
            config=config,
            account_balance=account_balance,
            desired_leverage=manual.leverage,
            symbol_spec=symbol_spec,
        )
        print(f"\n--- FIXTURE SUBMIT: {submit_scenario} ---")
        trend, counter, decision = _SCENARIO_BUILDERS[submit_scenario]()
        current_price = _current_price_for_scenario(submit_scenario)
        order = build_order_from_decision(
            decision=decision,
            trend_signal=trend,
            countertrend_signal=counter,
            current_price=current_price,
            account_balance=account_balance,
            risk_per_trade_pct=config.risk_per_trade_pct,
            buy_spread=config.buy_spread,
        )
        if order is None:
            raise ValueError("Built order is None; cannot submit")
        sized = _apply_symbol_specific_position_size(
            order=order,
            config=config,
            account_balance=account_balance,
            desired_leverage=manual.leverage,
            symbol_spec=symbol_spec,
        )
        skip_reason = _validate_pending_order_execution_size(
            order=sized,
            account_balance=account_balance,
            desired_leverage=manual.leverage,
            symbol_spec=symbol_spec,
        )
        if skip_reason:
            raise ValueError(f"Size validation failed: {skip_reason}")

        preview = build_order_submission_preview(sized, symbol_spec.asset, symbol_spec=symbol_spec)
        order_service = ProprOrderService(client)
        response = order_service.submit_pending_order(
            ctx.account_id,
            sized,
            symbol_spec.asset,
            submission_preview=preview,
            symbol_spec=symbol_spec,
        )
        print("submit_response:", response)
        print("external_order_id:", extract_order_id_from_submit_response(response))
        return 0

    if args.fixtures_only:
        scenarios = [_parse_fixture_scenario(args.fixtures_only)]
    else:
        scenarios = sorted(_SCENARIO_BUILDERS)  # type: ignore[assignment]

    for scenario in scenarios:
        _run_one_fixture_scenario(
            scenario=scenario,
            pair_symbol=pair_symbol,
            config=config,
            account_balance=account_balance,
            desired_leverage=manual.leverage,
            symbol_spec=symbol_spec,
        )

    print("\nDone (fixtures dry-run). Add --fixtures-submit <scenario> to place one synthetic order.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures",
        action="store_true",
        help="Use synthetic signals instead of live candles (for math checks only).",
    )
    parser.add_argument(
        "--fixtures-only",
        metavar="SCENARIO",
        help="With --fixtures, print only one scenario (trend-long, trend-short, countertrend-long, countertrend-short).",
    )
    parser.add_argument(
        "--fixtures-submit",
        metavar="SCENARIO",
        help="With --fixtures, submit exactly one synthetic scenario (requires MANUAL_ALLOW_SUBMIT=YES).",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        help="Live mode: run one cycle with real submit (requires MANUAL_ALLOW_SUBMIT=YES). Still at most one order.",
    )
    parser.add_argument(
        "--account-balance",
        type=float,
        default=None,
        help="Override sizing balance (default: challenge margin_balance or 10000).",
    )
    args = parser.parse_args()

    if args.fixtures_submit and not args.fixtures:
        parser.error("--fixtures-submit requires --fixtures")

    if args.fixtures_only and not args.fixtures:
        parser.error("--fixtures-only requires --fixtures")

    try:
        manual = load_manual_test_settings_from_env()
        propr_config = load_propr_config_from_env()
        if propr_config.environment != "beta":
            raise ValueError("This script is restricted to PROPR_ENV=beta")

        pair_symbol = _pair_symbol(manual.symbol)
        symbol_spec = HyperliquidSymbolService().get_symbol_spec(pair_symbol)

        if args.fixtures:
            return _run_fixtures_path(
                args=args,
                manual=manual,
                propr_config=propr_config,
                pair_symbol=pair_symbol,
                symbol_spec=symbol_spec,
            )

        return _run_live_path(
            args=args,
            manual=manual,
            propr_config=propr_config,
            pair_symbol=pair_symbol,
            symbol_spec=symbol_spec,
            allow_execution=bool(args.submit),
        )
    except Exception as exc:
        print(f"fake_signal_order_size_test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sys
from time import sleep
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading_app import run_app_cycle
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.symbol_service import HyperliquidSymbolService
from config.strategy_config import build_strategy_config
from data.providers import get_data_provider
from data.providers.golden_data_provider import _load_golden_scenario
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from utils.env_loader import (
    load_hyperliquid_config_from_env,
    load_propr_config_from_env,
    load_runner_settings_from_env,
)


# TODO: Later persist last_run metadata across restarts.
# TODO: Later add websocket-based wakeups.
# TODO: Later add multi-symbol handling.


def should_run_now_daily(
    current_utc_datetime: datetime,
    target_hh_mm: str,
    last_run_date: date | None,
) -> bool:
    target_time = datetime.strptime(target_hh_mm, "%H:%M").time()
    if last_run_date == current_utc_datetime.date():
        return False
    return current_utc_datetime.time() >= target_time


def should_run_now_interval(
    last_run_datetime: datetime | None,
    interval_seconds: int,
    current_utc_datetime: datetime,
) -> bool:
    if last_run_datetime is None:
        return True
    elapsed_seconds = (current_utc_datetime - last_run_datetime).total_seconds()
    return elapsed_seconds >= interval_seconds


def _print_result_summary(result: Any) -> None:
    challenge_account_id = None
    decision_action = None
    selected_signal_type = None
    trend_signal_valid = None
    countertrend_signal_valid = None
    pending_order_present = False
    active_trade_present = False
    health_guard_result = getattr(result, "health_guard_result", None)
    risk_guard_result = getattr(result, "risk_guard_result", None)

    if getattr(result, "challenge_context", None) is not None:
        challenge_account_id = result.challenge_context.account_id

    if getattr(result, "strategy_result", None) is not None:
        strategy_result = result.strategy_result
        decision_action = strategy_result.decision.action.value
        selected_signal_type = strategy_result.decision.selected_signal_type
        trend_signal_valid = (
            strategy_result.trend_signal.is_valid if strategy_result.trend_signal is not None else None
        )
        countertrend_signal_valid = (
            strategy_result.countertrend_signal.is_valid
            if strategy_result.countertrend_signal is not None
            else None
        )

    if getattr(result, "post_cycle_state", None) is not None:
        pending_order_present = result.post_cycle_state.pending_order is not None
        active_trade_present = result.post_cycle_state.active_trade is not None

    print("Cycle Summary:")
    print(f"  skipped_reason: {getattr(result, 'skipped_reason', None)}")
    print(f"  challenge_account_id: {challenge_account_id}")
    print(f"  health_guard_result: {health_guard_result.model_dump() if health_guard_result else None}")
    print(f"  risk_guard_result: {risk_guard_result.model_dump() if risk_guard_result else None}")
    print(f"  decision_action: {decision_action}")
    print(f"  selected_signal_type: {selected_signal_type}")
    print(f"  trend_signal_valid: {trend_signal_valid}")
    print(f"  countertrend_signal_valid: {countertrend_signal_valid}")
    print(f"  pending_order_present: {pending_order_present}")
    print(f"  active_trade_present: {active_trade_present}")
    print(f"  submitted_order: {getattr(result, 'submitted_order', False)}")
    print(f"  replaced_order: {getattr(result, 'replaced_order', False)}")
    print(f"  symbol_spec_loaded: {getattr(result, 'symbol_spec_loaded', False)}")
    print(f"  journal_entries: {len(getattr(result, 'journal_entries', []))}")
    print(f"  journal_path: {getattr(result, 'journal_path', None)}")


def _print_golden_expectations(scenario_name: str) -> None:
    scenario = _load_golden_scenario(scenario_name)
    print("Golden Expectations:")
    print(f"  expected_decision_action: {scenario.expected_decision_action}")
    print(f"  expected_order_present: {scenario.expected_order_present}")
    print(f"  expected_trend_signal_valid: {scenario.expected_trend_signal_valid}")
    print(f"  expected_countertrend_signal_valid: {scenario.expected_countertrend_signal_valid}")


def _resolve_live_buy_spread(hyperliquid_config, require_for_execution: bool) -> float:
    provider = HyperliquidHistoricalProvider(hyperliquid_config)
    try:
        return provider.fetch_current_spread()
    except Exception as exc:
        if require_for_execution:
            raise ValueError(f"Failed to fetch live spread from Hyperliquid: {exc}") from exc
        print(f"Live spread: unavailable ({exc}); using 0.0 for dry-run")
        return 0.0


def _run_single_cycle(
    client: ProprClient,
    order_service: ProprOrderService,
    runner_settings,
    data_provider,
    effective_allow_execution: bool,
    symbol_spec,
    live_buy_spread: float,
) -> None:
    current_utc_datetime = datetime.now(timezone.utc)
    print(f"Running app cycle at {current_utc_datetime.isoformat()}")
    data_batch = data_provider.get_data()
    strategy_overrides = data_batch.config.model_dump() if data_batch.config is not None else {}
    strategy_config = build_strategy_config(
        **{
            **strategy_overrides,
            "buy_spread": live_buy_spread,
        }
    )
    print(f"source_name={data_batch.source_name}")
    print(f"live_buy_spread={live_buy_spread}")
    if runner_settings.data_source == "golden" and runner_settings.golden_scenario:
        _print_golden_expectations(runner_settings.golden_scenario)

    result = run_app_cycle(
        client=client,
        order_service=order_service,
        symbol=runner_settings.symbol,
        candles=data_batch.candles,
        config=strategy_config,
        account_balance=10000.0,
        require_healthy_core=runner_settings.require_healthy_core,
        allow_execution=effective_allow_execution,
        desired_leverage=runner_settings.leverage,
        symbol_spec=symbol_spec,
        data_source=runner_settings.data_source,
        journal_path=runner_settings.journal_path,
        challenge_id=runner_settings.challenge_id,
        challenge_attempt_id=getattr(runner_settings, "challenge_attempt_id", None),
    )
    _print_result_summary(result)
    if result.skipped_reason == "missing symbol spec for live execution":
        print("Live submit was blocked because no SymbolSpec could be loaded.")


def main() -> None:
    print("Scheduled runner started.")

    try:
        propr_config = load_propr_config_from_env()
        runner_settings = load_runner_settings_from_env()
        hyperliquid_config = load_hyperliquid_config_from_env() if runner_settings.data_source == "live" else None
        allow_execution = runner_settings.allow_submit == "YES"
        effective_allow_execution = allow_execution and runner_settings.data_source != "golden"
        run_profile = "GOLDEN VALIDATION" if runner_settings.data_source == "golden" else "LIVE DATA"

        print(f"Environment: {propr_config.environment}")
        print(f"Mode: {runner_settings.mode}")
        print(f"Run profile: {run_profile}")
        print(f"Symbol: {runner_settings.symbol}")
        print(f"Configured leverage: x{runner_settings.leverage}")
        print(f"Submit allowed: {allow_execution}")
        print(f"Effective submit allowed after safety checks: {effective_allow_execution}")
        print(f"Require healthy core: {runner_settings.require_healthy_core}")
        print(f"Data source: {runner_settings.data_source}")
        if hyperliquid_config is not None:
            print(f"Hyperliquid coin: {hyperliquid_config.coin}")
            print(f"Hyperliquid interval: {hyperliquid_config.interval}")
            print(f"Hyperliquid lookback_bars: {hyperliquid_config.lookback_bars}")
        if runner_settings.golden_scenario:
            print(f"Golden scenario: {runner_settings.golden_scenario}")
        if runner_settings.data_source == "golden":
            print(f"Running golden scenario: {runner_settings.golden_scenario}")

        if runner_settings.confirm != "YES":
            raise ValueError("Scheduled runner requires RUNNER_CONFIRM=YES")
        if runner_settings.data_source == "golden" and allow_execution:
            raise ValueError("Submit is not allowed with golden data source")

        client = ProprClient(propr_config)
        order_service = ProprOrderService(client)
        data_provider = get_data_provider(
            runner_settings.data_source,
            runner_settings.golden_scenario,
            hyperliquid_config=hyperliquid_config,
        )

        live_buy_spread = 0.0
        if hyperliquid_config is not None:
            live_buy_spread = _resolve_live_buy_spread(
                hyperliquid_config=hyperliquid_config,
                require_for_execution=effective_allow_execution,
            )
            print(f"Live buy spread: {live_buy_spread}")

        symbol_spec = None
        try:
            symbol_spec = HyperliquidSymbolService().get_symbol_spec(runner_settings.symbol)
            print("SymbolSpec loaded: yes")
            print(f"quantity_decimals: {symbol_spec.quantity_decimals}")
            print(f"price_decimals: {symbol_spec.price_decimals}")
            print(f"max_leverage: {symbol_spec.max_leverage}")
        except Exception as exc:
            print("SymbolSpec loaded: no")
            print(f"Symbol spec: unavailable ({exc})")

        if runner_settings.mode == "manual":
            _run_single_cycle(
                client=client,
                order_service=order_service,
                runner_settings=runner_settings,
                data_provider=data_provider,
                effective_allow_execution=effective_allow_execution,
                symbol_spec=symbol_spec,
                live_buy_spread=live_buy_spread,
            )
            print("Scheduled runner finished (manual mode).")
            return

        last_run_datetime: datetime | None = None
        last_run_date: date | None = None
        interval_seconds = runner_settings.interval_seconds or 60
        loop_sleep_seconds = min(interval_seconds, 30)

        while True:
            current_utc_datetime = datetime.now(timezone.utc)
            should_run = False

            if runner_settings.mode == "daily":
                should_run = should_run_now_daily(
                    current_utc_datetime=current_utc_datetime,
                    target_hh_mm=runner_settings.time_utc or "07:00",
                    last_run_date=last_run_date,
                )
            else:
                should_run = should_run_now_interval(
                    last_run_datetime=last_run_datetime,
                    interval_seconds=interval_seconds,
                    current_utc_datetime=current_utc_datetime,
                )

            if should_run:
                _run_single_cycle(
                    client=client,
                    order_service=order_service,
                    runner_settings=runner_settings,
                    data_provider=data_provider,
                    effective_allow_execution=effective_allow_execution,
                    symbol_spec=symbol_spec,
                    live_buy_spread=live_buy_spread,
                )
                last_run_datetime = current_utc_datetime
                last_run_date = current_utc_datetime.date()

            sleep(loop_sleep_seconds)
    except KeyboardInterrupt:
        print("Scheduled runner stopped.")
    except Exception as exc:
        print(f"Scheduled runner failed: {exc}")


if __name__ == "__main__":
    main()


from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading_app import run_app_cycle
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.symbol_service import HyperliquidSymbolService
from config.strategy_config import StrategyConfig
from data.providers import get_data_provider
from data.providers.golden_data_provider import _load_golden_scenario
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from pydantic import BaseModel
from utils.env_loader import (
    load_hyperliquid_config_from_env,
    load_live_app_cycle_settings_from_env,
    load_propr_config_from_env,
)


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def _print_section(title: str, value: Any) -> None:
    print(f"{title}:")
    serialized = _serialize(value)
    if serialized is None:
        print("  None")
        return

    if isinstance(serialized, dict):
        for key, item in serialized.items():
            print(f"  {key}: {item}")
        return

    print(f"  {serialized}")


def _print_cycle_summary(result: Any) -> None:
    strategy_result = getattr(result, "strategy_result", None)
    post_cycle_state = getattr(result, "post_cycle_state", None)

    decision_action = None
    selected_signal_type = None
    trend_signal_valid = None
    countertrend_signal_valid = None
    if strategy_result is not None:
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

    pending_order_present = False
    active_trade_present = False
    if post_cycle_state is not None:
        pending_order_present = post_cycle_state.pending_order is not None
        active_trade_present = post_cycle_state.active_trade is not None

    print("Cycle Summary:")
    print(f"  decision_action: {decision_action}")
    print(f"  selected_signal_type: {selected_signal_type}")
    print(f"  trend_signal_valid: {trend_signal_valid}")
    print(f"  countertrend_signal_valid: {countertrend_signal_valid}")
    print(f"  pending_order_present: {pending_order_present}")
    print(f"  active_trade_present: {active_trade_present}")
    print(f"  submitted_order: {getattr(result, 'submitted_order', False)}")
    print(f"  replaced_order: {getattr(result, 'replaced_order', False)}")


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


def main() -> None:
    print("Live app cycle started.")

    try:
        config = load_propr_config_from_env()
        settings = load_live_app_cycle_settings_from_env()
        hyperliquid_config = load_hyperliquid_config_from_env() if settings.data_source == "live" else None
        allow_execution = settings.allow_submit == "YES"
        effective_allow_execution = allow_execution and settings.data_source != "golden"
        run_mode = "GOLDEN VALIDATION" if settings.data_source == "golden" else "LIVE DATA"

        print(f"Environment: {config.environment}")
        print(f"Base URL: {config.base_url}")
        print(f"Mode: {run_mode}")
        print(f"Data source: {settings.data_source}")
        print(f"Configured leverage: x{settings.leverage}")
        print(f"Submit allowed: {allow_execution}")
        print(f"Effective submit allowed after safety checks: {effective_allow_execution}")
        if hyperliquid_config is not None:
            print(f"Hyperliquid coin: {hyperliquid_config.coin}")
            print(f"Hyperliquid interval: {hyperliquid_config.interval}")
            print(f"Hyperliquid lookback_bars: {hyperliquid_config.lookback_bars}")
        if settings.golden_scenario:
            print(f"Golden scenario: {settings.golden_scenario}")
        if settings.data_source == "golden":
            print(f"Running golden scenario: {settings.golden_scenario}")

        if settings.environment != "beta":
            raise ValueError("Live app cycle is only allowed in beta")
        if settings.confirm != "YES":
            raise ValueError("Live app cycle requires LIVE_APP_CYCLE_CONFIRM=YES")
        if settings.data_source == "golden" and allow_execution:
            raise ValueError("Submit is not allowed with golden data source")

        client = ProprClient(config)
        order_service = ProprOrderService(client)
        data_provider = get_data_provider(
            settings.data_source,
            settings.golden_scenario,
            hyperliquid_config=hyperliquid_config,
        )
        data_batch = data_provider.get_data()
        strategy_config = data_batch.config or StrategyConfig()

        live_buy_spread = 0.0
        if hyperliquid_config is not None:
            live_buy_spread = _resolve_live_buy_spread(
                hyperliquid_config=hyperliquid_config,
                require_for_execution=effective_allow_execution,
            )
            print(f"Live buy spread: {live_buy_spread}")
            strategy_config = strategy_config.copy(update={"buy_spread": live_buy_spread})

        symbol_spec = None
        try:
            symbol_spec = HyperliquidSymbolService().get_symbol_spec(settings.test_symbol)
            print("SymbolSpec loaded: yes")
            print(f"quantity_decimals: {symbol_spec.quantity_decimals}")
            print(f"price_decimals: {symbol_spec.price_decimals}")
            print(f"max_leverage: {symbol_spec.max_leverage}")
        except Exception as exc:
            print("SymbolSpec loaded: no")
            print(f"Symbol spec: unavailable ({exc})")

        print(f"source_name: {data_batch.source_name}")

        result = run_app_cycle(
            client=client,
            order_service=order_service,
            symbol=settings.test_symbol,
            candles=data_batch.candles,
            config=strategy_config,
            account_balance=10000.0,
            require_healthy_core=settings.require_healthy_core,
            allow_execution=effective_allow_execution,
            desired_leverage=settings.leverage,
            symbol_spec=symbol_spec,
            data_source=settings.data_source,
            journal_path=settings.journal_path,
        )

        _print_section("Challenge Context", result.challenge_context)
        _print_section("Health Guard Result", result.health_guard_result)
        _print_section("Risk Guard Result", result.risk_guard_result)
        _print_cycle_summary(result)
        if settings.data_source == "golden" and settings.golden_scenario:
            _print_golden_expectations(settings.golden_scenario)
        _print_section("Synced State", result.synced_state)
        _print_section("Strategy Result", result.strategy_result)
        _print_section("Post-Cycle State", result.post_cycle_state)
        _print_section("Asset Guard Result", result.asset_guard_result)
        print(f"SymbolSpec loaded in app cycle: {result.symbol_spec_loaded}")
        print(f"Execution allowed: {effective_allow_execution}")
        print(f"Journal entries: {len(result.journal_entries)}")
        print(f"Journal path: {result.journal_path}")
        _print_section("Execution response", result.execution_response)
        if result.skipped_reason:
            print(f"Skipped reason: {result.skipped_reason}")
            if result.skipped_reason == "missing symbol spec for live execution":
                print("Live submit was blocked because no SymbolSpec could be loaded.")

        print("Live app cycle finished.")
    except Exception as exc:
        print(f"Live app cycle failed: {exc}")


if __name__ == "__main__":
    main()


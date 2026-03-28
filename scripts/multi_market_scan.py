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
from config.hyperliquid_config import HyperliquidConfig
from config.strategy_config import StrategyConfig
from data.providers import get_data_provider
from data.providers.golden_data_provider import _load_golden_scenario
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from utils.env_loader import (
    load_data_source_settings_from_env,
    load_hyperliquid_config_from_env,
    load_multi_market_scan_settings_from_env,
    load_propr_config_from_env,
)


# TODO: Later add real multi-market prioritization and ranking.
# TODO: Later add persistent scan memory across runs.
# TODO: Later support true multi-market submit once orchestration is ready.


def _guard_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return None


def _print_market_summary(symbol: str, coin: str, result: Any, live_buy_spread: float) -> dict[str, Any]:
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

    print(f"Market: {symbol} ({coin})")
    print(f"  skipped_reason: {getattr(result, 'skipped_reason', None)}")
    print(f"  live_buy_spread: {live_buy_spread}")
    print(f"  health_guard: {_guard_to_dict(getattr(result, 'health_guard_result', None))}")
    print(f"  risk_guard: {_guard_to_dict(getattr(result, 'risk_guard_result', None))}")
    print(f"  decision_action: {decision_action}")
    print(f"  selected_signal_type: {selected_signal_type}")
    print(f"  trend_signal_valid: {trend_signal_valid}")
    print(f"  countertrend_signal_valid: {countertrend_signal_valid}")
    print(f"  pending_order_present: {pending_order_present}")
    print(f"  active_trade_present: {active_trade_present}")

    return {
        "symbol": symbol,
        "coin": coin,
        "decision_action": decision_action,
        "selected_signal_type": selected_signal_type,
        "trend_signal_valid": trend_signal_valid,
        "countertrend_signal_valid": countertrend_signal_valid,
        "pending_order_present": pending_order_present,
        "active_trade_present": active_trade_present,
        "skipped_reason": getattr(result, "skipped_reason", None),
    }


def _build_live_hyperliquid_config(base_config: HyperliquidConfig, coin: str) -> HyperliquidConfig:
    return HyperliquidConfig(
        base_url=base_config.base_url,
        info_path=base_config.info_path,
        coin=coin,
        interval=base_config.interval,
        lookback_bars=base_config.lookback_bars,
    )


def _print_golden_expectations(scenario_name: str) -> None:
    scenario = _load_golden_scenario(scenario_name)
    print("Golden Expectations:")
    print(f"  expected_decision_action: {scenario.expected_decision_action}")
    print(f"  expected_order_present: {scenario.expected_order_present}")
    print(f"  expected_trend_signal_valid: {scenario.expected_trend_signal_valid}")
    print(f"  expected_countertrend_signal_valid: {scenario.expected_countertrend_signal_valid}")


def _resolve_live_buy_spread(hyperliquid_config: HyperliquidConfig) -> float:
    try:
        return HyperliquidHistoricalProvider(hyperliquid_config).fetch_current_spread()
    except Exception as exc:
        print(f"  live spread unavailable ({exc}); using 0.0 for dry-run")
        return 0.0


def main() -> None:
    print("Multi-market scan started.")

    try:
        propr_config = load_propr_config_from_env()
        data_source_settings = load_data_source_settings_from_env()
        scan_settings = load_multi_market_scan_settings_from_env()

        effective_allow_submit = False
        markets = list(zip(scan_settings.symbols, scan_settings.hyperliquid_coins))

        print(f"Environment: {propr_config.environment}")
        print(f"Data source: {data_source_settings.data_source}")
        print(f"Submit allowed (configured): {scan_settings.allow_submit}")
        print(f"Effective submit allowed: {effective_allow_submit}")
        print(f"Number of markets: {len(markets)}")

        if scan_settings.allow_submit:
            print("Multi-market submit is not enabled yet. Running as dry-run only.")

        if data_source_settings.data_source == "golden":
            print("Golden data source active. Configured symbols/coins are used as scan labels only.")
            print(f"Golden scenario: {data_source_settings.golden_scenario}")
            _print_golden_expectations(data_source_settings.golden_scenario or "")

        if data_source_settings.data_source not in {"live", "golden"}:
            raise ValueError("Invalid DATA_SOURCE")
        if not markets:
            raise ValueError("No markets configured for multi-market scan")

        client = ProprClient(propr_config)
        order_service = ProprOrderService(client)
        hyperliquid_base_config = (
            load_hyperliquid_config_from_env() if data_source_settings.data_source == "live" else None
        )

        scan_results: list[dict[str, Any]] = []
        for symbol, coin in markets:
            print(f"Scanning symbol={symbol} coin={coin}")

            live_buy_spread = 0.0
            if data_source_settings.data_source == "live":
                hyperliquid_config = _build_live_hyperliquid_config(hyperliquid_base_config, coin)
                data_provider = get_data_provider(
                    "live",
                    hyperliquid_config=hyperliquid_config,
                )
                live_buy_spread = _resolve_live_buy_spread(hyperliquid_config)
            else:
                data_provider = get_data_provider(
                    "golden",
                    data_source_settings.golden_scenario,
                )

            data_batch = data_provider.get_data()
            strategy_config = (data_batch.config or StrategyConfig()).copy(update={"buy_spread": live_buy_spread})
            print(f"  source_name: {data_batch.source_name}")
            print(f"  live_buy_spread: {live_buy_spread}")

            result = run_app_cycle(
                client=client,
                order_service=order_service,
                symbol=symbol,
                candles=data_batch.candles,
                config=strategy_config,
                account_balance=data_batch.account_balance or 10000.0,
                previous_state=data_batch.agent_state,
                require_healthy_core=scan_settings.require_healthy_core,
                allow_execution=False,
                desired_leverage=scan_settings.leverage,
                symbol_spec=None,
                data_source=data_source_settings.data_source,
            )
            scan_results.append(_print_market_summary(symbol, coin, result, live_buy_spread))

        markets_with_valid_trend = [item for item in scan_results if item["trend_signal_valid"]]
        markets_with_valid_countertrend = [item for item in scan_results if item["countertrend_signal_valid"]]
        markets_with_pending_order_candidate = [item for item in scan_results if item["pending_order_present"]]
        interesting_markets = [
            item for item in scan_results if item["decision_action"] and item["decision_action"] != "NO_ACTION"
        ]

        print("Scan Summary:")
        print(f"  total_markets_scanned: {len(scan_results)}")
        print(f"  markets_with_valid_trend_signal: {len(markets_with_valid_trend)}")
        print(f"  markets_with_valid_countertrend_signal: {len(markets_with_valid_countertrend)}")
        print(f"  markets_with_pending_order_candidate: {len(markets_with_pending_order_candidate)}")
        print("  interesting_markets:")
        if not interesting_markets:
            print("    none")
        else:
            for item in interesting_markets:
                print(
                    f"    {item['symbol']} ({item['coin']}): decision_action={item['decision_action']}, "
                    f"selected_signal_type={item['selected_signal_type']}"
                )
    except Exception as exc:
        print(f"Multi-market scan failed: {exc}")


if __name__ == "__main__":
    main()

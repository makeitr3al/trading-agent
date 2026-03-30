from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading_app import MAX_OPEN_ORDER_TRADE_SLOTS, run_app_cycle
from broker.challenge_service import get_active_challenge_context
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.state_sync import sync_agent_state_from_propr
from broker.symbol_service import HyperliquidSymbolService
from config.hyperliquid_config import HyperliquidConfig
from config.strategy_config import StrategyConfig, build_strategy_config
from data.providers import get_data_provider
from data.providers.base import DataBatch
from data.providers.golden_data_provider import _load_golden_scenario
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from utils.env_loader import (
    load_data_source_settings_from_env,
    load_hyperliquid_config_from_env,
    load_multi_market_scan_settings_from_env,
    load_propr_config_from_env,
)
from utils.live_status import write_live_status_from_state


# TODO: Later add persistent scan memory across runs.
# TODO: Later add account-aware per-market cooldown rules.


def _guard_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return None


def _best_signal_strength(result: Any) -> float:
    strategy_result = getattr(result, "strategy_result", None)
    if strategy_result is None:
        return float("-inf")

    strengths: list[float] = []
    for signal in [strategy_result.trend_signal, strategy_result.countertrend_signal]:
        if signal is None or not signal.is_valid:
            continue
        strengths.append(float(signal.signal_strength or 0.0))

    if not strengths:
        return float("-inf")
    return max(strengths)


def _select_execution_candidates(scan_results: list[dict[str, Any]], available_slots: int) -> list[dict[str, Any]]:
    if available_slots <= 0:
        return []

    candidates = [
        item
        for item in scan_results
        if item.get("pending_order_present") and not item.get("skipped_reason")
    ]
    if len(candidates) <= available_slots:
        return candidates

    return sorted(
        candidates,
        key=lambda item: item.get("best_signal_strength", float("-inf")),
        reverse=True,
    )[:available_slots]


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

    best_signal_strength = _best_signal_strength(result)

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
    print(f"  best_signal_strength: {best_signal_strength}")
    print(f"  journal_entries: {len(getattr(result, 'journal_entries', []))}")
    print(f"  journal_path: {getattr(result, 'journal_path', None)}")

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
        "best_signal_strength": best_signal_strength,
        "result": result,
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


def _resolve_live_buy_spread(hyperliquid_config: HyperliquidConfig, require_for_execution: bool) -> float:
    try:
        return HyperliquidHistoricalProvider(hyperliquid_config).fetch_current_spread()
    except Exception as exc:
        if require_for_execution:
            raise ValueError(f"Failed to fetch live spread from Hyperliquid: {exc}") from exc
        print(f"  live spread unavailable ({exc}); using 0.0 for dry-run")
        return 0.0


def _load_symbol_spec(symbol_service: HyperliquidSymbolService, symbol: str):
    try:
        return symbol_service.get_symbol_spec(symbol)
    except Exception as exc:
        print(f"  symbol spec unavailable for {symbol}: {exc}")
        return None


def _build_data_batch_and_config(
    data_source: str,
    golden_scenario: str | None,
    hyperliquid_base_config: HyperliquidConfig | None,
    coin: str,
    require_for_execution: bool,
) -> tuple[DataBatch, StrategyConfig, float]:
    live_buy_spread = 0.0
    if data_source == "live":
        hyperliquid_config = _build_live_hyperliquid_config(hyperliquid_base_config, coin)
        data_provider = get_data_provider(
            "live",
            hyperliquid_config=hyperliquid_config,
        )
        live_buy_spread = _resolve_live_buy_spread(hyperliquid_config, require_for_execution=require_for_execution)
    else:
        data_provider = get_data_provider(
            "golden",
            golden_scenario,
        )

    data_batch = data_provider.get_data()
    strategy_overrides = data_batch.config.model_dump() if data_batch.config is not None else {}
    strategy_config = build_strategy_config(
        **{
            **strategy_overrides,
            "buy_spread": live_buy_spread,
        }
    )
    return data_batch, strategy_config, live_buy_spread


def _persist_live_status(
    client: ProprClient,
    environment: str,
    symbol: str | None,
    *,
    last_error: str | None = None,
) -> None:
    try:
        challenge_context = get_active_challenge_context(client)
        if challenge_context is None:
            write_live_status_from_state(
                environment=environment,
                state=None,
                source="poll",
                last_error=last_error or "no active challenge",
            )
            return

        state = sync_agent_state_from_propr(
            client,
            challenge_context.account_id,
            symbol=symbol,
        )
        write_live_status_from_state(
            environment=environment,
            state=state,
            source="poll",
            last_error=last_error,
        )
    except Exception as exc:
        write_live_status_from_state(
            environment=environment,
            state=None,
            source="poll",
            last_error=last_error or str(exc),
        )


def main() -> None:
    print("Multi-market scan started.")
    environment = "unknown"
    primary_symbol: str | None = None
    client: ProprClient | None = None

    try:
        propr_config = load_propr_config_from_env()
        environment = propr_config.environment
        data_source_settings = load_data_source_settings_from_env()
        scan_settings = load_multi_market_scan_settings_from_env()
        primary_symbol = scan_settings.symbols[0] if scan_settings.symbols else None

        effective_allow_submit = scan_settings.allow_submit and data_source_settings.data_source == "live"
        markets = list(zip(scan_settings.symbols, scan_settings.hyperliquid_coins))

        print(f"Environment: {propr_config.environment}")
        print(f"Data source: {data_source_settings.data_source}")
        print(f"Submit allowed (configured): {scan_settings.allow_submit}")
        print(f"Effective submit allowed: {effective_allow_submit}")
        print(f"Number of markets: {len(markets)}")

        if scan_settings.allow_submit and data_source_settings.data_source != "live":
            print("Multi-market submit is only enabled for live data. Running as dry-run.")

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
        symbol_service = HyperliquidSymbolService()
        hyperliquid_base_config = (
            load_hyperliquid_config_from_env() if data_source_settings.data_source == "live" else None
        )

        scan_results: list[dict[str, Any]] = []
        market_contexts: list[dict[str, Any]] = []
        for symbol, coin in markets:
            print(f"Scanning symbol={symbol} coin={coin}")
            data_batch, strategy_config, live_buy_spread = _build_data_batch_and_config(
                data_source=data_source_settings.data_source,
                golden_scenario=data_source_settings.golden_scenario,
                hyperliquid_base_config=hyperliquid_base_config,
                coin=coin,
                require_for_execution=False,
            )
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
                journal_path=scan_settings.journal_path,
            )
            scan_results.append(_print_market_summary(symbol, coin, result, live_buy_spread))
            market_contexts.append(
                {
                    "symbol": symbol,
                    "coin": coin,
                    "data_batch": data_batch,
                    "strategy_config": strategy_config,
                    "live_buy_spread": live_buy_spread,
                }
            )

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
                    f"selected_signal_type={item['selected_signal_type']}, best_signal_strength={item['best_signal_strength']}"
                )

        if not effective_allow_submit:
            if client is not None:
                _persist_live_status(client, environment, primary_symbol)
            return

        reference_result = scan_results[0]["result"] if scan_results else None
        synced_state = getattr(reference_result, "synced_state", None)
        currently_open_slots = 0
        if synced_state is not None:
            currently_open_slots = int(getattr(synced_state, "account_open_entry_orders_count", 0) or 0) + int(
                getattr(synced_state, "account_open_positions_count", 0) or 0
            )
        available_slots = max(0, MAX_OPEN_ORDER_TRADE_SLOTS - currently_open_slots)
        print(f"Execution slots available: {available_slots}")
        if available_slots <= 0:
            print("No execution slots available. Skipping submits.")
            _persist_live_status(client, environment, primary_symbol)
            return

        selected_candidates = _select_execution_candidates(scan_results, available_slots)
        if not selected_candidates:
            print("No executable signal candidates found.")
            _persist_live_status(client, environment, primary_symbol)
            return

        print("Executing markets:")
        for candidate in selected_candidates:
            print(
                f"  {candidate['symbol']} ({candidate['coin']}): selected_signal_type={candidate['selected_signal_type']}, "
                f"best_signal_strength={candidate['best_signal_strength']}"
            )

        context_by_symbol = {item["symbol"]: item for item in market_contexts}
        for candidate in selected_candidates:
            market_context = context_by_symbol[candidate["symbol"]]
            symbol = market_context["symbol"]
            symbol_spec = _load_symbol_spec(symbol_service, symbol)
            execution_result = run_app_cycle(
                client=client,
                order_service=order_service,
                symbol=symbol,
                candles=market_context["data_batch"].candles,
                config=market_context["strategy_config"],
                account_balance=market_context["data_batch"].account_balance or 10000.0,
                previous_state=market_context["data_batch"].agent_state,
                require_healthy_core=scan_settings.require_healthy_core,
                allow_execution=True,
                desired_leverage=scan_settings.leverage,
                symbol_spec=symbol_spec,
                data_source=data_source_settings.data_source,
                journal_path=scan_settings.journal_path,
            )
            print(
                f"Executed {symbol}: submitted={execution_result.submitted_order}, replaced={execution_result.replaced_order}, "
                f"skipped_reason={execution_result.skipped_reason}"
            )

        _persist_live_status(client, environment, primary_symbol)
    except Exception as exc:
        print(f"Multi-market scan failed: {exc}")
        if client is not None:
            try:
                _persist_live_status(client, environment, primary_symbol, last_error=str(exc))
            except Exception:
                pass


if __name__ == "__main__":
    main()

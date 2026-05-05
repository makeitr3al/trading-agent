from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading_app import run_app_cycle
from broker.asset_registry import AssetRegistry
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from broker.symbol_service import HyperliquidSymbolService
from scripts.scan_core import (
    best_signal_strength as _best_signal_strength,
    build_data_batch_and_config as _scan_core_build_data_batch_and_config,
    build_scan_context,
    execute_candidates,
    maybe_upgrade_to_hip3_market as _maybe_upgrade_to_hip3_market,
    persist_live_status as _persist_live_status,
    print_golden_expectations as _print_golden_expectations,
    scan_markets_once,
    select_execution_candidates as _select_execution_candidates,
)
from utils.env_loader import (
    load_data_source_settings_from_env,
    load_hyperliquid_config_from_env,
    load_multi_market_scan_settings_from_env,
    load_propr_config_from_env,
)


# TODO: Later add persistent scan memory across runs.
# TODO: Later add account-aware per-market cooldown rules.


# Backwards-compatible monkeypatch targets for tests.
def _build_data_batch_and_config(*args: Any, **kwargs: Any):
    return _scan_core_build_data_batch_and_config(*args, **kwargs)


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
        primary_symbol = scan_settings.assets[0] if scan_settings.assets else None

        print(f"Environment: {propr_config.environment}")
        print(f"Data source: {data_source_settings.data_source}")
        print(f"Submit allowed (configured): {scan_settings.allow_submit}")
        effective_allow_submit = scan_settings.allow_submit and data_source_settings.data_source == "live"
        print(f"Effective submit allowed: {effective_allow_submit}")
        print(f"Number of markets: {len(scan_settings.assets)}")

        if scan_settings.allow_submit and data_source_settings.data_source != "live":
            print("Multi-market submit is only enabled for live data. Running as dry-run.")

        if data_source_settings.data_source == "golden":
            print("Golden data source active. Configured symbols/coins are used as scan labels only.")
            print(f"Golden scenario: {data_source_settings.golden_scenario}")
            _print_golden_expectations(data_source_settings.golden_scenario or "")

        if data_source_settings.data_source not in {"live", "golden"}:
            raise ValueError("Invalid DATA_SOURCE")
        if not scan_settings.assets:
            raise ValueError("No markets configured for multi-market scan")

        client = ProprClient(propr_config)
        order_service = ProprOrderService(client)
        symbol_service = HyperliquidSymbolService()
        registry = AssetRegistry()
        ctx = build_scan_context(
            environment=environment,
            data_source_settings=data_source_settings,
            scan_settings=scan_settings,
            propr_client=client,
            order_service=order_service,
            symbol_service=symbol_service,
            registry=registry,
            # Keep this lookup here so unit tests can monkeypatch
            # scripts.multi_market_scan.load_hyperliquid_config_from_env.
            hyperliquid_base_config=(
                load_hyperliquid_config_from_env() if data_source_settings.data_source == "live" else None
            ),
        )

        scan_executed_at = None
        scan_results = scan_markets_once(
            ctx,
            executed_at=scan_executed_at,
            scan_cycle_phase="dry_run",
            build_data_batch_and_config_fn=_build_data_batch_and_config,
            run_app_cycle_fn=run_app_cycle,
        )
        scan_summaries = [row.summary for row in scan_results]

        markets_with_valid_trend = [item for item in scan_summaries if item["trend_signal_valid"]]
        markets_with_valid_countertrend = [item for item in scan_summaries if item["countertrend_signal_valid"]]
        markets_with_pending_order_candidate = [item for item in scan_summaries if item["pending_order_present"]]
        interesting_markets = [
            item for item in scan_summaries if item["decision_action"] and item["decision_action"] != "NO_ACTION"
        ]

        print("Scan Summary:")
        print(f"  total_markets_scanned: {len(scan_summaries)}")
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
                _persist_live_status(
                    client,
                    environment,
                    primary_symbol,
                    challenge_id=scan_settings.challenge_id,
                    challenge_attempt_id=scan_settings.challenge_attempt_id,
                )
            return

        execute_candidates(ctx, scan_results, executed_at=datetime.now(timezone.utc).isoformat())

        _persist_live_status(
            client,
            environment,
            primary_symbol,
            challenge_id=scan_settings.challenge_id,
            challenge_attempt_id=scan_settings.challenge_attempt_id,
        )
    except Exception as exc:
        print(f"Multi-market scan failed: {exc}")
        if client is not None:
            try:
                _persist_live_status(
                    client,
                    environment,
                    primary_symbol,
                    challenge_id=scan_settings.challenge_id,
                    challenge_attempt_id=scan_settings.challenge_attempt_id,
                    last_error=str(exc),
                )
            except Exception:
                pass


if __name__ == "__main__":
    main()

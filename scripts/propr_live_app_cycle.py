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
from config.strategy_config import StrategyConfig
from data.providers import get_data_provider
from pydantic import BaseModel
from utils.env_loader import (
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



def main() -> None:
    print("Live app cycle started.")

    try:
        config = load_propr_config_from_env()
        settings = load_live_app_cycle_settings_from_env()
        allow_execution = settings.allow_submit == "YES"

        print(f"Environment: {config.environment}")
        print(f"Base URL: {config.base_url}")
        print(f"Data source: {settings.data_source}")
        if settings.golden_scenario:
            print(f"Golden scenario: {settings.golden_scenario}")

        if settings.environment != "beta":
            raise ValueError("Live app cycle is only allowed in beta")
        if settings.confirm != "YES":
            raise ValueError("Live app cycle requires LIVE_APP_CYCLE_CONFIRM=YES")
        if settings.data_source == "golden" and allow_execution:
            raise ValueError("Submit is not allowed with golden data source")

        client = ProprClient(config)
        order_service = ProprOrderService(client)
        data_provider = get_data_provider(settings.data_source, settings.golden_scenario)
        data_batch = data_provider.get_data()
        strategy_config = data_batch.config or StrategyConfig()

        print(f"source_name: {data_batch.source_name}")

        result = run_app_cycle(
            client=client,
            order_service=order_service,
            symbol=settings.test_symbol,
            candles=data_batch.candles,
            config=strategy_config,
            account_balance=10000.0,
            require_healthy_core=settings.require_healthy_core,
            allow_execution=allow_execution,
        )

        _print_section("Challenge Context", result.challenge_context)
        _print_section("Synced State", result.synced_state)
        _print_section("Strategy Result", result.strategy_result)
        _print_section("Post-Cycle State", result.post_cycle_state)
        _print_section("Risk Guard Result", result.risk_guard_result)
        _print_section("Health Guard Result", result.health_guard_result)
        print(f"Execution allowed: {allow_execution}")
        _print_section("Execution response", result.execution_response)
        if result.skipped_reason:
            print(f"Skipped reason: {result.skipped_reason}")

        print("Live app cycle finished.")
    except Exception as exc:
        print(f"Live app cycle failed: {exc}")


if __name__ == "__main__":
    main()

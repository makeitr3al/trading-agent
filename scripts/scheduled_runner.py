from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
import sys
from time import sleep

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trading_app import run_app_cycle
from broker.order_service import ProprOrderService
from broker.propr_client import ProprClient
from config.strategy_config import StrategyConfig
from data.providers import get_data_provider
from utils.env_loader import load_propr_config_from_env, load_runner_settings_from_env


# TODO: Later persist last_run metadata across restarts.
# TODO: Later replace the live stub provider with a real market data source.
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



def _compact_result_line(result: object) -> str:
    challenge_account_id = None
    decision_action = None
    if getattr(result, "challenge_context", None) is not None:
        challenge_account_id = result.challenge_context.account_id
    if getattr(result, "strategy_result", None) is not None:
        decision_action = result.strategy_result.decision.action.value

    return (
        f"skipped_reason={getattr(result, 'skipped_reason', None)!r}, "
        f"challenge_account_id={challenge_account_id!r}, "
        f"decision_action={decision_action!r}, "
        f"submitted_order={getattr(result, 'submitted_order', False)}, "
        f"replaced_order={getattr(result, 'replaced_order', False)}"
    )



def main() -> None:
    print("Scheduled runner started.")

    try:
        propr_config = load_propr_config_from_env()
        runner_settings = load_runner_settings_from_env()
        allow_execution = runner_settings.allow_submit == "YES"

        print(f"Environment: {propr_config.environment}")
        print(f"Mode: {runner_settings.mode}")
        print(f"Symbol: {runner_settings.symbol}")
        print(f"Submit allowed: {allow_execution}")
        print(f"Require healthy core: {runner_settings.require_healthy_core}")
        print(f"Data source: {runner_settings.data_source}")
        if runner_settings.golden_scenario:
            print(f"Golden scenario: {runner_settings.golden_scenario}")

        if runner_settings.confirm != "YES":
            raise ValueError("Scheduled runner requires RUNNER_CONFIRM=YES")
        if runner_settings.data_source == "golden" and allow_execution:
            raise ValueError("Submit is not allowed with golden data source")

        client = ProprClient(propr_config)
        order_service = ProprOrderService(client)
        data_provider = get_data_provider(
            runner_settings.data_source,
            runner_settings.golden_scenario,
        )

        last_run_datetime: datetime | None = None
        last_run_date: date | None = None
        loop_sleep_seconds = min(runner_settings.interval_seconds, 30)

        while True:
            current_utc_datetime = datetime.now(timezone.utc)
            should_run = False

            if runner_settings.mode == "daily":
                should_run = should_run_now_daily(
                    current_utc_datetime=current_utc_datetime,
                    target_hh_mm=runner_settings.time_utc,
                    last_run_date=last_run_date,
                )
            else:
                should_run = should_run_now_interval(
                    last_run_datetime=last_run_datetime,
                    interval_seconds=runner_settings.interval_seconds,
                    current_utc_datetime=current_utc_datetime,
                )

            if should_run:
                print(f"Running app cycle at {current_utc_datetime.isoformat()}")
                data_batch = data_provider.get_data()
                strategy_config = data_batch.config or StrategyConfig()
                print(f"source_name={data_batch.source_name}")

                result = run_app_cycle(
                    client=client,
                    order_service=order_service,
                    symbol=runner_settings.symbol,
                    candles=data_batch.candles,
                    config=strategy_config,
                    account_balance=10000.0,
                    require_healthy_core=runner_settings.require_healthy_core,
                    allow_execution=allow_execution,
                )
                print(_compact_result_line(result))
                last_run_datetime = current_utc_datetime
                last_run_date = current_utc_datetime.date()

            sleep(loop_sleep_seconds)
    except KeyboardInterrupt:
        print("Scheduled runner stopped.")
    except Exception as exc:
        print(f"Scheduled runner failed: {exc}")


if __name__ == "__main__":
    main()

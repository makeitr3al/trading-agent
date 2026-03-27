from __future__ import annotations

import inspect
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategy.engine import run_agent_cycle, run_strategy_cycle
from strategy.state import AgentState


SCENARIO_FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "strategy_scenarios.py"
MODULE_NAME = "strategy_scenarios_runtime"

# TODO: Later optionally emit JSON or JUnit-style output for CI reporting.
# TODO: Later optionally add filtering by scenario name prefix or tag.


def _load_strategy_scenarios_module() -> ModuleType:
    if not SCENARIO_FIXTURE_PATH.exists():
        raise ValueError("Golden scenario fixtures could not be found")

    spec = spec_from_file_location(MODULE_NAME, SCENARIO_FIXTURE_PATH)
    if spec is None or spec.loader is None:
        raise ValueError("Golden scenario fixtures could not be loaded")

    module = module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module



def _is_zero_arg_builder(name: str, value: object) -> bool:
    if name.startswith("_") or not name.endswith("_scenario") or not callable(value):
        return False

    signature = inspect.signature(value)
    required_parameters = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.default is inspect._empty
        and parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    return not required_parameters



def _discover_scenario_builders(module: ModuleType) -> dict[str, Callable[[], object]]:
    builders: dict[str, Callable[[], object]] = {}
    for name in dir(module):
        value = getattr(module, name)
        if not _is_zero_arg_builder(name, value):
            continue

        scenario = value()
        scenario_name = getattr(scenario, "name", None)
        if scenario_name:
            builders[str(scenario_name)] = value
    return builders



def _bool_text(value: bool) -> str:
    return "PASS" if value else "FAIL"



def _evaluate_scenario(scenario: Any) -> tuple[bool, list[str]]:
    messages: list[str] = []
    passed = True

    uses_agent_cycle = scenario.agent_state is not None or scenario.expected_consumed_flag is not None

    if uses_agent_cycle:
        result, new_state = run_agent_cycle(
            candles=scenario.candles,
            config=scenario.config,
            account_balance=scenario.account_balance,
            state=scenario.agent_state or AgentState(),
        )
        order_present = new_state.pending_order is not None
        consumed_flag = new_state.trend_signal_consumed_in_regime
    else:
        result = run_strategy_cycle(
            candles=scenario.candles,
            config=scenario.config,
            account_balance=scenario.account_balance,
            active_trade=scenario.active_trade,
        )
        order_present = result.order is not None
        consumed_flag = None

    if scenario.expected_trend_signal_valid is not None:
        actual = result.trend_signal.is_valid if result.trend_signal is not None else None
        ok = actual == scenario.expected_trend_signal_valid
        passed = passed and ok
        messages.append(
            f"trend_signal_valid={actual} expected={scenario.expected_trend_signal_valid} {_bool_text(ok)}"
        )

    if scenario.expected_trend_signal_type is not None:
        actual = result.trend_signal.signal_type.value if result.trend_signal is not None else None
        ok = actual == scenario.expected_trend_signal_type
        passed = passed and ok
        messages.append(
            f"trend_signal_type={actual} expected={scenario.expected_trend_signal_type} {_bool_text(ok)}"
        )

    if scenario.expected_countertrend_signal_valid is not None:
        actual = result.countertrend_signal.is_valid if result.countertrend_signal is not None else None
        ok = actual == scenario.expected_countertrend_signal_valid
        passed = passed and ok
        messages.append(
            f"countertrend_signal_valid={actual} expected={scenario.expected_countertrend_signal_valid} {_bool_text(ok)}"
        )

    if scenario.expected_countertrend_signal_type is not None:
        actual = (
            result.countertrend_signal.signal_type.value
            if result.countertrend_signal is not None
            else None
        )
        ok = actual == scenario.expected_countertrend_signal_type
        passed = passed and ok
        messages.append(
            f"countertrend_signal_type={actual} expected={scenario.expected_countertrend_signal_type} {_bool_text(ok)}"
        )

    if scenario.expected_decision_action is not None:
        actual = result.decision.action.value
        ok = actual == scenario.expected_decision_action
        passed = passed and ok
        messages.append(
            f"decision_action={actual} expected={scenario.expected_decision_action} {_bool_text(ok)}"
        )

    if scenario.expected_order_present is not None:
        ok = order_present == scenario.expected_order_present
        passed = passed and ok
        messages.append(
            f"order_present={order_present} expected={scenario.expected_order_present} {_bool_text(ok)}"
        )

    if scenario.expected_break_even_activated is not None:
        actual = result.updated_trade.break_even_activated if result.updated_trade is not None else None
        ok = actual == scenario.expected_break_even_activated
        passed = passed and ok
        messages.append(
            f"break_even_activated={actual} expected={scenario.expected_break_even_activated} {_bool_text(ok)}"
        )

    if scenario.expected_consumed_flag is not None:
        ok = consumed_flag == scenario.expected_consumed_flag
        passed = passed and ok
        messages.append(
            f"consumed_flag={consumed_flag} expected={scenario.expected_consumed_flag} {_bool_text(ok)}"
        )

    return passed, messages



def main() -> None:
    print("Run all golden scenarios started.")

    try:
        module = _load_strategy_scenarios_module()
        builders = _discover_scenario_builders(module)
        scenario_names = sorted(builders)

        print(f"Total golden scenarios: {len(scenario_names)}")
        print("Mode: scheduled-runner-style dry run")
        print("Execution: disabled")

        passed_count = 0
        failed_count = 0
        failed_scenarios: list[str] = []

        for scenario_name in scenario_names:
            scenario = builders[scenario_name]()
            print(f"Scenario: {scenario.name}")
            passed, messages = _evaluate_scenario(scenario)
            for message in messages:
                print(f"  {message}")
            print(f"  result: {_bool_text(passed)}")

            if passed:
                passed_count += 1
            else:
                failed_count += 1
                failed_scenarios.append(scenario.name)

        print("Golden suite summary:")
        print(f"  total: {len(scenario_names)}")
        print(f"  passed: {passed_count}")
        print(f"  failed: {failed_count}")
        if failed_scenarios:
            print("  failed_scenarios:")
            for scenario_name in failed_scenarios:
                print(f"    {scenario_name}")
        else:
            print("  failed_scenarios: none")
    except Exception as exc:
        print(f"Run all golden scenarios failed: {exc}")


if __name__ == "__main__":
    main()

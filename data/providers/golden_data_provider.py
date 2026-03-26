from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Callable
import sys

from data.providers.base import DataBatch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "strategy_scenarios.py"
MODULE_NAME = "strategy_scenarios"


class GoldenDataProvider:
    def __init__(self, scenario_name: str) -> None:
        if not scenario_name or not scenario_name.strip():
            raise ValueError("Missing GOLDEN_SCENARIO for golden data source")
        self.scenario_name = scenario_name.strip()

    def get_data(self) -> DataBatch:
        scenario = _load_golden_scenario(self.scenario_name)
        return DataBatch(
            candles=scenario.candles,
            symbol=None,
            source_name=f"golden:{scenario.name}",
            config=scenario.config,
        )



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



def _discover_scenario_builders(module: ModuleType) -> dict[str, Callable[[], object]]:
    builders: dict[str, Callable[[], object]] = {}
    for name in dir(module):
        if not name.endswith("_scenario"):
            continue
        value = getattr(module, name)
        if callable(value):
            scenario = value()
            scenario_name = getattr(scenario, "name", None)
            if scenario_name:
                builders[str(scenario_name)] = value
    return builders



def _load_golden_scenario(scenario_name: str):
    module = _load_strategy_scenarios_module()
    builders = _discover_scenario_builders(module)
    if scenario_name not in builders:
        available = ", ".join(sorted(builders)) or "none"
        raise ValueError(
            f"Unknown GOLDEN_SCENARIO '{scenario_name}'. Available scenarios: {available}"
        )
    return builders[scenario_name]()

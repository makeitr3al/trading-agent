from __future__ import annotations

import argparse
import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_STATUS_PATH = PROJECT_ROOT / "artifacts" / "test_suite_status.json"
DEFAULT_LOG_PATH = PROJECT_ROOT / "artifacts" / "test_suite_last.log"
SANITIZED_PYTEST_ENV_KEYS = (
    "TRADING_JOURNAL_PATH",
    "RUNNER_STATUS_PATH",
    "TRADING_AGENT_RUNTIME_CONFIG_PATH",
    "TRADING_AGENT_DOTENV_PATH",
    "TRADING_AGENT_USE_DOTENV_FALLBACK",
)


SUITE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "core": {
        "description": "Focused local regression suite for core bot logic and runtime helpers.",
        "requires_live_beta_writes": False,
        "steps": [
            {
                "name": "core_pytest",
                "kind": "pytest",
                "command": [
                    "tests/test_strategy_golden_cases.py",
                    "tests/test_trading_app.py",
                    "tests/test_state_sync.py",
                    "tests/test_order_service.py",
                    "tests/test_execution.py",
                    "tests/test_journal_integration.py",
                    "tests/test_journal_snapshot.py",
                    "tests/test_runtime_status.py",
                ],
            }
        ],
    },
    "unit": {
        "description": "Full local pytest suite under tests/.",
        "requires_live_beta_writes": False,
        "steps": [
            {
                "name": "all_pytests",
                "kind": "pytest",
                "command": ["tests"],
            }
        ],
    },
    "preflight": {
        "description": "Recommended first-start verification: full pytest suite, golden dry-run suite, and Propr read-only smoke test.",
        "requires_live_beta_writes": False,
        "steps": [
            {
                "name": "all_pytests",
                "kind": "pytest",
                "command": ["tests"],
            },
            {
                "name": "golden_dry_run",
                "kind": "python",
                "command": ["scripts/run_all_golden_scenarios.py"],
            },
            {
                "name": "propr_smoke",
                "kind": "python",
                "command": ["scripts/propr_smoke_test.py"],
            },
        ],
    },
    "beta_write": {
        "description": "Manual Beta write verification. This suite submits real Beta test orders and must stay opt-in.",
        "requires_live_beta_writes": True,
        "steps": [
            {
                "name": "submit_cancel",
                "kind": "python",
                "command": ["scripts/propr_submit_cancel_test.py"],
            },
            {
                "name": "order_types",
                "kind": "python",
                "command": ["scripts/propr_order_types_test.py"],
            },
        ],
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail_lines(path: Path, limit: int = 20) -> list[str]:
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        lines = deque(handle, maxlen=limit)
    return [line.rstrip("\r\n") for line in lines]


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")


def _resolved_command(step: dict[str, Any], pytest_args: list[str]) -> list[str]:
    if step["kind"] == "pytest":
        return [sys.executable, "-m", "pytest", *step["command"], *pytest_args]
    return [sys.executable, *step["command"]]


def _step_env(step_kind: str) -> dict[str, str]:
    env = dict(os.environ)
    if step_kind == "pytest":
        for key in SANITIZED_PYTEST_ENV_KEYS:
            env.pop(key, None)
    return env


def _describe_suite(suite_name: str, pytest_args: list[str]) -> dict[str, Any]:
    definition = SUITE_DEFINITIONS[suite_name]
    return {
        "suite": suite_name,
        "description": definition["description"],
        "requires_live_beta_writes": definition["requires_live_beta_writes"],
        "steps": [
            {
                "name": step["name"],
                "kind": step["kind"],
                "command": _resolved_command(step, pytest_args),
            }
            for step in definition["steps"]
        ],
    }


def _print_suite_list() -> None:
    for suite_name in sorted(SUITE_DEFINITIONS):
        description = SUITE_DEFINITIONS[suite_name]["description"]
        print(f"{suite_name}: {description}")


def _append_step_header(log_handle, step_name: str, command: list[str]) -> None:
    log_handle.write(f"===== STEP {step_name} =====\n")
    log_handle.write("COMMAND: " + " ".join(command) + "\n")
    log_handle.write(f"STARTED_AT: {_utc_now_iso()}\n\n")


def _append_step_footer(log_handle, return_code: int) -> None:
    log_handle.write(f"\nRETURN_CODE: {return_code}\n")
    log_handle.write(f"FINISHED_AT: {_utc_now_iso()}\n\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local verification suites and persist a JSON status file.")
    parser.add_argument("--suite", choices=sorted(SUITE_DEFINITIONS.keys()), default="preflight")
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS_PATH))
    parser.add_argument("--log-path", default=str(DEFAULT_LOG_PATH))
    parser.add_argument("--pytest-arg", action="append", default=[], help="Additional pytest argument.")
    parser.add_argument(
        "--allow-live-beta-writes",
        action="store_true",
        help="Required for suites that submit real test orders in the Propr Beta environment.",
    )
    parser.add_argument("--list-suites", action="store_true", help="List available suite names and exit.")
    parser.add_argument(
        "--describe-suite",
        choices=sorted(SUITE_DEFINITIONS.keys()),
        help="Print the resolved steps for one suite as JSON and exit.",
    )
    args = parser.parse_args()

    if args.list_suites:
        _print_suite_list()
        return 0

    if args.describe_suite:
        print(json.dumps(_describe_suite(args.describe_suite, args.pytest_arg), ensure_ascii=True, indent=2))
        return 0

    suite_name = args.suite
    suite_definition = SUITE_DEFINITIONS[suite_name]
    if suite_definition["requires_live_beta_writes"] and not args.allow_live_beta_writes:
        print("Refusing to run live Beta write suite without --allow-live-beta-writes.")
        return 2

    status_path = Path(args.status_path)
    log_path = Path(args.log_path)
    suite_description = _describe_suite(suite_name, args.pytest_arg)
    started_at = _utc_now_iso()
    step_results: list[dict[str, Any]] = []

    _write_status(
        status_path,
        {
            "status_version": 2,
            "runner_state": "running",
            "suite": suite_name,
            "description": suite_description["description"],
            "requires_live_beta_writes": suite_description["requires_live_beta_writes"],
            "started_at": started_at,
            "finished_at": None,
            "success": None,
            "return_code": None,
            "log_path": str(log_path),
            "steps": step_results,
            "output_tail": [],
            "last_error": None,
        },
    )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    overall_return_code = 0
    with log_path.open("w", encoding="utf-8") as log_handle:
        for step in suite_description["steps"]:
            command = step["command"]
            _append_step_header(log_handle, step["name"], command)
            step_started_at = _utc_now_iso()
            process = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                env=_step_env(step["kind"]),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            _append_step_footer(log_handle, process.returncode)

            step_result = {
                "name": step["name"],
                "kind": step["kind"],
                "command": command,
                "started_at": step_started_at,
                "finished_at": _utc_now_iso(),
                "return_code": process.returncode,
                "success": process.returncode == 0,
            }
            step_results.append(step_result)

            if process.returncode != 0:
                overall_return_code = process.returncode
                break

    success = overall_return_code == 0
    _write_status(
        status_path,
        {
            "status_version": 2,
            "runner_state": "completed" if success else "failed",
            "suite": suite_name,
            "description": suite_description["description"],
            "requires_live_beta_writes": suite_description["requires_live_beta_writes"],
            "started_at": started_at,
            "finished_at": _utc_now_iso(),
            "success": success,
            "return_code": overall_return_code,
            "log_path": str(log_path),
            "steps": step_results,
            "output_tail": _tail_lines(log_path),
            "last_error": None if success else "verification suite returned non-zero exit code",
        },
    )
    return overall_return_code


if __name__ == "__main__":
    raise SystemExit(main())

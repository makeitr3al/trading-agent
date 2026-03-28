from pathlib import Path
import json
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_run_test_suite_writes_success_status_and_log(tmp_path: Path) -> None:
    status_path = tmp_path / "test_status.json"
    log_path = tmp_path / "test.log"

    completed = subprocess.run(
        [
            sys.executable,
            "run_test_suite.py",
            "--suite",
            "core",
            "--status-path",
            str(status_path),
            "--log-path",
            str(log_path),
            "--pytest-arg=-q",
        ],
        cwd=PROJECT_ROOT,
        check=False,
    )

    assert completed.returncode == 0
    persisted = json.loads(status_path.read_text(encoding="utf-8"))
    assert persisted["runner_state"] == "completed"
    assert persisted["success"] is True
    assert persisted["return_code"] == 0
    assert persisted["suite"] == "core"
    assert persisted["log_path"] == str(log_path)
    assert persisted["steps"][0]["name"] == "core_pytest"
    assert persisted["steps"][0]["success"] is True
    assert log_path.exists()


def test_describe_suite_shows_preflight_steps() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "run_test_suite.py",
            "--describe-suite",
            "preflight",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert payload["suite"] == "preflight"
    assert [step["name"] for step in payload["steps"]] == [
        "all_pytests",
        "golden_dry_run",
        "propr_smoke",
    ]


def test_beta_write_requires_explicit_opt_in() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "run_test_suite.py",
            "--suite",
            "beta_write",
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--allow-live-beta-writes" in completed.stdout

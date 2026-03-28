from pathlib import Path
import json
import os
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_config_set_and_show_roundtrip(tmp_path: Path) -> None:
    runtime_path = tmp_path / "runtime_overrides.json"
    env = dict(os.environ)
    env["TRADING_AGENT_RUNTIME_CONFIG_PATH"] = str(runtime_path)

    set_result = subprocess.run(
        [
            sys.executable,
            "runtime_config.py",
            "set",
            "--propr-env",
            "beta",
            "--propr-symbol",
            "eth/usdc",
            "--propr-leverage",
            "3",
            "--scan-markets",
            "btc/usdc:btc,eth/usdc:eth",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert set_result.returncode == 0
    persisted = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert persisted["PROPR_ENV"] == "beta"
    assert persisted["PROPR_SYMBOL"] == "ETH/USDC"
    assert persisted["PROPR_LEVERAGE"] == "3"
    assert persisted["SCAN_MARKETS"] == "BTC/USDC:BTC,ETH/USDC:ETH"

    show_result = subprocess.run(
        [sys.executable, "runtime_config.py", "show"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert show_result.returncode == 0
    payload = json.loads(show_result.stdout)
    assert payload["effective"]["PROPR_SYMBOL"] == "ETH/USDC"
    assert payload["effective"]["PROPR_LEVERAGE"] == "3"
    assert payload["effective"]["SCAN_MARKETS"] == "BTC/USDC:BTC,ETH/USDC:ETH"


def test_runtime_config_clear_all_removes_overrides(tmp_path: Path) -> None:
    runtime_path = tmp_path / "runtime_overrides.json"
    runtime_path.write_text('{"PROPR_ENV": "beta", "PROPR_SYMBOL": "BTC/USDC"}\n', encoding="utf-8")
    env = dict(os.environ)
    env["TRADING_AGENT_RUNTIME_CONFIG_PATH"] = str(runtime_path)

    clear_result = subprocess.run(
        [sys.executable, "runtime_config.py", "clear", "--all"],
        cwd=PROJECT_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert clear_result.returncode == 0
    persisted = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert persisted == {}

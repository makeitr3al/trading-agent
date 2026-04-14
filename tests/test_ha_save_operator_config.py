"""Tests for ha_addons/trading_agent/ha_save_operator_config.py (HA shell_command helper)."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def _load_save_module():
    path = Path(__file__).resolve().parents[1] / "ha_addons" / "trading_agent" / "ha_save_operator_config.py"
    spec = importlib.util.spec_from_file_location("ha_save_operator_config", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_save_treats_empty_leverage_as_one(tmp_path: Path, monkeypatch) -> None:
    mod = _load_save_module()
    cfg = tmp_path / "operator_config.json"
    monkeypatch.setenv("HA_SAVE_OPERATOR_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(sys, "argv", ["ha_save_operator_config.py", "scharf", "beta", "", "BTC", "false", "07:00", "", "false"])
    assert mod.main() == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["leverage"] == 1
    assert data["markets"] == "BTC"
    assert data["challenge_attempt_id"] == ""
    assert data["push_enabled"] is False


def test_refuses_when_mode_or_environment_empty_and_does_not_overwrite(tmp_path: Path, monkeypatch) -> None:
    mod = _load_save_module()
    cfg = tmp_path / "operator_config.json"
    original = '{"mode": "scharf", "environment": "beta", "leverage": 3}\n'
    cfg.write_text(original, encoding="utf-8")
    monkeypatch.setenv("HA_SAVE_OPERATOR_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(
        sys,
        "argv",
        ["ha_save_operator_config.py", "", "", "", "BTC", "false", "07:00", "", "false"],
    )
    assert mod.main() == 2
    assert cfg.read_text(encoding="utf-8") == original


def test_save_preserves_existing_challenge_id(tmp_path: Path, monkeypatch) -> None:
    mod = _load_save_module()
    cfg = tmp_path / "operator_config.json"
    cfg.write_text(
        json.dumps(
            {"challenge_id": "urn:prp:challenge:keep", "markets": "ETH"},
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HA_SAVE_OPERATOR_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(
        sys,
        "argv",
        ["ha_save_operator_config.py", "preflight", "beta", "2", "BTC,SOL", "true", "08:30", "urn:prp:attempt:new", "true"],
    )
    assert mod.main() == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["challenge_id"] == "urn:prp:challenge:keep"
    assert data["challenge_attempt_id"] == "urn:prp:attempt:new"
    assert data["leverage"] == 2

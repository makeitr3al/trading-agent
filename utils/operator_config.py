from __future__ import annotations

import json
import os
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OPERATOR_DATA_PATH = Path("artifacts")
DEFAULT_OPERATOR_CONFIG = {
    "mode": "scharf",
    "environment": "beta",
    "leverage": 1,
    "markets": "BTC/USDC:BTC,ETH/USDC:ETH,SOL/USDC:SOL",
    "scheduling_enabled": False,
    "schedule_time": "07:00",
}
SUPPORTED_MODES = ("scharf", "preflight", "beta_write")
SUPPORTED_ENVIRONMENTS = ("beta", "prod")


def resolve_operator_data_path() -> Path:
    configured = (os.getenv("TRADING_AGENT_DATA_PATH") or "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_OPERATOR_DATA_PATH


def resolve_operator_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)

    configured = (os.getenv("TRADING_AGENT_OPERATOR_CONFIG_PATH") or "").strip()
    if configured:
        return Path(configured)
    return resolve_operator_data_path() / "operator_config.json"


def _normalize_mode(value: str | None) -> str:
    normalized = (value or DEFAULT_OPERATOR_CONFIG["mode"]).strip().lower()
    if normalized not in SUPPORTED_MODES:
        raise ValueError(f"mode must be one of: {', '.join(SUPPORTED_MODES)}")
    return normalized


def _normalize_environment(value: str | None) -> str:
    normalized = (value or DEFAULT_OPERATOR_CONFIG["environment"]).strip().lower()
    if normalized not in SUPPORTED_ENVIRONMENTS:
        raise ValueError(f"environment must be one of: {', '.join(SUPPORTED_ENVIRONMENTS)}")
    return normalized


def _normalize_leverage(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("leverage must be an integer") from exc
    if parsed < 1:
        raise ValueError("leverage must be greater than or equal to 1")
    return parsed


def _normalize_markets(value: str | None) -> str:
    raw_value = (value or DEFAULT_OPERATOR_CONFIG["markets"]).strip()
    entries = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not entries:
        raise ValueError("markets must not be empty")

    normalized_entries: list[str] = []
    for entry in entries:
        if ":" not in entry:
            raise ValueError("markets entries must use SYMBOL:COIN format")
        symbol, coin = entry.split(":", 1)
        symbol_parts = [part.strip().upper() for part in symbol.split("/") if part.strip()]
        normalized_coin = coin.strip().upper()
        if len(symbol_parts) != 2 or not normalized_coin:
            raise ValueError("markets entries must use SYMBOL:COIN format")
        normalized_entries.append(f"{symbol_parts[0]}/{symbol_parts[1]}:{normalized_coin}")
    return ",".join(normalized_entries)


def _normalize_scheduling_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError("scheduling_enabled must be true or false")


def _normalize_schedule_time(value: str | None) -> str:
    normalized = (value or DEFAULT_OPERATOR_CONFIG["schedule_time"]).strip()
    try:
        return datetime.strptime(normalized, "%H:%M").strftime("%H:%M")
    except ValueError as exc:
        raise ValueError("schedule_time must use HH:MM format") from exc


def _default_operator_config() -> dict[str, Any]:
    return dict(DEFAULT_OPERATOR_CONFIG)


def normalize_operator_config(payload: dict[str, Any]) -> dict[str, Any]:
    defaults = _default_operator_config()
    merged = {**defaults, **(payload or {})}
    return {
        "mode": _normalize_mode(merged.get("mode")),
        "environment": _normalize_environment(merged.get("environment")),
        "leverage": _normalize_leverage(merged.get("leverage")),
        "markets": _normalize_markets(merged.get("markets")),
        "scheduling_enabled": _normalize_scheduling_enabled(merged.get("scheduling_enabled")),
        "schedule_time": _normalize_schedule_time(merged.get("schedule_time")),
    }


def load_operator_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = resolve_operator_config_path(path)
    if not config_path.exists():
        return normalize_operator_config({})

    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("operator config must contain a JSON object")
    return normalize_operator_config(payload)


def save_operator_config(config: dict[str, Any], path: str | Path | None = None) -> Path:
    config_path = resolve_operator_config_path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    normalized = normalize_operator_config(config)
    config_path.write_text(json.dumps(normalized, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return config_path


def update_operator_config(
    updates: dict[str, Any],
    *,
    reset: bool = False,
    path: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    current = {} if reset else load_operator_config(path=path)
    merged = {**current, **updates}
    normalized = normalize_operator_config(merged)
    persisted_path = save_operator_config(normalized, path=path)
    return persisted_path, normalized


def _first_market(markets: str) -> tuple[str, str]:
    first_entry = markets.split(",", 1)[0].strip()
    symbol, coin = first_entry.split(":", 1)
    return symbol.strip(), coin.strip()


def resolve_operator_paths(
    config: dict[str, Any],
    *,
    data_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, str]:
    resolved_data_path = Path(data_path) if data_path is not None else resolve_operator_data_path()
    resolved_config_path = resolve_operator_config_path(config_path)
    environment = str(config["environment"]).strip().lower()
    return {
        "data_path": str(resolved_data_path),
        "operator_config_path": str(resolved_config_path),
        "journal_path": str(resolved_data_path / f"trading_journal_{environment}.jsonl"),
        "runtime_status_path": str(resolved_data_path / f"runtime_status_{environment}.json"),
        "test_status_path": str(resolved_data_path / "test_suite_status.json"),
        "test_log_path": str(resolved_data_path / "test_suite_last.log"),
    }


def build_operator_payload(path: str | Path | None = None) -> dict[str, Any]:
    config = load_operator_config(path=path)
    primary_symbol, primary_coin = _first_market(config["markets"])
    paths = resolve_operator_paths(config, config_path=path)
    return {
        "config_path": str(resolve_operator_config_path(path)),
        "config": config,
        "derived": {
            "primary_symbol": primary_symbol,
            "primary_coin": primary_coin,
        },
        "paths": paths,
    }


def export_operator_env_shell(path: str | Path | None = None) -> str:
    payload = build_operator_payload(path=path)
    config = payload["config"]
    paths = payload["paths"]
    derived = payload["derived"]
    values = {
        "OPERATOR_MODE": config["mode"],
        "OPERATOR_ENVIRONMENT": config["environment"],
        "OPERATOR_LEVERAGE": str(config["leverage"]),
        "OPERATOR_MARKETS": config["markets"],
        "OPERATOR_SCHEDULING_ENABLED": "YES" if config["scheduling_enabled"] else "NO",
        "OPERATOR_SCHEDULE_TIME": config["schedule_time"],
        "OPERATOR_PRIMARY_SYMBOL": derived["primary_symbol"],
        "OPERATOR_PRIMARY_COIN": derived["primary_coin"],
        "OPERATOR_JOURNAL_PATH": paths["journal_path"],
        "OPERATOR_RUNTIME_STATUS_PATH": paths["runtime_status_path"],
        "OPERATOR_TEST_STATUS_PATH": paths["test_status_path"],
        "OPERATOR_TEST_LOG_PATH": paths["test_log_path"],
    }
    return "\n".join(f"export {key}={shlex.quote(value)}" for key, value in values.items())

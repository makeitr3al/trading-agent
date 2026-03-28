from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_OVERRIDES_PATH = Path("artifacts/runtime_overrides.json")
DEFAULT_DOTENV_PATH = Path(".env")
SUPPORTED_RUNTIME_OVERRIDE_KEYS = ("PROPR_ENV", "PROPR_SYMBOL", "PROPR_LEVERAGE", "SCAN_MARKETS")


def resolve_runtime_overrides_path() -> Path:
    configured = (os.getenv("TRADING_AGENT_RUNTIME_CONFIG_PATH") or "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_RUNTIME_OVERRIDES_PATH


def resolve_dotenv_path() -> Path:
    configured = (os.getenv("TRADING_AGENT_DOTENV_PATH") or "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_DOTENV_PATH


def should_use_dotenv_fallback() -> bool:
    return (os.getenv("TRADING_AGENT_USE_DOTENV_FALLBACK") or "").strip().upper() == "YES"


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_dotenv_defaults(path: str | Path | None = None) -> dict[str, str]:
    dotenv_path = Path(path) if path is not None else resolve_dotenv_path()
    if not dotenv_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if not normalized_key:
            continue
        normalized_value = _strip_wrapping_quotes(value.strip())
        values[normalized_key] = normalized_value
    return values


def load_runtime_overrides(path: str | Path | None = None) -> dict[str, str]:
    overrides_path = Path(path) if path is not None else resolve_runtime_overrides_path()
    if not overrides_path.exists():
        return {}

    payload = json.loads(overrides_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Runtime overrides file must contain a JSON object")

    normalized: dict[str, str] = {}
    for key in SUPPORTED_RUNTIME_OVERRIDE_KEYS:
        value = payload.get(key)
        if value is None:
            continue
        normalized[key] = str(value).strip()
    return normalized


def save_runtime_overrides(overrides: dict[str, Any], path: str | Path | None = None) -> Path:
    overrides_path = Path(path) if path is not None else resolve_runtime_overrides_path()
    overrides_path.parent.mkdir(parents=True, exist_ok=True)

    persisted = {
        key: str(value).strip()
        for key, value in overrides.items()
        if key in SUPPORTED_RUNTIME_OVERRIDE_KEYS and value is not None and str(value).strip()
    }
    overrides_path.write_text(json.dumps(persisted, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return overrides_path


def update_runtime_overrides(
    updates: dict[str, Any],
    *,
    clear_keys: list[str] | None = None,
    path: str | Path | None = None,
) -> tuple[Path, dict[str, str]]:
    current = load_runtime_overrides(path=path)
    for key, value in updates.items():
        if key not in SUPPORTED_RUNTIME_OVERRIDE_KEYS:
            continue
        if value is None or not str(value).strip():
            current.pop(key, None)
        else:
            current[key] = str(value).strip()

    for key in clear_keys or []:
        if key in SUPPORTED_RUNTIME_OVERRIDE_KEYS:
            current.pop(key, None)

    persisted_path = save_runtime_overrides(current, path=path)
    return persisted_path, current


def get_effective_runtime_value(name: str) -> str:
    overrides = load_runtime_overrides()
    if name in overrides:
        return overrides[name]

    env_value = (os.getenv(name) or "").strip()
    if env_value:
        return env_value

    if not should_use_dotenv_fallback():
        return ""

    dotenv_values = load_dotenv_defaults()
    return (dotenv_values.get(name) or "").strip()

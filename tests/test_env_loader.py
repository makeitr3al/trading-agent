from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from utils.env_loader import load_propr_config_from_env


def _clear_propr_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "PROPR_ENV",
        "PROPR_BETA_API_KEY",
        "PROPR_BETA_API_URL",
        "PROPR_BETA_WS_URL",
        "PROPR_PROD_API_KEY",
        "PROPR_PROD_API_URL",
        "PROPR_PROD_WS_URL",
        "PROPR_PROD_CONFIRM",
    ]:
        monkeypatch.delenv(name, raising=False)


def test_defaults_to_beta_when_propr_env_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_BETA_API_KEY", "beta-key")

    config = load_propr_config_from_env()

    assert config.environment == "beta"
    assert config.api_key == "beta-key"


def test_loads_beta_config_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "beta")
    monkeypatch.setenv("PROPR_BETA_API_KEY", "beta-key")
    monkeypatch.setenv("PROPR_BETA_API_URL", "https://beta.example/v1")
    monkeypatch.setenv("PROPR_BETA_WS_URL", "wss://beta.example/ws")

    config = load_propr_config_from_env()

    assert config.environment == "beta"
    assert config.api_key == "beta-key"
    assert config.base_url == "https://beta.example/v1"
    assert config.websocket_url == "wss://beta.example/ws"


def test_loads_beta_defaults_when_beta_urls_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "beta")
    monkeypatch.setenv("PROPR_BETA_API_KEY", "beta-key")

    config = load_propr_config_from_env()

    assert config.base_url == "https://api.beta.propr.xyz/v1"
    assert config.websocket_url == "wss://api.beta.propr.xyz/ws"


def test_raises_error_when_beta_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "beta")

    with pytest.raises(ValueError, match="Missing PROPR_BETA_API_KEY"):
        load_propr_config_from_env()


def test_raises_error_on_invalid_propr_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "staging")

    with pytest.raises(ValueError, match="Invalid PROPR_ENV"):
        load_propr_config_from_env()


def test_raises_error_when_prod_confirm_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "prod")
    monkeypatch.setenv("PROPR_PROD_API_KEY", "prod-key")

    with pytest.raises(ValueError, match="PROD environment requires PROPR_PROD_CONFIRM=YES"):
        load_propr_config_from_env()


def test_raises_error_when_prod_confirm_is_not_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "prod")
    monkeypatch.setenv("PROPR_PROD_API_KEY", "prod-key")
    monkeypatch.setenv("PROPR_PROD_CONFIRM", "NO")

    with pytest.raises(ValueError, match="PROD environment requires PROPR_PROD_CONFIRM=YES"):
        load_propr_config_from_env()


def test_loads_prod_config_when_confirm_is_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "prod")
    monkeypatch.setenv("PROPR_PROD_API_KEY", "prod-key")
    monkeypatch.setenv("PROPR_PROD_API_URL", "https://prod.example/v1")
    monkeypatch.setenv("PROPR_PROD_WS_URL", "wss://prod.example/ws")
    monkeypatch.setenv("PROPR_PROD_CONFIRM", "YES")

    config = load_propr_config_from_env()

    assert config.environment == "prod"
    assert config.api_key == "prod-key"
    assert config.base_url == "https://prod.example/v1"
    assert config.websocket_url == "wss://prod.example/ws"


def test_loads_prod_defaults_when_prod_urls_are_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "prod")
    monkeypatch.setenv("PROPR_PROD_API_KEY", "prod-key")
    monkeypatch.setenv("PROPR_PROD_CONFIRM", "YES")

    config = load_propr_config_from_env()

    assert config.base_url == "https://api.propr.xyz/v1"
    assert config.websocket_url == "wss://api.propr.xyz/ws"


def test_raises_error_when_prod_key_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_propr_env(monkeypatch)
    monkeypatch.setenv("PROPR_ENV", "prod")
    monkeypatch.setenv("PROPR_PROD_CONFIRM", "YES")

    with pytest.raises(ValueError, match="Missing PROPR_PROD_API_KEY"):
        load_propr_config_from_env()

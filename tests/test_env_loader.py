from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from utils.env_loader import (
    load_live_app_cycle_settings_from_env,
    load_manual_test_settings_from_env,
    load_multi_market_scan_settings_from_env,
    load_propr_config_from_env,
    load_runner_settings_from_env,
)


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



def test_manual_test_settings_default_leverage_is_one_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROPR_LEVERAGE", raising=False)

    settings = load_manual_test_settings_from_env()

    assert settings.leverage == 1



def test_manual_test_settings_invalid_leverage_falls_back_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPR_LEVERAGE", "abc")

    settings = load_manual_test_settings_from_env()

    assert settings.leverage == 1



def test_manual_test_settings_use_new_canonical_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPR_SYMBOL", "ETH/USDC")
    monkeypatch.setenv("MANUAL_WRITE_CONFIRM", "YES")
    monkeypatch.setenv("MANUAL_LIVE_CYCLE_CONFIRM", "YES")
    monkeypatch.setenv("MANUAL_ALLOW_SUBMIT", "NO")

    settings = load_manual_test_settings_from_env()

    assert settings.symbol == "ETH/USDC"
    assert settings.manual_write_confirm == "YES"
    assert settings.manual_live_cycle_confirm == "YES"
    assert settings.manual_allow_submit == "NO"



def test_runner_settings_invalid_leverage_falls_back_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNNER_MODE", "daily")
    monkeypatch.setenv("RUNNER_TIME_UTC", "07:00")
    monkeypatch.setenv("RUNNER_INTERVAL_SECONDS", "60")
    monkeypatch.setenv("PROPR_LEVERAGE", "-5")
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("GOLDEN_SCENARIO", raising=False)

    settings = load_runner_settings_from_env()

    assert settings.leverage == 1



def test_runner_settings_use_new_canonical_env_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNNER_CONFIRM", "YES")
    monkeypatch.setenv("RUNNER_ALLOW_SUBMIT", "NO")
    monkeypatch.setenv("RUNNER_MODE", "manual")
    monkeypatch.setenv("PROPR_SYMBOL", "BTC/USDC")
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("GOLDEN_SCENARIO", raising=False)

    settings = load_runner_settings_from_env()

    assert settings.confirm == "YES"
    assert settings.allow_submit == "NO"
    assert settings.mode == "manual"
    assert settings.symbol == "BTC/USDC"



def test_live_app_cycle_settings_reads_valid_leverage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROPR_LEVERAGE", "4")
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("GOLDEN_SCENARIO", raising=False)

    settings = load_live_app_cycle_settings_from_env()

    assert settings.leverage == 4


def test_live_app_cycle_settings_reads_journal_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_JOURNAL_PATH", "artifacts/custom-journal.jsonl")
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("GOLDEN_SCENARIO", raising=False)

    settings = load_live_app_cycle_settings_from_env()

    assert settings.journal_path == "artifacts/custom-journal.jsonl"



def test_multi_market_scan_settings_can_parse_combined_market_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCAN_CONFIRM", "YES")
    monkeypatch.setenv("SCAN_MARKETS", "BTC/USDC:BTC,ETH/USDC:ETH")
    monkeypatch.delenv("SCAN_SYMBOLS", raising=False)
    monkeypatch.delenv("SCAN_HYPERLIQUID_COINS", raising=False)
    monkeypatch.setenv("TRADING_JOURNAL_PATH", "artifacts/scan-journal.jsonl")

    settings = load_multi_market_scan_settings_from_env()

    assert settings.symbols == ["BTC/USDC", "ETH/USDC"]
    assert settings.hyperliquid_coins == ["BTC", "ETH"]
    assert settings.journal_path == "artifacts/scan-journal.jsonl"


def test_live_app_cycle_settings_default_journal_path_uses_beta_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRADING_JOURNAL_PATH", raising=False)
    monkeypatch.delenv("PROPR_ENV", raising=False)
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("GOLDEN_SCENARIO", raising=False)

    settings = load_live_app_cycle_settings_from_env()

    assert settings.journal_path == "artifacts/trading_journal_beta.jsonl"


def test_runner_settings_default_journal_path_uses_prod_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRADING_JOURNAL_PATH", raising=False)
    monkeypatch.setenv("PROPR_ENV", "prod")
    monkeypatch.setenv("RUNNER_MODE", "manual")
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("GOLDEN_SCENARIO", raising=False)

    settings = load_runner_settings_from_env()

    assert settings.journal_path == "artifacts/trading_journal_prod.jsonl"


def test_live_app_cycle_settings_legacy_generic_journal_path_maps_to_environment_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_JOURNAL_PATH", "artifacts/trading_journal.jsonl")
    monkeypatch.setenv("PROPR_ENV", "beta")
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("GOLDEN_SCENARIO", raising=False)

    settings = load_live_app_cycle_settings_from_env()

    assert settings.journal_path == "artifacts/trading_journal_beta.jsonl"

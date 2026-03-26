import os
from datetime import datetime

from dotenv import load_dotenv
from pydantic import BaseModel

from config.propr_config import ProprConfig


load_dotenv()

BETA_BASE_URL = "https://api.beta.propr.xyz/v1"
BETA_WS_URL = "wss://api.beta.propr.xyz/ws"
PROD_BASE_URL = "https://api.propr.xyz/v1"
PROD_WS_URL = "wss://api.propr.xyz/ws"
DEFAULT_SYMBOL = "BTC/USDC"

# TODO: Remove legacy environment fallbacks after the new schema has fully replaced them.


class WriteTestSettings(BaseModel):
    environment: str
    write_test_confirm: str
    test_symbol: str = DEFAULT_SYMBOL


class LiveAppCycleSettings(BaseModel):
    environment: str
    confirm: str
    allow_submit: str
    test_symbol: str = DEFAULT_SYMBOL
    require_healthy_core: bool = True
    data_source: str = "live"
    golden_scenario: str | None = None


class ManualTestSettings(BaseModel):
    symbol: str = DEFAULT_SYMBOL
    require_healthy_core: bool = True
    manual_write_confirm: str = "NO"
    manual_live_cycle_confirm: str = "NO"
    manual_allow_submit: str = "NO"


class RunnerSettings(BaseModel):
    environment: str
    confirm: str
    allow_submit: str
    mode: str
    time_utc: str
    interval_seconds: int
    symbol: str = DEFAULT_SYMBOL
    require_healthy_core: bool = True
    data_source: str = "live"
    golden_scenario: str | None = None


class DataSourceSettings(BaseModel):
    data_source: str = "live"
    golden_scenario: str | None = None


def _get_env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _get_env_with_fallback(primary: str, *fallbacks: str, default: str = "") -> str:
    primary_value = _get_env(primary)
    if primary_value:
        return primary_value

    for fallback in fallbacks:
        fallback_value = _get_env(fallback)
        if fallback_value:
            return fallback_value

    return default


def _parse_yes_no(value: str, field_name: str) -> bool:
    normalized = value.strip().upper()
    if normalized == "YES":
        return True
    if normalized == "NO":
        return False
    raise ValueError(f"{field_name} must be YES or NO")


def _validate_time_utc(value: str) -> str:
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError("RUNNER_TIME_UTC must be in HH:MM format") from exc
    return parsed.strftime("%H:%M")


def _validate_interval_seconds(value: str) -> int:
    try:
        interval_seconds = int(value)
    except ValueError as exc:
        raise ValueError("RUNNER_INTERVAL_SECONDS must be an integer") from exc

    if interval_seconds <= 0:
        raise ValueError("RUNNER_INTERVAL_SECONDS must be greater than 0")
    return interval_seconds


def load_propr_config_from_env() -> ProprConfig:
    environment = _get_env("PROPR_ENV") or "beta"
    if environment not in {"beta", "prod"}:
        raise ValueError("Invalid PROPR_ENV")

    if environment == "beta":
        api_key = _get_env("PROPR_BETA_API_KEY")
        if not api_key:
            raise ValueError("Missing PROPR_BETA_API_KEY")

        base_url = _get_env("PROPR_BETA_API_URL") or BETA_BASE_URL
        websocket_url = _get_env("PROPR_BETA_WS_URL") or BETA_WS_URL
        return ProprConfig(
            environment="beta",
            api_key=api_key,
            base_url=base_url,
            websocket_url=websocket_url,
        )

    if _get_env("PROPR_PROD_CONFIRM") != "YES":
        raise ValueError("PROD environment requires PROPR_PROD_CONFIRM=YES")

    api_key = _get_env("PROPR_PROD_API_KEY")
    if not api_key:
        raise ValueError("Missing PROPR_PROD_API_KEY")

    base_url = _get_env("PROPR_PROD_API_URL") or PROD_BASE_URL
    websocket_url = _get_env("PROPR_PROD_WS_URL") or PROD_WS_URL
    return ProprConfig(
        environment="prod",
        api_key=api_key,
        base_url=base_url,
        websocket_url=websocket_url,
    )


def load_data_source_settings_from_env() -> DataSourceSettings:
    data_source = (_get_env("DATA_SOURCE") or "live").lower()
    if data_source not in {"live", "golden"}:
        raise ValueError("Invalid DATA_SOURCE")

    golden_scenario = _get_env("GOLDEN_SCENARIO") or None
    if data_source == "golden" and not golden_scenario:
        raise ValueError("Missing GOLDEN_SCENARIO for golden data source")

    return DataSourceSettings(
        data_source=data_source,
        golden_scenario=golden_scenario,
    )


def load_manual_test_settings_from_env() -> ManualTestSettings:
    symbol = _get_env_with_fallback("PROPR_SYMBOL", "PROPR_TEST_SYMBOL", default=DEFAULT_SYMBOL)
    require_healthy_core = _parse_yes_no(
        _get_env_with_fallback("PROPR_REQUIRE_HEALTHY_CORE", default="YES"),
        "PROPR_REQUIRE_HEALTHY_CORE",
    )
    manual_write_confirm = _get_env_with_fallback(
        "MANUAL_WRITE_CONFIRM",
        "WRITE_TEST_CONFIRM",
        default="NO",
    )
    manual_live_cycle_confirm = _get_env_with_fallback(
        "MANUAL_LIVE_CYCLE_CONFIRM",
        "LIVE_APP_CYCLE_CONFIRM",
        default="NO",
    )
    manual_allow_submit = _get_env_with_fallback(
        "MANUAL_ALLOW_SUBMIT",
        "LIVE_APP_CYCLE_ALLOW_SUBMIT",
        default="NO",
    )

    return ManualTestSettings(
        symbol=symbol,
        require_healthy_core=require_healthy_core,
        manual_write_confirm=manual_write_confirm,
        manual_live_cycle_confirm=manual_live_cycle_confirm,
        manual_allow_submit=manual_allow_submit,
    )


def load_runner_settings_from_env() -> RunnerSettings:
    data_source_settings = load_data_source_settings_from_env()
    environment = _get_env("PROPR_ENV") or "beta"
    confirm = _get_env_with_fallback("RUNNER_CONFIRM", "APP_RUNNER_CONFIRM", default="NO")
    allow_submit = _get_env_with_fallback(
        "RUNNER_ALLOW_SUBMIT",
        "APP_RUNNER_ALLOW_SUBMIT",
        default="NO",
    )
    mode = _get_env_with_fallback("RUNNER_MODE", "APP_RUNNER_MODE", default="daily").lower()
    if mode not in {"daily", "interval"}:
        raise ValueError("RUNNER_MODE must be one of: daily, interval")

    time_utc = _validate_time_utc(
        _get_env_with_fallback("RUNNER_TIME_UTC", "APP_RUNNER_TIME_UTC", default="07:00")
    )
    interval_seconds = _validate_interval_seconds(
        _get_env_with_fallback(
            "RUNNER_INTERVAL_SECONDS",
            "APP_RUNNER_INTERVAL_SECONDS",
            default="60",
        )
    )
    symbol = _get_env_with_fallback("PROPR_SYMBOL", "PROPR_TEST_SYMBOL", default=DEFAULT_SYMBOL)
    require_healthy_core = _parse_yes_no(
        _get_env_with_fallback("PROPR_REQUIRE_HEALTHY_CORE", default="YES"),
        "PROPR_REQUIRE_HEALTHY_CORE",
    )

    return RunnerSettings(
        environment=environment,
        confirm=confirm,
        allow_submit=allow_submit,
        mode=mode,
        time_utc=time_utc,
        interval_seconds=interval_seconds,
        symbol=symbol,
        require_healthy_core=require_healthy_core,
        data_source=data_source_settings.data_source,
        golden_scenario=data_source_settings.golden_scenario,
    )


def load_write_test_settings_from_env() -> WriteTestSettings:
    manual_settings = load_manual_test_settings_from_env()
    environment = _get_env("PROPR_ENV") or "beta"
    return WriteTestSettings(
        environment=environment,
        write_test_confirm=manual_settings.manual_write_confirm,
        test_symbol=manual_settings.symbol,
    )


def load_live_app_cycle_settings_from_env() -> LiveAppCycleSettings:
    manual_settings = load_manual_test_settings_from_env()
    data_source_settings = load_data_source_settings_from_env()
    environment = _get_env("PROPR_ENV") or "beta"
    return LiveAppCycleSettings(
        environment=environment,
        confirm=manual_settings.manual_live_cycle_confirm,
        allow_submit=manual_settings.manual_allow_submit,
        test_symbol=manual_settings.symbol,
        require_healthy_core=manual_settings.require_healthy_core,
        data_source=data_source_settings.data_source,
        golden_scenario=data_source_settings.golden_scenario,
    )

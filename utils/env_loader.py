import os
from datetime import datetime

from dotenv import load_dotenv
from pydantic import BaseModel

from config.hyperliquid_config import HyperliquidConfig
from config.propr_config import ProprConfig


load_dotenv()

BETA_BASE_URL = "https://api.beta.propr.xyz/v1"
BETA_WS_URL = "wss://api.beta.propr.xyz/ws"
PROD_BASE_URL = "https://api.propr.xyz/v1"
PROD_WS_URL = "wss://api.propr.xyz/ws"
HYPERLIQUID_BASE_URL = "https://api.hyperliquid.xyz"
DEFAULT_SYMBOL = "BTC/USDC"
DEFAULT_LEVERAGE = 1


class WriteTestSettings(BaseModel):
    environment: str
    write_test_confirm: str
    test_symbol: str = DEFAULT_SYMBOL


class OrderTypesTestSettings(BaseModel):
    environment: str
    confirm: str
    test_symbol: str = DEFAULT_SYMBOL


class LiveAppCycleSettings(BaseModel):
    environment: str
    confirm: str
    allow_submit: str
    test_symbol: str = DEFAULT_SYMBOL
    require_healthy_core: bool = True
    data_source: str = "live"
    golden_scenario: str | None = None
    leverage: int = DEFAULT_LEVERAGE


class ManualTestSettings(BaseModel):
    symbol: str = DEFAULT_SYMBOL
    require_healthy_core: bool = True
    manual_write_confirm: str = "NO"
    manual_order_types_confirm: str = "NO"
    manual_live_cycle_confirm: str = "NO"
    manual_allow_submit: str = "NO"
    leverage: int = DEFAULT_LEVERAGE


class RunnerSettings(BaseModel):
    environment: str
    confirm: str
    allow_submit: str
    mode: str
    time_utc: str | None = None
    interval_seconds: int | None = None
    symbol: str = DEFAULT_SYMBOL
    require_healthy_core: bool = True
    data_source: str = "live"
    golden_scenario: str | None = None
    leverage: int = DEFAULT_LEVERAGE


class DataSourceSettings(BaseModel):
    data_source: str = "live"
    golden_scenario: str | None = None


class MultiMarketScanSettings(BaseModel):
    confirm: str
    symbols: list[str]
    hyperliquid_coins: list[str]
    allow_submit: bool = False
    require_healthy_core: bool = True
    leverage: int = DEFAULT_LEVERAGE



def _get_env(name: str) -> str:
    return (os.getenv(name) or "").strip()



def _parse_yes_no(value: str, field_name: str) -> bool:
    normalized = value.strip().upper()
    if normalized == "YES":
        return True
    if normalized == "NO":
        return False
    raise ValueError(f"{field_name} must be YES or NO")



def _parse_csv_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]



def _parse_leverage_or_default(value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LEVERAGE
    if parsed < 1:
        return DEFAULT_LEVERAGE
    return parsed



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



def load_hyperliquid_config_from_env() -> HyperliquidConfig:
    coin = _get_env("HYPERLIQUID_COIN")
    if not coin:
        raise ValueError("Missing HYPERLIQUID_COIN")

    lookback_raw = _get_env("HYPERLIQUID_LOOKBACK_BARS") or "200"
    try:
        lookback_bars = int(lookback_raw)
    except ValueError as exc:
        raise ValueError("HYPERLIQUID_LOOKBACK_BARS must be an integer") from exc
    if lookback_bars <= 0:
        raise ValueError("HYPERLIQUID_LOOKBACK_BARS must be greater than 0")

    return HyperliquidConfig(
        base_url=_get_env("HYPERLIQUID_BASE_URL") or HYPERLIQUID_BASE_URL,
        coin=coin,
        interval=_get_env("HYPERLIQUID_INTERVAL") or "1h",
        lookback_bars=lookback_bars,
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
    symbol = _get_env("PROPR_SYMBOL") or DEFAULT_SYMBOL
    require_healthy_core = _parse_yes_no(
        _get_env("PROPR_REQUIRE_HEALTHY_CORE") or "YES",
        "PROPR_REQUIRE_HEALTHY_CORE",
    )
    manual_write_confirm = _get_env("MANUAL_WRITE_CONFIRM") or "NO"
    manual_order_types_confirm = _get_env("MANUAL_ORDER_TYPES_CONFIRM") or "NO"
    manual_live_cycle_confirm = _get_env("MANUAL_LIVE_CYCLE_CONFIRM") or "NO"
    manual_allow_submit = _get_env("MANUAL_ALLOW_SUBMIT") or "NO"
    leverage = _parse_leverage_or_default(_get_env("PROPR_LEVERAGE") or "1")

    return ManualTestSettings(
        symbol=symbol,
        require_healthy_core=require_healthy_core,
        manual_write_confirm=manual_write_confirm,
        manual_order_types_confirm=manual_order_types_confirm,
        manual_live_cycle_confirm=manual_live_cycle_confirm,
        manual_allow_submit=manual_allow_submit,
        leverage=leverage,
    )



def load_runner_settings_from_env() -> RunnerSettings:
    data_source_settings = load_data_source_settings_from_env()
    environment = _get_env("PROPR_ENV") or "beta"
    confirm = _get_env("RUNNER_CONFIRM") or "NO"
    allow_submit = _get_env("RUNNER_ALLOW_SUBMIT") or "NO"
    mode = (_get_env("RUNNER_MODE") or "daily").lower()
    if mode not in {"daily", "interval", "manual"}:
        raise ValueError("Invalid RUNNER_MODE")

    time_utc: str | None = None
    interval_seconds: int | None = None
    if mode == "daily":
        time_utc = _validate_time_utc(_get_env("RUNNER_TIME_UTC") or "07:00")
    elif mode == "interval":
        interval_seconds = _validate_interval_seconds(_get_env("RUNNER_INTERVAL_SECONDS") or "60")

    symbol = _get_env("PROPR_SYMBOL") or DEFAULT_SYMBOL
    require_healthy_core = _parse_yes_no(
        _get_env("PROPR_REQUIRE_HEALTHY_CORE") or "YES",
        "PROPR_REQUIRE_HEALTHY_CORE",
    )
    leverage = _parse_leverage_or_default(_get_env("PROPR_LEVERAGE") or "1")

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
        leverage=leverage,
    )



def load_multi_market_scan_settings_from_env() -> MultiMarketScanSettings:
    confirm = _get_env("SCAN_CONFIRM") or "NO"
    if confirm != "YES":
        raise ValueError("Multi-market scan requires SCAN_CONFIRM=YES")

    symbols = _parse_csv_list(_get_env("SCAN_SYMBOLS"))
    hyperliquid_coins = _parse_csv_list(_get_env("SCAN_HYPERLIQUID_COINS"))
    if len(symbols) != len(hyperliquid_coins):
        raise ValueError("SCAN_SYMBOLS and SCAN_HYPERLIQUID_COINS length mismatch")

    allow_submit = _parse_yes_no(_get_env("SCAN_ALLOW_SUBMIT") or "NO", "SCAN_ALLOW_SUBMIT")
    require_healthy_core = _parse_yes_no(
        _get_env("PROPR_REQUIRE_HEALTHY_CORE") or "YES",
        "PROPR_REQUIRE_HEALTHY_CORE",
    )
    leverage = _parse_leverage_or_default(_get_env("PROPR_LEVERAGE") or "1")

    return MultiMarketScanSettings(
        confirm=confirm,
        symbols=symbols,
        hyperliquid_coins=hyperliquid_coins,
        allow_submit=allow_submit,
        require_healthy_core=require_healthy_core,
        leverage=leverage,
    )



def load_write_test_settings_from_env() -> WriteTestSettings:
    manual_settings = load_manual_test_settings_from_env()
    environment = _get_env("PROPR_ENV") or "beta"
    return WriteTestSettings(
        environment=environment,
        write_test_confirm=manual_settings.manual_write_confirm,
        test_symbol=manual_settings.symbol,
    )



def load_order_types_test_settings_from_env() -> OrderTypesTestSettings:
    manual_settings = load_manual_test_settings_from_env()
    environment = _get_env("PROPR_ENV") or "beta"
    return OrderTypesTestSettings(
        environment=environment,
        confirm=manual_settings.manual_order_types_confirm,
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
        leverage=manual_settings.leverage,
    )

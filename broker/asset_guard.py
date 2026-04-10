from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from broker.propr_client import ProprClient


class AssetGuardResult(BaseModel):
    allow_execution: bool
    reason: str | None = None
    asset: str | None = None
    desired_leverage: int = 1
    max_leverage: int | None = None
    effective_leverage: int = 1



def extract_base_asset(symbol: str) -> str:
    from utils.asset_normalizer import normalize_asset
    info = normalize_asset(symbol)
    return info.base



def _safe_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed



def get_max_leverage_for_asset(
    limits_payload: dict[str, Any], asset: str, is_hip3: bool = False,
) -> int:
    overrides = limits_payload.get("overrides")
    if isinstance(overrides, dict) and asset in overrides:
        return _safe_int(overrides.get(asset), 1)

    defaults = limits_payload.get("defaults")
    if isinstance(defaults, dict):
        if is_hip3:
            return _safe_int(defaults.get("equity", defaults.get("commodity", 1)), 1)
        return _safe_int(defaults.get("crypto", 1), 1)

    return _safe_int(limits_payload.get("defaultMax"), 1)



def ensure_leverage(
    client: ProprClient,
    account_id: str,
    asset: str,
    desired_leverage: int,
) -> None:
    import logging
    logger = logging.getLogger(__name__)
    try:
        config = client.get_margin_config(account_id, asset)
        config_id = config.get("configId")
        current_leverage = _safe_int(config.get("leverage"), 0)
        if config_id and current_leverage != desired_leverage:
            logger.info(
                "Updating margin config for %s: leverage %d -> %d",
                asset, current_leverage, desired_leverage,
            )
            client.update_margin_config(account_id, config_id, asset, desired_leverage)
    except Exception:
        logger.warning("Failed to ensure leverage for %s", asset, exc_info=True)


def evaluate_asset_execution_guard(
    client: ProprClient,
    account_id: str,
    symbol: str,
    desired_leverage: int = 1,
) -> AssetGuardResult:
    from utils.asset_normalizer import normalize_asset
    info = normalize_asset(symbol)
    asset = info.base
    margin_config_asset = info.asset

    try:
        client.get_margin_config(account_id, margin_config_asset)
    except Exception:
        return AssetGuardResult(
            allow_execution=False,
            reason="asset not tradeable",
            asset=asset,
            desired_leverage=max(desired_leverage, 1),
            max_leverage=None,
            effective_leverage=1,
        )

    try:
        limits_payload = client.get_effective_leverage_limits()
    except Exception:
        return AssetGuardResult(
            allow_execution=False,
            reason="leverage limits unavailable",
            asset=asset,
            desired_leverage=max(desired_leverage, 1),
            max_leverage=None,
            effective_leverage=1,
        )

    max_leverage = get_max_leverage_for_asset(limits_payload, asset, is_hip3=info.is_hip3)
    normalized_leverage = max(desired_leverage, 1)
    effective_leverage = min(normalized_leverage, max_leverage)

    ensure_leverage(client, account_id, margin_config_asset, effective_leverage)

    return AssetGuardResult(
        allow_execution=True,
        reason=None,
        asset=asset,
        desired_leverage=normalized_leverage,
        max_leverage=max_leverage,
        effective_leverage=effective_leverage,
    )

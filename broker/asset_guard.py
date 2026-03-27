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



def extract_base_asset(symbol: str) -> str:
    normalized = (symbol or "").strip()
    parts = normalized.split("/")
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError("symbol must be in BASE/QUOTE format")
    return parts[0].strip().upper()



def _safe_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return parsed



def get_max_leverage_for_asset(limits_payload: dict[str, Any], asset: str) -> int:
    default_max = _safe_int(limits_payload.get("defaultMax"), 1)
    overrides = limits_payload.get("overrides")
    if isinstance(overrides, dict) and asset in overrides:
        return _safe_int(overrides.get(asset), default_max)
    return default_max



def evaluate_asset_execution_guard(
    client: ProprClient,
    account_id: str,
    symbol: str,
    desired_leverage: int = 1,
) -> AssetGuardResult:
    asset = extract_base_asset(symbol)

    try:
        client.get_margin_config(account_id, asset)
    except Exception:
        return AssetGuardResult(
            allow_execution=False,
            reason="asset not tradeable",
            asset=asset,
            desired_leverage=max(desired_leverage, 1),
            max_leverage=None,
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
        )

    max_leverage = get_max_leverage_for_asset(limits_payload, asset)
    normalized_leverage = max(desired_leverage, 1)
    if normalized_leverage > max_leverage:
        return AssetGuardResult(
            allow_execution=False,
            reason="configured leverage exceeds max allowed",
            asset=asset,
            desired_leverage=normalized_leverage,
            max_leverage=max_leverage,
        )

    return AssetGuardResult(
        allow_execution=True,
        reason=None,
        asset=asset,
        desired_leverage=normalized_leverage,
        max_leverage=max_leverage,
    )

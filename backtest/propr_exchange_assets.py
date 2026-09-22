"""Public Propr exchange-assets catalog (no API key)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

EXCHANGE_ASSETS_PATH = "/exchange-assets/config/hyperliquid"
DEFAULT_TTL_SECONDS = 24 * 60 * 60

PROD_BASE = "https://api.propr.xyz/v1"
BETA_BASE = "https://api.beta.propr.xyz/v1"


@dataclass(frozen=True)
class ExchangeAssetRow:
    asset: str
    status: str
    max_order_notional_value: str | None
    maker_fee: float | None
    taker_fee: float | None
    created_at: str | None

    @property
    def is_whitelisted(self) -> bool:
        return self.status.lower() == "whitelisted"

    def fee_roundtrip_bps_from_taker(self) -> float | None:
        """Conservative round-trip: 2 * taker * 10000 (both legs taker)."""
        if self.taker_fee is None:
            return None
        return float(self.taker_fee) * 2.0 * 10_000.0

    def taker_bps(self) -> float | None:
        if self.taker_fee is None:
            return None
        return float(self.taker_fee) * 10_000.0


def resolve_propr_api_base(*, env: str | None = None, base_url: str | None = None) -> str:
    if base_url:
        return base_url.rstrip("/")
    raw_env = (env or os.getenv("PROPR_ENV") or "beta").strip().lower()
    if raw_env == "prod":
        return PROD_BASE
    return BETA_BASE


def exchange_assets_url(*, env: str | None = None, base_url: str | None = None) -> str:
    base = resolve_propr_api_base(env=env, base_url=base_url)
    return f"{base}{EXCHANGE_ASSETS_PATH}"


def _parse_fee(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_exchange_assets_payload(payload: dict[str, Any] | list[Any]) -> list[ExchangeAssetRow]:
    if isinstance(payload, list):
        rows_raw = payload
    elif isinstance(payload, dict):
        data = payload.get("data", payload)
        if isinstance(data, list):
            rows_raw = data
        else:
            raise ValueError("exchange-assets payload missing list under 'data'")
    else:
        raise ValueError("exchange-assets payload must be dict or list")

    out: list[ExchangeAssetRow] = []
    for item in rows_raw:
        if not isinstance(item, dict):
            continue
        asset = str(item.get("asset") or "").strip()
        if not asset:
            continue
        fee = item.get("feeSchedule") or {}
        if not isinstance(fee, dict):
            fee = {}
        out.append(
            ExchangeAssetRow(
                asset=asset,
                status=str(item.get("status") or "").strip().lower(),
                max_order_notional_value=(
                    str(item["maxOrderNotionalValue"])
                    if item.get("maxOrderNotionalValue") is not None
                    else None
                ),
                maker_fee=_parse_fee(fee.get("maker")),
                taker_fee=_parse_fee(fee.get("taker")),
                created_at=str(item["createdAt"]) if item.get("createdAt") is not None else None,
            )
        )
    return out


def load_exchange_assets_from_file(path: Path) -> list[ExchangeAssetRow]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "payload" in raw:
        return parse_exchange_assets_payload(raw["payload"])
    return parse_exchange_assets_payload(raw)


def fetch_exchange_assets(
    *,
    env: str | None = None,
    base_url: str | None = None,
    cache_path: Path | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    refresh: bool = False,
    timeout_s: float = 30.0,
    session: requests.Session | None = None,
) -> tuple[list[ExchangeAssetRow], dict[str, Any]]:
    """Fetch (or load cached) Hyperliquid exchange-asset config.

    Returns (rows, meta) where meta includes url, fetched_at_utc, from_cache.
    """
    url = exchange_assets_url(env=env, base_url=base_url)
    meta: dict[str, Any] = {
        "url": url,
        "env": (env or os.getenv("PROPR_ENV") or "beta").strip().lower(),
        "from_cache": False,
        "fetched_at_utc": None,
    }

    if cache_path is not None and cache_path.exists() and not refresh:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            fetched_at = cached.get("fetched_at_utc")
            if fetched_at:
                ts = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
                if age <= ttl_seconds:
                    rows = parse_exchange_assets_payload(cached.get("payload", cached))
                    meta["from_cache"] = True
                    meta["fetched_at_utc"] = fetched_at
                    meta["n_assets"] = len(rows)
                    meta["n_whitelisted"] = sum(1 for r in rows if r.is_whitelisted)
                    return rows, meta
        except Exception as exc:
            logger.warning("Ignoring bad exchange-assets cache %s: %s", cache_path, exc)

    sess = session or requests.Session()
    resp = sess.get(url, timeout=timeout_s)
    resp.raise_for_status()
    payload = resp.json()
    rows = parse_exchange_assets_payload(payload)
    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["fetched_at_utc"] = fetched_at
    meta["from_cache"] = False
    meta["n_assets"] = len(rows)
    meta["n_whitelisted"] = sum(1 for r in rows if r.is_whitelisted)

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "fetched_at_utc": fetched_at,
                    "url": url,
                    "payload": payload,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    return rows, meta


def whitelisted_assets(rows: list[ExchangeAssetRow]) -> list[ExchangeAssetRow]:
    return [r for r in rows if r.is_whitelisted]

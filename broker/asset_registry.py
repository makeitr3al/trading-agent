from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from pydantic import BaseModel

if TYPE_CHECKING:
    from utils.asset_normalizer import AssetInfo

logger = logging.getLogger(__name__)

HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_CACHE_PATH = Path("artifacts/asset_registry.json")
DEFAULT_TTL_HOURS = 24

KNOWN_HIP3_NAMES: set[str] = {"AAPL", "TSLA", "NVDA", "GOLD", "SILVER", "CL"}

# Wagyu-wrapped crypto tokens that look like HIP-3 but are not stocks/commodities.
# These should NOT be treated as HIP-3 tradeable assets on Propr.
_WAGYU_CRYPTO_EXCLUSIONS: set[str] = {"XMR1", "TAO1"}


class AssetEntry(BaseModel):
    name: str
    propr_asset: str
    asset_type: str
    base: str
    quote: str = "USDC"
    sz_decimals: int
    max_leverage: int | None = None


class AssetRegistryCache(BaseModel):
    fetched_at: str
    assets: list[dict[str, Any]]


def _fetch_perps_meta() -> dict[str, Any]:
    response = requests.post(
        HYPERLIQUID_INFO_URL,
        json={"type": "meta"},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _fetch_perps_meta_for_dex(dex: str) -> dict[str, Any]:
    response = requests.post(
        HYPERLIQUID_INFO_URL,
        json={"type": "meta", "dex": dex},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _fetch_perp_dexs() -> list[dict[str, Any]]:
    response = requests.post(
        HYPERLIQUID_INFO_URL,
        json={"type": "perpDexs"},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _fetch_all_mids(dex: str | None = None) -> dict[str, str]:
    payload: dict[str, Any] = {"type": "allMids"}
    if dex is not None:
        payload["dex"] = dex
    response = requests.post(
        HYPERLIQUID_INFO_URL,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    raw = response.json()
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, str):
            out[k] = v
    return out


def _fetch_spot_meta() -> dict[str, Any]:
    response = requests.post(
        HYPERLIQUID_INFO_URL,
        json={"type": "spotMeta"},
        headers={"Content-Type": "application/json"},
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def _parse_crypto_assets(perps_meta: dict[str, Any]) -> list[AssetEntry]:
    universe = perps_meta.get("universe")
    if not isinstance(universe, list):
        return []

    assets: list[AssetEntry] = []
    for item in universe:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        if item.get("isDelisted"):
            continue

        sz_decimals = item.get("szDecimals")
        if sz_decimals is None:
            continue

        max_leverage = item.get("maxLeverage")
        if name.lower().startswith("xyz:"):
            base = name.split(":", 1)[1].strip().upper()
            assets.append(AssetEntry(
                name=base or name,
                propr_asset=name,
                asset_type="builder_perp",
                base=base or name,
                quote="USDC",
                sz_decimals=int(sz_decimals),
                max_leverage=int(max_leverage) if max_leverage is not None else None,
            ))
        else:
            assets.append(AssetEntry(
                name=name,
                propr_asset=name,
                asset_type="crypto",
                base=name,
                quote="USDC",
                sz_decimals=int(sz_decimals),
                max_leverage=int(max_leverage) if max_leverage is not None else None,
            ))
    return assets


def _parse_hip3_assets(spot_meta: dict[str, Any]) -> list[AssetEntry]:
    tokens = spot_meta.get("tokens")
    if not isinstance(tokens, list):
        tokens = []

    # Build lookup from spotMeta tokens for szDecimals
    token_lookup: dict[str, dict[str, Any]] = {}
    for token in tokens:
        if not isinstance(token, dict):
            continue
        name = str(token.get("name", "")).strip().upper()
        if name:
            token_lookup[name] = token

    assets: list[AssetEntry] = []
    seen: set[str] = set()

    # 1. Always include known HIP-3 assets from Propr docs
    for name in sorted(KNOWN_HIP3_NAMES):
        upper_name = name.upper()
        seen.add(upper_name)
        token_data = token_lookup.get(upper_name, {})
        sz_decimals = token_data.get("szDecimals", 2)

        assets.append(AssetEntry(
            name=upper_name,
            propr_asset=f"xyz:{upper_name}",
            asset_type="hip3",
            base=upper_name,
            quote="USDC",
            sz_decimals=int(sz_decimals),
            max_leverage=None,
        ))

    # 2. Discover additional Wagyu assets (stocks/commodities only)
    for token in tokens:
        if not isinstance(token, dict):
            continue
        name = str(token.get("name", "")).strip().upper()
        if not name or name in seen:
            continue

        full_name = str(token.get("fullName") or "")
        if "wagyu" not in full_name.lower():
            continue

        if name in _WAGYU_CRYPTO_EXCLUSIONS:
            continue

        seen.add(name)
        sz_decimals = token.get("szDecimals", 2)
        assets.append(AssetEntry(
            name=name,
            propr_asset=f"xyz:{name}",
            asset_type="hip3",
            base=name,
            quote="USDC",
            sz_decimals=int(sz_decimals),
            max_leverage=None,
        ))

    return assets


class AssetRegistry:
    def __init__(
        self,
        cache_path: Path | str | None = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ) -> None:
        self._cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
        self._ttl_hours = ttl_hours
        self._assets: list[AssetEntry] = []
        self._fetched_at: datetime | None = None
        self._loaded = False

    def ensure_fresh(self) -> None:
        if self._loaded and self._fetched_at is not None:
            age_hours = (datetime.now(timezone.utc) - self._fetched_at).total_seconds() / 3600
            if age_hours < self._ttl_hours:
                return

        if self._try_load_cache():
            return

        self.refresh()

    def refresh(self) -> None:
        logger.info("Refreshing asset registry from Hyperliquid...")
        perps: list[AssetEntry] = []
        hip3: list[AssetEntry] = []
        extras: list[AssetEntry] = []

        try:
            # The default `meta` only returns the first perp dex. Use `perpDexs` to discover
            # additional perp dexs (e.g. `xyz`) and fetch each dex's `meta` universe.
            perps_meta = _fetch_perps_meta()
            perps = _parse_crypto_assets(perps_meta)

            for dex in sorted({str(d.get("name") or "").strip() for d in _fetch_perp_dexs()} - {""}):
                try:
                    dex_meta = _fetch_perps_meta_for_dex(dex)
                    perps.extend(_parse_crypto_assets(dex_meta))
                except Exception as exc:
                    logger.warning("Failed to fetch perps meta for dex=%s: %s", dex, exc)
        except Exception as exc:
            logger.warning("Failed to fetch perps meta: %s", exc)

        # Optional: `allMids` may contain backend coins not present in meta universes.
        # Keep them in a separate bucket; they are not guaranteed to support candles/trading.
        try:
            mids = _fetch_all_mids()
            known = {a.propr_asset.upper() for a in perps}
            for coin in sorted(set(mids.keys()) - known):
                # Skip empty and internal keys.
                if not coin or coin.startswith("@"):
                    continue
                extras.append(AssetEntry(
                    name=coin,
                    propr_asset=coin,
                    asset_type="backend_coin",
                    base=coin,
                    quote="USDC",
                    sz_decimals=0,
                    max_leverage=None,
                ))
        except Exception as exc:
            logger.debug("Failed to fetch allMids (optional): %s", exc)

        try:
            spot_meta = _fetch_spot_meta()
            hip3 = _parse_hip3_assets(spot_meta)
        except Exception as exc:
            logger.warning("Failed to fetch spot meta: %s", exc)

        # Exclude HIP-3 names that clash with perp names
        perp_names = {a.name.upper() for a in perps}
        hip3 = [a for a in hip3 if a.name.upper() not in perp_names]

        self._assets = perps + hip3 + extras
        self._fetched_at = datetime.now(timezone.utc)
        self._loaded = True

        self._save_cache()
        logger.info(
            "Asset registry refreshed: %d perps, %d hip3, %d extras",
            len(perps), len(hip3), len(extras),
        )

    def get(self, name: str) -> AssetEntry | None:
        self.ensure_fresh()
        normalized = name.strip()
        upper = normalized.upper()
        for asset in self._assets:
            if asset.name.upper() == upper:
                return asset
            if asset.propr_asset.upper() == upper:
                return asset
            if asset.base.upper() == upper:
                return asset
        return None

    def list_crypto(self) -> list[AssetEntry]:
        self.ensure_fresh()
        return [a for a in self._assets if a.asset_type == "crypto"]

    def list_perps(self) -> list[AssetEntry]:
        self.ensure_fresh()
        return [a for a in self._assets if a.asset_type in {"crypto", "builder_perp"}]

    def list_builder_perps(self) -> list[AssetEntry]:
        self.ensure_fresh()
        return [a for a in self._assets if a.asset_type == "builder_perp"]

    def list_hip3(self) -> list[AssetEntry]:
        self.ensure_fresh()
        return [a for a in self._assets if a.asset_type == "hip3"]

    def list_all(self) -> list[AssetEntry]:
        self.ensure_fresh()
        return list(self._assets)

    def is_available(self, name: str) -> bool:
        return self.get(name) is not None

    def validate_perp_coin_for_data_fetch(self, coin: str) -> None:
        """Raise if ``coin`` is not a known Hyperliquid perp coin (across dexs)."""
        self.ensure_fresh()
        perp_names = {a.propr_asset.upper() for a in self.list_perps()}
        if not perp_names:
            logger.warning("Skipping Hyperliquid perp coin validation: empty perp universe (offline?)")
            return
        upper = coin.strip().upper()
        if upper in perp_names:
            return
        sample = ", ".join(sorted(perp_names)[:16])
        raise ValueError(
            f"Unknown Hyperliquid perp {coin!r}: not in meta universe. "
            f"Use a listed perp coin (examples: {sample})."
        )

    def validate_scan_asset_for_hyperliquid_fetch(self, asset: AssetInfo) -> None:
        """Preflight for multi-market scan: crypto perps vs HIP-3 / builder assets."""
        self.ensure_fresh()
        if asset.is_hip3:
            entry = self.get(asset.asset)
            if entry is not None and entry.asset_type in {"hip3", "builder_perp"}:
                return
            # Fallback: some `xyz:` coins may be fetchable even if discovery is incomplete.
            logger.warning("Unknown `xyz:` market %r; allowing fetch (may fail at /info).", asset.asset)
            return

        self.validate_perp_coin_for_data_fetch(asset.coin or asset.base)

    def _try_load_cache(self) -> bool:
        if not self._cache_path.exists():
            return False

        try:
            raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
            fetched_at_str = raw.get("fetched_at", "")
            fetched_at = datetime.fromisoformat(fetched_at_str)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)

            age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
            if age_hours >= self._ttl_hours:
                return False

            assets_raw = raw.get("assets", [])
            self._assets = [AssetEntry(**entry) for entry in assets_raw]
            self._fetched_at = fetched_at
            self._loaded = True
            return True
        except Exception as exc:
            logger.warning("Failed to load asset registry cache: %s", exc)
            return False

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "fetched_at": self._fetched_at.isoformat() if self._fetched_at else "",
                "assets": [a.model_dump() for a in self._assets],
            }
            self._cache_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save asset registry cache: %s", exc)

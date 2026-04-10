from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AssetInfo:
    asset: str
    base: str
    quote: str
    coin: str | None
    is_hip3: bool


def normalize_asset(raw: str) -> AssetInfo:
    trimmed = (raw or "").strip()
    if not trimmed:
        raise ValueError("asset must not be empty")

    # Legacy SCAN_MARKETS format: "BTC/USDC:BTC"
    if "/" in trimmed and ":" in trimmed:
        slash_pos = trimmed.index("/")
        colon_pos = trimmed.index(":")
        if slash_pos < colon_pos:
            pair_part = trimmed[:colon_pos].strip()
            base = pair_part.split("/")[0].strip().upper()
            logger.warning(
                "Deprecated format '%s' — use '%s' instead", trimmed, base,
            )
            return AssetInfo(
                asset=base, base=base, quote="USDC", coin=base, is_hip3=False,
            )

    # HIP-3 format: "xyz:AAPL"
    if trimmed.lower().startswith("xyz:"):
        ticker = trimmed[4:].strip().upper()
        if not ticker:
            raise ValueError("HIP-3 asset must have a ticker after 'xyz:'")
        return AssetInfo(
            asset=f"xyz:{ticker}",
            base=ticker,
            quote="USDC",
            coin=None,
            is_hip3=True,
        )

    # Legacy pair format: "BTC/USDC"
    if "/" in trimmed:
        parts = trimmed.split("/")
        base = parts[0].strip().upper()
        if not base:
            raise ValueError("symbol pair must have a base asset")
        logger.warning(
            "Deprecated format '%s' — use '%s' instead", trimmed, base,
        )
        return AssetInfo(
            asset=base, base=base, quote="USDC", coin=base, is_hip3=False,
        )

    # Simple ticker: "BTC"
    upper = trimmed.upper()
    return AssetInfo(
        asset=upper, base=upper, quote="USDC", coin=upper, is_hip3=False,
    )


def parse_market_list(raw_csv: str) -> list[AssetInfo]:
    entries = [item.strip() for item in raw_csv.split(",") if item.strip()]
    if not entries:
        raise ValueError("market list must not be empty")
    return [normalize_asset(entry) for entry in entries]

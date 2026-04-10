from __future__ import annotations

from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Callable

import requests

from models.symbol_spec import SymbolSpec


HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"

# TODO: Later add caching and a Propr-aware metadata source if Propr exposes
# richer asset precision rules directly.
# TODO: Later add min-notional or exchange-specific quantity floors once we
# have a documented primary source for them.



def _to_decimal(value: float | int | str | Decimal) -> Decimal:
    return Decimal(str(value))



def _quantum_from_decimals(decimals: int) -> Decimal:
    return Decimal("1").scaleb(-decimals)



def split_symbol(symbol: str) -> tuple[str, str]:
    normalized = (symbol or "").strip()
    base, sep, quote = normalized.partition("/")
    if not sep or not base.strip() or not quote.strip():
        raise ValueError("symbol must be in BASE/QUOTE format")
    return base.strip().upper(), quote.strip().upper()


def resolve_symbol_pair(asset_or_pair: str) -> tuple[str, str]:
    normalized = (asset_or_pair or "").strip()
    if not normalized:
        raise ValueError("symbol must not be empty")
    if "/" in normalized:
        return split_symbol(normalized)
    if normalized.lower().startswith("xyz:"):
        ticker = normalized[4:].strip().upper()
        return ticker, "USDC"
    return normalized.upper(), "USDC"



def round_quantity_to_symbol_spec(value: float | int | str | Decimal, symbol_spec: SymbolSpec) -> Decimal:
    decimal_value = _to_decimal(value)
    quantum = _quantum_from_decimals(symbol_spec.quantity_decimals)
    return decimal_value.quantize(quantum, rounding=ROUND_DOWN)



def round_price_to_symbol_spec(value: float | int | str | Decimal, symbol_spec: SymbolSpec) -> Decimal:
    decimal_value = _to_decimal(value)
    if symbol_spec.price_decimals is None:
        return decimal_value
    quantum = _quantum_from_decimals(symbol_spec.price_decimals)
    return decimal_value.quantize(quantum, rounding=ROUND_HALF_UP)


class HyperliquidSymbolService:
    def __init__(
        self,
        fetch_meta: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._fetch_meta = fetch_meta or self._fetch_meta_from_http

    def get_symbol_spec(self, symbol: str) -> SymbolSpec:
        base, quote = resolve_symbol_pair(symbol)
        payload = self._fetch_meta()
        universe = payload.get("universe")
        if not isinstance(universe, list):
            raise ValueError("Hyperliquid meta payload is missing universe")

        for asset_payload in universe:
            if not isinstance(asset_payload, dict):
                continue
            if str(asset_payload.get("name", "")).upper() != base:
                continue

            quantity_decimals = asset_payload.get("szDecimals")
            max_leverage = asset_payload.get("maxLeverage")
            price_decimals = None
            for key in ["priceDecimals", "pxDecimals", "price_precision", "pricePrecision"]:
                if asset_payload.get(key) is not None:
                    price_decimals = int(asset_payload[key])
                    break
            if quantity_decimals is None:
                raise ValueError(f"Hyperliquid meta for {base} is missing szDecimals")

            return SymbolSpec(
                symbol=f"{base}/{quote}",
                asset=base,
                base=base,
                quote=quote,
                quantity_decimals=int(quantity_decimals),
                price_decimals=price_decimals,
                max_leverage=int(max_leverage) if max_leverage is not None else None,
                source_name="hyperliquid_meta",
            )

        raise ValueError(f"Unsupported symbol base asset: {base}")

    @staticmethod
    def _fetch_meta_from_http() -> dict[str, Any]:
        response = requests.post(
            HYPERLIQUID_INFO_URL,
            json={"type": "meta"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

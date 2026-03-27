from decimal import Decimal
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from broker.symbol_service import (
    HyperliquidSymbolService,
    round_price_to_symbol_spec,
    round_quantity_to_symbol_spec,
    split_symbol,
)
from models.symbol_spec import SymbolSpec



def test_split_symbol_reads_base_and_quote() -> None:
    base, quote = split_symbol("btc/usdc")

    assert base == "BTC"
    assert quote == "USDC"



def test_quantity_rounding_helper_rounds_down_correctly() -> None:
    spec = SymbolSpec(
        symbol="BTC/USDC",
        asset="BTC",
        base="BTC",
        quote="USDC",
        quantity_decimals=3,
        price_decimals=None,
        max_leverage=5,
        source_name="test",
    )

    rounded = round_quantity_to_symbol_spec("1.2349", spec)

    assert rounded == Decimal("1.234")



def test_price_rounding_helper_respects_configured_price_decimals() -> None:
    spec = SymbolSpec(
        symbol="BTC/USDC",
        asset="BTC",
        base="BTC",
        quote="USDC",
        quantity_decimals=3,
        price_decimals=2,
        max_leverage=5,
        source_name="test",
    )

    rounded = round_price_to_symbol_spec("123.456", spec)

    assert rounded == Decimal("123.46")



def test_price_rounding_helper_leaves_value_unchanged_when_price_precision_unknown() -> None:
    spec = SymbolSpec(
        symbol="BTC/USDC",
        asset="BTC",
        base="BTC",
        quote="USDC",
        quantity_decimals=3,
        price_decimals=None,
        max_leverage=5,
        source_name="test",
    )

    rounded = round_price_to_symbol_spec("123.456", spec)

    assert rounded == Decimal("123.456")



def test_hyperliquid_symbol_service_builds_symbol_spec_from_meta() -> None:
    service = HyperliquidSymbolService(
        fetch_meta=lambda: {
            "universe": [
                {"name": "BTC", "szDecimals": 5, "maxLeverage": 50, "priceDecimals": 2},
                {"name": "ETH", "szDecimals": 4, "maxLeverage": 50},
            ]
        }
    )

    spec = service.get_symbol_spec("BTC/USDC")

    assert spec.symbol == "BTC/USDC"
    assert spec.asset == "BTC"
    assert spec.quantity_decimals == 5
    assert spec.price_decimals == 2
    assert spec.max_leverage == 50
    assert spec.source_name == "hyperliquid_meta"



def test_symbol_spec_parsing_still_works_when_price_precision_cannot_be_derived() -> None:
    service = HyperliquidSymbolService(
        fetch_meta=lambda: {
            "universe": [
                {"name": "BTC", "szDecimals": 5, "maxLeverage": 50},
            ]
        }
    )

    spec = service.get_symbol_spec("BTC/USDC")

    assert spec.price_decimals is None
    assert spec.quantity_decimals == 5



def test_hyperliquid_symbol_service_raises_for_unsupported_asset() -> None:
    service = HyperliquidSymbolService(fetch_meta=lambda: {"universe": [{"name": "BTC", "szDecimals": 5}]})

    with pytest.raises(ValueError, match="Unsupported symbol base asset: ETH"):
        service.get_symbol_spec("ETH/USDC")



def test_hyperliquid_symbol_service_raises_when_universe_missing() -> None:
    service = HyperliquidSymbolService(fetch_meta=lambda: {})

    with pytest.raises(ValueError, match="missing universe"):
        service.get_symbol_spec("BTC/USDC")

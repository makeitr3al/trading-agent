from __future__ import annotations

from utils.asset_normalizer import hyperliquid_candle_coin, normalize_asset


def test_hyperliquid_candle_coin_uses_dex_qualified_name_for_hip3() -> None:
    info = normalize_asset("xyz:AAPL")
    assert info.is_hip3 is True
    assert hyperliquid_candle_coin(info) == "xyz:AAPL"


def test_hyperliquid_candle_coin_uses_perp_name_for_crypto() -> None:
    info = normalize_asset("BTC")
    assert hyperliquid_candle_coin(info) == "BTC"


def test_hyperliquid_candle_coin_legacy_pair() -> None:
    info = normalize_asset("ETH/USDC")
    assert hyperliquid_candle_coin(info) == "ETH"

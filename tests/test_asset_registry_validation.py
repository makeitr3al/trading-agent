from __future__ import annotations

import pytest

from broker.asset_registry import AssetEntry, AssetRegistry


def test_validate_perp_coin_for_data_fetch_accepts_listed_coin(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = AssetRegistry(cache_path="__no_such_cache_path__")
    fake = [
        AssetEntry(
            name="BTC",
            propr_asset="BTC",
            asset_type="crypto",
            base="BTC",
            sz_decimals=5,
            max_leverage=40,
        ),
    ]
    monkeypatch.setattr(reg, "list_perps", lambda: fake)
    monkeypatch.setattr(reg, "ensure_fresh", lambda: None)
    reg.validate_perp_coin_for_data_fetch("btc")


def test_validate_scan_asset_accepts_hip3_when_registry_lists_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils.asset_normalizer import normalize_asset

    reg = AssetRegistry(cache_path="__no_such_cache_path__")
    hip = [
        AssetEntry(
            name="AAPL",
            propr_asset="xyz:AAPL",
            asset_type="hip3",
            base="AAPL",
            quote="USDC",
            sz_decimals=2,
            max_leverage=4,
        ),
    ]
    monkeypatch.setattr(reg, "ensure_fresh", lambda: None)
    monkeypatch.setattr(reg, "get", lambda name: hip[0] if str(name).upper() == "XYZ:AAPL" else None)
    reg.validate_scan_asset_for_hyperliquid_fetch(normalize_asset("xyz:AAPL"))


def test_validate_scan_asset_rejects_unknown_hip3(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils.asset_normalizer import normalize_asset

    reg = AssetRegistry(cache_path="__no_such_cache_path__")
    monkeypatch.setattr(reg, "ensure_fresh", lambda: None)
    monkeypatch.setattr(reg, "get", lambda name: None)
    # Unknown `xyz:` markets are allowed (warning) so scans can proceed; fetch may still fail later.
    reg.validate_scan_asset_for_hyperliquid_fetch(normalize_asset("xyz:ZZZZ"))


def test_validate_scan_asset_accepts_builder_perp_coin(monkeypatch: pytest.MonkeyPatch) -> None:
    from utils.asset_normalizer import normalize_asset

    reg = AssetRegistry(cache_path="__no_such_cache_path__")
    monkeypatch.setattr(reg, "ensure_fresh", lambda: None)
    builder = AssetEntry(
        name="EUR",
        propr_asset="xyz:EUR",
        asset_type="builder_perp",
        base="EUR",
        quote="USDC",
        sz_decimals=2,
        max_leverage=10,
    )
    monkeypatch.setattr(reg, "get", lambda name: builder if str(name).upper() == "XYZ:EUR" else None)

    reg.validate_scan_asset_for_hyperliquid_fetch(normalize_asset("xyz:EUR"))


def test_validate_perp_coin_for_data_fetch_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = AssetRegistry(cache_path="__no_such_cache_path__")
    fake = [
        AssetEntry(
            name="BTC",
            propr_asset="BTC",
            asset_type="crypto",
            base="BTC",
            sz_decimals=5,
            max_leverage=40,
        ),
    ]
    monkeypatch.setattr(reg, "list_perps", lambda: fake)
    monkeypatch.setattr(reg, "ensure_fresh", lambda: None)
    with pytest.raises(ValueError, match="Unknown Hyperliquid perp"):
        reg.validate_perp_coin_for_data_fetch("EUR")

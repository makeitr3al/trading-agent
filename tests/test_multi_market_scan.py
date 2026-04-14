from __future__ import annotations

import builtins
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.hyperliquid_config import HyperliquidConfig
from config.strategy_config import StrategyConfig
from data.providers.base import DataBatch
from models.candle import Candle
from scripts import multi_market_scan as multi_market_scan_module
from scripts.multi_market_scan import (
    _best_signal_strength,
    _maybe_upgrade_to_hip3_market,
    _select_execution_candidates,
)
from utils.env_loader import DataSourceSettings, MultiMarketScanSettings


def _make_signal(is_valid: bool, strength: float | None):
    return SimpleNamespace(is_valid=is_valid, signal_strength=strength)


def _make_result(trend_valid: bool, trend_strength: float | None, counter_valid: bool, counter_strength: float | None):
    strategy_result = SimpleNamespace(
        trend_signal=_make_signal(trend_valid, trend_strength),
        countertrend_signal=_make_signal(counter_valid, counter_strength),
    )
    return SimpleNamespace(strategy_result=strategy_result)


def test_best_signal_strength_returns_max_valid_strength() -> None:
    result = _make_result(True, 0.35, True, 0.9)

    assert _best_signal_strength(result) == 0.9


def test_select_execution_candidates_keeps_all_when_slots_are_sufficient() -> None:
    candidates = [
        {"symbol": "BTC/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.2},
        {"symbol": "ETH/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.8},
    ]

    selected = _select_execution_candidates(candidates, available_slots=2)

    assert [item["symbol"] for item in selected] == ["BTC/USDC", "ETH/USDC"]


def test_select_execution_candidates_uses_strength_only_when_slots_are_limited() -> None:
    candidates = [
        {"symbol": "BTC/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.2},
        {"symbol": "ETH/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.8},
        {"symbol": "SOL/USDC", "pending_order_present": True, "skipped_reason": None, "best_signal_strength": 0.5},
    ]

    selected = _select_execution_candidates(candidates, available_slots=2)

    assert [item["symbol"] for item in selected] == ["ETH/USDC", "SOL/USDC"]


def test_maybe_upgrade_to_hip3_market_upgrades_bare_ticker_when_registry_has_hip3() -> None:
    class FakeRegistry:
        def is_available(self, name: str) -> bool:
            return name.upper() == "XYZ:EUR"

    assert _maybe_upgrade_to_hip3_market("EUR", FakeRegistry()) == "xyz:EUR"


def test_maybe_upgrade_to_hip3_market_keeps_bare_ticker_when_not_hip3() -> None:
    class FakeRegistry:
        def is_available(self, name: str) -> bool:
            return False

    assert _maybe_upgrade_to_hip3_market("EUR", FakeRegistry()) == "EUR"


def test_main_scans_remaining_markets_after_hyperliquid_preflight_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid HL coin for one market must not abort the whole multi-market scan."""

    def _fake_propr_config() -> SimpleNamespace:
        return SimpleNamespace(environment="beta")

    def _fake_scan_settings() -> MultiMarketScanSettings:
        return MultiMarketScanSettings(
            confirm="YES",
            assets=["EUR", "BTC"],
            allow_submit=False,
            journal_path="",
        )

    class _FakeRegistry:
        def __init__(self, *_a: object, **_k: object) -> None:
            pass

        def is_available(self, _name: str) -> bool:
            return False

        def validate_scan_asset_for_hyperliquid_fetch(self, asset_info: SimpleNamespace) -> None:
            if asset_info.base == "EUR":
                raise ValueError("Unknown Hyperliquid perp 'EUR'")

    def _fake_build_batch(*_a: object, **_k: object) -> tuple[DataBatch, StrategyConfig, float]:
        c = Candle(
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            open=1.0,
            high=1.0,
            low=1.0,
            close=1.0,
        )
        batch = DataBatch(candles=[c], source_name="stub", config=StrategyConfig())
        return batch, StrategyConfig(), 0.0

    def _fake_run_app_cycle(**_kwargs: object) -> SimpleNamespace:
        decision = SimpleNamespace(action=SimpleNamespace(value="NO_ACTION"))
        strategy_result = SimpleNamespace(
            decision=decision,
            selected_signal_type=None,
            trend_signal=SimpleNamespace(is_valid=False),
            countertrend_signal=SimpleNamespace(is_valid=False),
        )
        return SimpleNamespace(
            strategy_result=strategy_result,
            post_cycle_state=None,
            skipped_reason=None,
            health_guard_result=None,
            risk_guard_result=None,
            journal_entries=[],
            journal_path=None,
        )

    scan_lines: list[str] = []
    real_print = builtins.print

    def _capture_print(*args: object, **kwargs: object) -> None:
        if args:
            scan_lines.append(str(args[0]))
        return real_print(*args, **kwargs)

    monkeypatch.setattr(multi_market_scan_module, "load_propr_config_from_env", _fake_propr_config)
    monkeypatch.setattr(multi_market_scan_module, "load_data_source_settings_from_env", lambda: DataSourceSettings(data_source="live"))
    monkeypatch.setattr(multi_market_scan_module, "load_multi_market_scan_settings_from_env", _fake_scan_settings)
    monkeypatch.setattr(multi_market_scan_module, "ProprClient", lambda *_a, **_k: object())
    monkeypatch.setattr(multi_market_scan_module, "ProprOrderService", lambda *_a, **_k: object())
    monkeypatch.setattr(multi_market_scan_module, "HyperliquidSymbolService", lambda: object())
    monkeypatch.setattr(multi_market_scan_module, "AssetRegistry", _FakeRegistry)
    monkeypatch.setattr(multi_market_scan_module, "load_hyperliquid_config_from_env", lambda: HyperliquidConfig(coin="BTC"))
    monkeypatch.setattr(multi_market_scan_module, "_build_data_batch_and_config", _fake_build_batch)
    monkeypatch.setattr(multi_market_scan_module, "run_app_cycle", _fake_run_app_cycle)
    monkeypatch.setattr(multi_market_scan_module, "_persist_live_status", lambda *_a, **_k: None)
    monkeypatch.setattr(builtins, "print", _capture_print)

    multi_market_scan_module.main()

    assert any("Scanning asset=EUR coin=EUR" in line for line in scan_lines)
    assert any("Scanning asset=BTC coin=BTC" in line for line in scan_lines)
    assert any("total_markets_scanned: 2" in line for line in scan_lines)
    assert not any(line.startswith("Multi-market scan failed:") for line in scan_lines)

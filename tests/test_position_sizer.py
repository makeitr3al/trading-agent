from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models.symbol_spec import SymbolSpec
from strategy.position_sizer import calculate_position_size



def test_quantity_is_rounded_down_to_quantity_decimals() -> None:
    symbol_spec = SymbolSpec(
        symbol="BTC/USDC",
        asset="BTC",
        base="BTC",
        quote="USDC",
        quantity_decimals=3,
        price_decimals=None,
        max_leverage=5,
        source_name="test",
    )

    result = calculate_position_size(
        entry=107.0,
        stop_loss=100.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
        desired_leverage=1,
        symbol_spec=symbol_spec,
    )

    assert result.position_size == 14.285



def test_leverage_cap_still_applies_before_and_with_rounding() -> None:
    symbol_spec = SymbolSpec(
        symbol="BTC/USDC",
        asset="BTC",
        base="BTC",
        quote="USDC",
        quantity_decimals=3,
        price_decimals=None,
        max_leverage=5,
        source_name="test",
    )

    result = calculate_position_size(
        entry=1000.0,
        stop_loss=900.0,
        account_balance=100.0,
        risk_per_trade_pct=1.0,
        desired_leverage=1,
        symbol_spec=symbol_spec,
    )

    assert result.position_size == 0.1
    assert result.was_margin_capped is True



def test_fallback_works_when_no_symbol_spec_exists() -> None:
    result = calculate_position_size(
        entry=110.0,
        stop_loss=100.0,
        account_balance=10000.0,
        risk_per_trade_pct=0.01,
        desired_leverage=1,
        symbol_spec=None,
    )

    assert result.position_size == 10.0
    assert result.was_margin_capped is False
    assert result.applied_leverage == 1



def test_invalid_leverage_falls_back_to_one() -> None:
    result = calculate_position_size(
        entry=100.0,
        stop_loss=90.0,
        account_balance=1000.0,
        risk_per_trade_pct=0.01,
        desired_leverage=0,
        symbol_spec=None,
    )

    assert result.applied_leverage == 1
    assert result.position_size == 1.0

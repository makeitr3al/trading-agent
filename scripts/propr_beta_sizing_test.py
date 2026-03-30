from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from broker.challenge_service import get_active_challenge_context
from broker.health_guard import fetch_and_check_core_service_health
from broker.order_service import (
    ProprOrderService,
    apply_symbol_spec_to_order,
    build_order_submission_preview,
    extract_order_id_from_submit_response,
)
from broker.propr_client import ProprClient
from broker.symbol_service import HyperliquidSymbolService
from models.order import Order, OrderType
from strategy.position_sizer import calculate_position_size, evaluate_position_size_execution
from utils.env_loader import load_propr_config_from_env


ORDER_TYPE_CHOICES = {
    "buy_limit": OrderType.BUY_LIMIT,
    "sell_limit": OrderType.SELL_LIMIT,
    "buy_stop": OrderType.BUY_STOP,
    "sell_stop": OrderType.SELL_STOP,
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Submit a real beta order to verify 1R position sizing.")
    parser.add_argument("--confirm", required=True, help="Safety confirmation. Must be YES.")
    parser.add_argument("--symbol", required=True, help="Trading symbol in BASE/QUOTE format, e.g. BTC/USDC")
    parser.add_argument("--order-type", required=True, choices=sorted(ORDER_TYPE_CHOICES.keys()))
    parser.add_argument("--entry", required=True, type=float)
    parser.add_argument("--stop-loss", required=True, type=float)
    parser.add_argument("--take-profit", type=float)
    parser.add_argument("--account-balance", type=float, default=10000.0)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--desired-leverage", type=int, default=1)
    parser.add_argument("--signal-source", default="manual_beta_sizing_test")
    return parser



def _direction_from_order_type(order_type: OrderType) -> str:
    return "long" if order_type in {OrderType.BUY_LIMIT, OrderType.BUY_STOP} else "short"



def _default_take_profit(order_type: OrderType, entry: float, stop_loss: float) -> float:
    risk = abs(entry - stop_loss)
    if order_type in {OrderType.BUY_LIMIT, OrderType.BUY_STOP}:
        return entry + 2.0 * risk
    return entry - 2.0 * risk



def _parse_numeric_status(response: dict[str, Any] | None) -> int | None:
    if response is None:
        return None
    raw_status = response.get("status") or response.get("status_code")
    if raw_status is None:
        return None
    if isinstance(raw_status, int):
        return raw_status
    text = str(raw_status).strip()
    return int(text) if text.isdigit() else None



def main() -> int:
    args = _build_parser().parse_args()

    try:
        if str(args.confirm).strip().upper() != "YES":
            raise ValueError("This script requires --confirm YES")

        config = load_propr_config_from_env()
        if config.environment != "beta":
            raise ValueError("This script is only allowed against beta")

        client = ProprClient(config)
        order_service = ProprOrderService(client)

        health_result = fetch_and_check_core_service_health(client)
        if not health_result.allow_trading:
            raise ValueError(f"Core health check blocked sizing test: {health_result.reason}")

        challenge_context = get_active_challenge_context(client)
        if challenge_context is None:
            raise ValueError("No active challenge attempt found")

        symbol_spec = HyperliquidSymbolService().get_symbol_spec(args.symbol)
        order_type = ORDER_TYPE_CHOICES[args.order_type]
        take_profit = args.take_profit if args.take_profit is not None else _default_take_profit(order_type, args.entry, args.stop_loss)

        sizing_result = calculate_position_size(
            entry=args.entry,
            stop_loss=args.stop_loss,
            account_balance=args.account_balance,
            risk_per_trade_pct=args.risk_per_trade_pct,
            desired_leverage=args.desired_leverage,
            symbol_spec=symbol_spec,
        )
        if sizing_result.position_size is None:
            raise ValueError(sizing_result.reason or "Unable to calculate position size")

        execution_check = evaluate_position_size_execution(
            entry=args.entry,
            position_size=sizing_result.position_size,
            account_balance=args.account_balance,
            desired_leverage=args.desired_leverage,
            max_leverage=symbol_spec.max_leverage,
        )
        if not execution_check.allow_execution:
            raise ValueError(execution_check.reason or "Position size is not executable")

        order = apply_symbol_spec_to_order(
            Order(
                order_type=order_type,
                entry=args.entry,
                stop_loss=args.stop_loss,
                take_profit=take_profit,
                position_size=sizing_result.position_size,
                signal_source=args.signal_source,
            ),
            symbol_spec,
        )

        submission_preview = build_order_submission_preview(order, args.symbol)
        submission_preview["asset"] = submission_preview["base"]

        print("Beta sizing test started.")
        print(f"environment: {config.environment}")
        print(f"account_id: {challenge_context.account_id}")
        print(f"symbol: {args.symbol}")
        print(f"direction: {_direction_from_order_type(order_type)}")
        print(f"order_type: {order_type.value}")
        print(f"risk_amount: {sizing_result.risk_amount}")
        print(f"risk_per_unit: {sizing_result.risk_per_unit}")
        print(f"raw_position_size: {sizing_result.raw_position_size}")
        print(f"rounded_position_size: {order.position_size}")
        print(f"required_notional: {execution_check.required_notional}")
        print(f"required_leverage: {execution_check.required_leverage}")
        print("submission_preview:")
        print(submission_preview)

        submit_response = order_service.submit_pending_order(
            challenge_context.account_id,
            order,
            args.symbol,
            submission_preview=submission_preview,
        )
        submit_status = _parse_numeric_status(submit_response)
        if submit_status is not None and submit_status not in {200, 201}:
            raise ValueError(f"Submit returned unexpected status: {submit_status}")

        external_order_id = extract_order_id_from_submit_response(submit_response)
        print("submit_response:")
        print(submit_response)
        print(f"external_order_id: {external_order_id}")
        print("Order left open intentionally.")
        return 0
    except Exception as exc:
        print(f"Beta sizing test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

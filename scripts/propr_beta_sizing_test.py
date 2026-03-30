from __future__ import annotations

import argparse
from pathlib import Path
import sys
from time import sleep
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
from models.trade import Trade, TradeDirection, TradeType
from strategy.position_sizer import calculate_position_size, evaluate_position_size_execution
from utils.env_loader import load_propr_config_from_env


ORDER_TYPE_CHOICES = {
    "buy_limit": OrderType.BUY_LIMIT,
    "sell_limit": OrderType.SELL_LIMIT,
    "buy_stop": OrderType.BUY_STOP,
    "sell_stop": OrderType.SELL_STOP,
}

OPEN_POSITION_STATUSES = {"open", "active", "live"}


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
    parser.add_argument(
        "--place-effective-exits",
        action="store_true",
        help="After the entry fills, place real reduce-only TP and SL orders bound to the opened position.",
    )
    parser.add_argument("--fill-check-attempts", type=int, default=30)
    parser.add_argument("--fill-check-delay-seconds", type=int, default=2)
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



def _parse_symbol(symbol: str) -> tuple[str, str]:
    parts = [part.strip().upper() for part in symbol.split("/") if part.strip()]
    if len(parts) != 2:
        raise ValueError("symbol must be in BASE/QUOTE format")
    return parts[0], parts[1]



def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None



def _extract_position_side(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"buy", "long"}:
        return "long"
    if normalized in {"sell", "short"}:
        return "short"
    return None



def _find_open_position(
    client: ProprClient,
    account_id: str,
    symbol: str,
    direction: str,
) -> dict[str, Any] | None:
    base, _quote = _parse_symbol(symbol)
    positions_payload = client.get_positions(account_id)
    positions = positions_payload.get("data", []) if isinstance(positions_payload, dict) else []
    expected_side = direction.strip().lower()

    for item in positions:
        if not isinstance(item, dict):
            continue
        item_base = str(item.get("base") or "").upper()
        item_asset = str(item.get("asset") or "").upper()
        if item_base != base and item_asset != base and not item_asset.startswith(f"{base}/"):
            continue

        side = _extract_position_side(item.get("positionSide") or item.get("side") or item.get("direction"))
        if side != expected_side:
            continue

        quantity = _to_optional_float(item.get("quantity") or item.get("qty") or item.get("size") or item.get("positionSize"))
        if quantity is None or quantity <= 0:
            continue

        status = str(item.get("status") or "").strip().lower()
        if status and status not in OPEN_POSITION_STATUSES:
            continue

        return item
    return None



def _confirm_open_position(
    client: ProprClient,
    account_id: str,
    symbol: str,
    direction: str,
    attempts: int,
    delay_seconds: int,
) -> dict[str, Any] | None:
    normalized_attempts = max(1, int(attempts))
    normalized_delay = max(0, int(delay_seconds))
    for attempt in range(1, normalized_attempts + 1):
        position = _find_open_position(client, account_id, symbol, direction)
        if position is not None:
            quantity = position.get("quantity") or position.get("qty") or position.get("size") or position.get("positionSize")
            print(f"fill confirmation attempt {attempt}: found open position with quantity={quantity}")
            return position
        if attempt < normalized_attempts and normalized_delay > 0:
            sleep(normalized_delay)
    return None



def _build_trade_from_open_position(
    position_payload: dict[str, Any],
    order_type: OrderType,
    fallback_order: Order,
) -> Trade:
    quantity = _to_optional_float(
        position_payload.get("quantity")
        or position_payload.get("qty")
        or position_payload.get("size")
        or position_payload.get("positionSize")
    )
    if quantity is None or quantity <= 0:
        raise ValueError("Filled position does not expose a positive quantity")

    position_id = position_payload.get("positionId") or position_payload.get("position_id") or position_payload.get("id")
    if position_id is None or not str(position_id).strip():
        raise ValueError("Filled position does not expose a position_id")

    entry = _to_optional_float(
        position_payload.get("entry")
        or position_payload.get("entry_price")
        or position_payload.get("entryPrice")
        or position_payload.get("avgEntryPrice")
        or position_payload.get("averageEntryPrice")
        or position_payload.get("price")
    )
    if entry is None:
        entry = fallback_order.entry

    direction = TradeDirection.LONG if _direction_from_order_type(order_type) == "long" else TradeDirection.SHORT
    return Trade(
        trade_type=TradeType.TREND,
        direction=direction,
        entry=entry,
        stop_loss=fallback_order.stop_loss,
        take_profit=fallback_order.take_profit,
        quantity=quantity,
        position_id=str(position_id),
        is_active=True,
        break_even_activated=False,
        opened_at=str(
            position_payload.get("opened_at")
            or position_payload.get("openedAt")
            or position_payload.get("createdAt")
            or position_payload.get("updatedAt")
            or ""
        )
        or None,
    )



def _print_execution_diagnostics(
    symbol: str,
    order_type: OrderType,
    order: Order,
    sizing_result: Any,
    execution_check: Any,
) -> None:
    print("Beta sizing test started.")
    print(f"symbol: {symbol}")
    print(f"direction: {_direction_from_order_type(order_type)}")
    print(f"order_type: {order_type.value}")
    print(f"entry: {order.entry}")
    print(f"stop_loss: {order.stop_loss}")
    print(f"take_profit: {order.take_profit}")
    print(f"risk_amount: {sizing_result.risk_amount}")
    print(f"risk_per_unit: {sizing_result.risk_per_unit}")
    print(f"raw_position_size: {sizing_result.raw_position_size}")
    print(f"rounded_position_size: {order.position_size}")
    print(f"required_notional: {execution_check.required_notional}")
    print(f"required_leverage: {execution_check.required_leverage}")



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

        _print_execution_diagnostics(
            symbol=args.symbol,
            order_type=order_type,
            order=order,
            sizing_result=sizing_result,
            execution_check=execution_check,
        )

        if not execution_check.allow_execution:
            raise ValueError(execution_check.reason or "Position size is not executable")

        submission_preview = build_order_submission_preview(order, args.symbol)
        submission_preview["asset"] = submission_preview["base"]

        print(f"environment: {config.environment}")
        print(f"account_id: {challenge_context.account_id}")
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

        if not args.place_effective_exits:
            print("Order left open intentionally.")
            return 0

        print("Waiting for fill to place effective TP/SL exits...")
        open_position = _confirm_open_position(
            client=client,
            account_id=challenge_context.account_id,
            symbol=args.symbol,
            direction=_direction_from_order_type(order_type),
            attempts=args.fill_check_attempts,
            delay_seconds=args.fill_check_delay_seconds,
        )
        if open_position is None:
            raise ValueError(
                "Entry order was submitted but no filled position became visible within the configured wait window; "
                "effective TP/SL exits were not placed"
            )

        active_trade = _build_trade_from_open_position(open_position, order_type, order)
        stop_loss_response = order_service.submit_stop_loss_exit(
            challenge_context.account_id,
            active_trade,
            args.symbol,
        )
        take_profit_response = order_service.submit_take_profit_exit(
            challenge_context.account_id,
            active_trade,
            args.symbol,
        )

        stop_loss_status = _parse_numeric_status(stop_loss_response)
        if stop_loss_status is not None and stop_loss_status not in {200, 201}:
            raise ValueError(f"Stop-loss submit returned unexpected status: {stop_loss_status}")

        take_profit_status = _parse_numeric_status(take_profit_response)
        if take_profit_status is not None and take_profit_status not in {200, 201}:
            raise ValueError(f"Take-profit submit returned unexpected status: {take_profit_status}")

        print("filled_position:")
        print(open_position)
        print("stop_loss_response:")
        print(stop_loss_response)
        print(f"stop_loss_order_id: {extract_order_id_from_submit_response(stop_loss_response)}")
        print("take_profit_response:")
        print(take_profit_response)
        print(f"take_profit_order_id: {extract_order_id_from_submit_response(take_profit_response)}")
        print("Position and effective TP/SL exits left open intentionally.")
        return 0
    except Exception as exc:
        print(f"Beta sizing test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

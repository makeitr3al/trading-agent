from __future__ import annotations

from decimal import Decimal
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
    build_manual_order_submission_preview,
    build_order_submission_preview,
    extract_order_id_from_submit_response,
)
from broker.propr_client import ProprClient
from config.hyperliquid_config import HyperliquidConfig
from data.providers.hyperliquid_historical_provider import HyperliquidHistoricalProvider
from models.order import Order, OrderType
from utils.env_loader import (
    load_hyperliquid_config_from_env,
    load_order_types_test_settings_from_env,
    load_propr_config_from_env,
)


STANDALONE_PENDING_ORDER_TYPES_TO_TEST = [
    OrderType.BUY_LIMIT,
    OrderType.SELL_LIMIT,
]

STANDALONE_CONDITIONAL_ORDER_TYPES_NOT_SUPPORTED = [
    OrderType.BUY_STOP,
    OrderType.SELL_STOP,
]


# TODO: Later add a small polling abstraction shared across manual beta write scripts.
# TODO: Later support symbol-specific test quantities from SymbolSpec once needed.
# TODO: If Propr exposes grouped conditional entry orders via the SDK, add standalone BUY_STOP/SELL_STOP coverage.


def _parse_numeric_status(response: dict | None) -> int | None:
    if response is None:
        return None

    raw_status = response.get("status") or response.get("status_code")
    if raw_status is None:
        return None
    if isinstance(raw_status, int):
        return raw_status

    text = str(raw_status).strip()
    if text.isdigit():
        return int(text)
    return None



def _extract_error_message(exc: Exception) -> str:
    return str(exc).lower()



def _is_exchange_asset_not_found(exc: Exception) -> bool:
    return "exchange_asset_not_found" in _extract_error_message(exc)



def _cancel_is_already_resolved(response: dict | None) -> bool:
    if response is None:
        return True

    numeric_status = _parse_numeric_status(response)
    lifecycle_status = str(response.get("status") or "").lower()
    message = str(response.get("message") or response.get("reason") or "").lower()

    if lifecycle_status == "cancelled":
        return False

    if numeric_status == 400 and any(
        text in message for text in ["already filled", "already cancelled", "already canceled", "expired"]
    ):
        return True
    return False



def _load_reference_price(hyperliquid_config: HyperliquidConfig) -> Decimal:
    batch = HyperliquidHistoricalProvider(hyperliquid_config).fetch_candles()
    if not batch.candles:
        raise ValueError("No Hyperliquid candles available for order type test")
    return Decimal(str(batch.candles[-1].close))



def _parse_symbol(symbol: str) -> tuple[str, str]:
    parts = [part.strip().upper() for part in symbol.split("/") if part.strip()]
    if len(parts) != 2:
        raise ValueError("symbol must be in BASE/QUOTE format")
    return parts[0], parts[1]



def _build_test_order(order_type: OrderType, reference_price: Decimal) -> Order:
    far_below = reference_price * Decimal("0.50")
    far_above = reference_price * Decimal("1.50")
    quantity = Decimal("0.001")

    if order_type == OrderType.BUY_LIMIT:
        entry = far_below
        stop_loss = entry * Decimal("0.90")
        take_profit = entry * Decimal("1.10")
    elif order_type == OrderType.SELL_LIMIT:
        entry = far_above
        stop_loss = entry * Decimal("1.10")
        take_profit = entry * Decimal("0.90")
    elif order_type == OrderType.BUY_STOP:
        entry = far_above
        stop_loss = entry * Decimal("0.90")
        take_profit = entry * Decimal("1.10")
    elif order_type == OrderType.SELL_STOP:
        entry = far_below
        stop_loss = entry * Decimal("1.10")
        take_profit = entry * Decimal("0.90")
    else:
        raise ValueError(f"Unsupported test order type: {order_type}")

    return Order(
        order_type=order_type,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        position_size=quantity,
        signal_source=f"manual_order_type_test_{order_type.value.lower()}",
    )



def _confirm_order_visible(client: ProprClient, account_id: str, order_id: str, attempts: int = 3, delay_seconds: int = 2) -> bool:
    for attempt in range(1, attempts + 1):
        orders_payload = client.get_orders(account_id)
        orders = orders_payload.get("data", []) if isinstance(orders_payload, dict) else []
        for item in orders:
            if not isinstance(item, dict):
                continue
            external_id = item.get("orderId") or item.get("order_id") or item.get("id")
            if str(external_id or "").strip() == order_id:
                status = str(item.get("status") or "").lower()
                print(f"  confirmation attempt {attempt}: found order with status={status or 'unknown'}")
                return True
        if attempt < attempts:
            sleep(delay_seconds)
    return False



def _find_open_position(client: ProprClient, account_id: str, base: str, position_side: str | None = None) -> dict[str, Any] | None:
    positions_payload = client.get_positions(account_id)
    positions = positions_payload.get("data", []) if isinstance(positions_payload, dict) else []
    for item in positions:
        if not isinstance(item, dict):
            continue
        item_base = str(item.get("base") or "").upper()
        item_asset = str(item.get("asset") or "").upper()
        if item_base != base and item_asset != base and not item_asset.startswith(f"{base}/"):
            continue
        if position_side and str(item.get("positionSide") or item.get("side") or "").lower() != position_side.lower():
            continue
        quantity = Decimal(str(item.get("quantity") or "0"))
        if quantity <= Decimal("0"):
            continue
        status = str(item.get("status") or "").lower()
        if status and status != "open":
            continue
        return item
    return None



def _confirm_open_position(
    client: ProprClient,
    account_id: str,
    base: str,
    position_side: str = "long",
    attempts: int = 5,
    delay_seconds: int = 2,
) -> dict[str, Any] | None:
    for attempt in range(1, attempts + 1):
        position = _find_open_position(client, account_id, base, position_side=position_side)
        if position is not None:
            print(
                f"  confirmation attempt {attempt}: found open position with quantity={position.get('quantity')} "
                f"and side={position.get('positionSide') or position.get('side')}"
            )
            return position
        if attempt < attempts:
            sleep(delay_seconds)
    return None



def _confirm_position_closed(
    client: ProprClient,
    account_id: str,
    base: str,
    attempts: int = 5,
    delay_seconds: int = 2,
) -> bool:
    for attempt in range(1, attempts + 1):
        position = _find_open_position(client, account_id, base)
        if position is None:
            print(f"  confirmation attempt {attempt}: no open position found")
            return True
        if attempt < attempts:
            sleep(delay_seconds)
    return False



def _prepare_beta_preview(preview: dict[str, Any], use_beta_asset_fallback: bool = False) -> dict[str, Any]:
    adjusted = dict(preview)
    if use_beta_asset_fallback:
        adjusted["asset"] = adjusted["base"]
    return adjusted



def _print_preview(preview: dict) -> None:
    print(f"  intentId: {preview.get('intent_id')}")
    print(f"  side: {preview.get('side')}")
    print(f"  positionSide: {preview.get('position_side')}")
    print(f"  orderType: {preview.get('order_type')}")
    print(f"  asset: {preview.get('asset')}")
    print(f"  base: {preview.get('base')}")
    print(f"  quote: {preview.get('quote')}")
    print(f"  quantity: {preview.get('quantity')}")
    print(f"  price: {preview.get('price')}")
    print(f"  triggerPrice: {preview.get('trigger_price')}")
    print(f"  positionId: {preview.get('position_id')}")
    print(f"  reduceOnly: {preview.get('reduce_only')}")
    print(f"  closePosition: {preview.get('close_position')}")



def _submit_preview(order_service: ProprOrderService, account_id: str, preview: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    response = order_service.submit_order_preview(account_id, preview)
    submit_status = _parse_numeric_status(response) or 200
    if submit_status not in {200, 201}:
        raise ValueError(f"Submit did not return a documented success status: {submit_status}")
    order_id = extract_order_id_from_submit_response(response)
    return response, order_id



def _submit_preview_with_beta_asset_fallback(
    order_service: ProprOrderService,
    account_id: str,
    preview: dict[str, Any],
) -> tuple[dict[str, Any], str | None, bool]:
    try:
        response, order_id = _submit_preview(order_service, account_id, preview)
        return response, order_id, False
    except Exception as exc:
        if not _is_exchange_asset_not_found(exc):
            raise
        fallback_preview = _prepare_beta_preview(preview, use_beta_asset_fallback=True)
        print("  beta asset fallback activated: retrying with asset set to base coin")
        print("  fallback payload preview:")
        _print_preview(fallback_preview)
        response, order_id = _submit_preview(order_service, account_id, fallback_preview)
        return response, order_id, True



def _cancel_if_possible(order_service: ProprOrderService, account_id: str, order_id: str | None, label: str) -> None:
    if not order_id:
        return

    cancel_response = order_service.cancel_order(account_id, order_id)
    if _cancel_is_already_resolved(cancel_response):
        print(f"  {label} cancel result: order already resolved")
        print(f"  {cancel_response}")
        return

    cancel_status = _parse_numeric_status(cancel_response)
    lifecycle_status = str((cancel_response or {}).get("status") or "").lower()
    if cancel_status is not None and cancel_status not in {200, 201}:
        raise ValueError(f"Cancel did not return a documented success status: {cancel_status}")
    if cancel_status is None and lifecycle_status and lifecycle_status != "cancelled":
        raise ValueError(f"Cancel returned unexpected lifecycle status: {lifecycle_status}")

    print(f"  {label} cancel response:")
    print(f"  {cancel_response}")



def _run_pending_order_tests(
    client: ProprClient,
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    reference_price: Decimal,
) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []

    for order_type in STANDALONE_PENDING_ORDER_TYPES_TO_TEST:
        print(f"Testing standalone order type: {order_type.value}")
        order = _build_test_order(order_type, reference_price)
        preview = build_order_submission_preview(order, symbol)

        print("  internal order:")
        print(f"  {order.model_dump()}")
        print("  documented payload preview:")
        _print_preview(preview)

        submit_response, order_id, used_beta_asset_fallback = _submit_preview_with_beta_asset_fallback(
            order_service,
            account_id,
            preview,
        )
        print(f"  used beta asset fallback: {used_beta_asset_fallback}")
        print("  submit response:")
        print(f"  {submit_response}")
        print(f"  extracted orderId: {order_id}")
        if not order_id:
            results.append((order_type.value, "FAILED_NO_ORDER_ID"))
            continue

        confirmed = _confirm_order_visible(client, account_id, order_id)
        print(f"  confirmed in open orders: {confirmed}")
        _cancel_if_possible(order_service, account_id, order_id, "pending order")
        results.append((order_type.value, "CONFIRMED_AND_CANCELLED" if confirmed else "CANCELLED_WITHOUT_CONFIRMATION"))

    for order_type in STANDALONE_CONDITIONAL_ORDER_TYPES_NOT_SUPPORTED:
        print(
            f"Skipping standalone order type: {order_type.value} "
            "because Propr Beta requires a position or group for conditional entry orders"
        )
        results.append((order_type.value, "SKIPPED_REQUIRES_POSITION_OR_GROUP"))

    return results



def _run_open_trade_lifecycle_test(
    client: ProprClient,
    order_service: ProprOrderService,
    account_id: str,
    symbol: str,
    reference_price: Decimal,
) -> list[tuple[str, str]]:
    base, _quote = _parse_symbol(symbol)
    existing_position = _find_open_position(client, account_id, base)
    if existing_position is not None:
        raise ValueError(f"Existing open position detected for {base}; aborting lifecycle test for safety")

    results: list[tuple[str, str]] = []
    tp_order_id: str | None = None
    sl_order_id: str | None = None

    try:
        print("Testing open trade lifecycle: MARKET_OPEN -> TP -> SL -> MARKET_CLOSE")

        market_open_preview = build_manual_order_submission_preview(
            symbol=symbol,
            side="buy",
            position_side="long",
            order_type="market",
            quantity=Decimal("0.001"),
        )
        print("  market open documented preview:")
        _print_preview(market_open_preview)
        open_response, open_order_id, used_beta_asset_fallback = _submit_preview_with_beta_asset_fallback(
            order_service,
            account_id,
            market_open_preview,
        )
        print(f"  used beta asset fallback: {used_beta_asset_fallback}")
        print("  market open response:")
        print(f"  {open_response}")
        print(f"  extracted orderId: {open_order_id}")

        position = _confirm_open_position(client, account_id, base, position_side="long")
        if position is None:
            raise ValueError("Market open did not produce a visible open position")

        open_position_quantity = Decimal(str(position.get("quantity") or "0"))
        if open_position_quantity <= Decimal("0"):
            raise ValueError("Open position quantity is invalid")
        position_id = position.get("positionId") or position.get("position_id")
        print(f"  active positionId: {position_id}")
        results.append(("MARKET_OPEN_LONG", "CONFIRMED_OPEN_POSITION"))

        tp_price = reference_price * Decimal("1.50")
        tp_trigger = reference_price * Decimal("1.40")
        tp_preview = build_manual_order_submission_preview(
            symbol=symbol,
            side="sell",
            position_side="long",
            order_type="take_profit_limit",
            quantity=open_position_quantity,
            price=tp_price,
            trigger_price=tp_trigger,
            reduce_only=True,
            close_position=False,
            position_id=str(position_id) if position_id else None,
        )
        print("  take-profit documented preview:")
        _print_preview(tp_preview)
        tp_response, tp_order_id, used_beta_asset_fallback = _submit_preview_with_beta_asset_fallback(
            order_service,
            account_id,
            tp_preview,
        )
        print(f"  used beta asset fallback: {used_beta_asset_fallback}")
        print("  take-profit response:")
        print(f"  {tp_response}")
        print(f"  extracted TP orderId: {tp_order_id}")
        tp_confirmed = bool(tp_order_id) and _confirm_order_visible(client, account_id, tp_order_id)
        print(f"  take-profit confirmed in open orders: {tp_confirmed}")
        results.append(("TAKE_PROFIT_LIMIT_LONG_EXIT", "CONFIRMED" if tp_confirmed else "NOT_CONFIRMED"))

        sl_trigger = reference_price * Decimal("0.50")
        sl_preview = build_manual_order_submission_preview(
            symbol=symbol,
            side="sell",
            position_side="long",
            order_type="stop_market",
            quantity=open_position_quantity,
            trigger_price=sl_trigger,
            reduce_only=True,
            close_position=False,
            position_id=str(position_id) if position_id else None,
        )
        print("  stop-loss documented preview:")
        _print_preview(sl_preview)
        sl_response, sl_order_id, used_beta_asset_fallback = _submit_preview_with_beta_asset_fallback(
            order_service,
            account_id,
            sl_preview,
        )
        print(f"  used beta asset fallback: {used_beta_asset_fallback}")
        print("  stop-loss response:")
        print(f"  {sl_response}")
        print(f"  extracted SL orderId: {sl_order_id}")
        sl_confirmed = bool(sl_order_id) and _confirm_order_visible(client, account_id, sl_order_id)
        print(f"  stop-loss confirmed in open orders: {sl_confirmed}")
        results.append(("STOP_MARKET_LONG_EXIT", "CONFIRMED" if sl_confirmed else "NOT_CONFIRMED"))

        close_preview = build_manual_order_submission_preview(
            symbol=symbol,
            side="sell",
            position_side="long",
            order_type="market",
            quantity=open_position_quantity,
            reduce_only=True,
            close_position=True,
        )
        print("  market close documented preview:")
        _print_preview(close_preview)
        close_response, close_order_id, used_beta_asset_fallback = _submit_preview_with_beta_asset_fallback(
            order_service,
            account_id,
            close_preview,
        )
        print(f"  used beta asset fallback: {used_beta_asset_fallback}")
        print("  market close response:")
        print(f"  {close_response}")
        print(f"  extracted close orderId: {close_order_id}")
        closed = _confirm_position_closed(client, account_id, base)
        print(f"  confirmed position closed: {closed}")
        results.append(("MARKET_CLOSE_LONG_POSITION", "CONFIRMED_CLOSED" if closed else "NOT_CONFIRMED"))
        return results
    finally:
        _cancel_if_possible(order_service, account_id, tp_order_id, "take-profit")
        _cancel_if_possible(order_service, account_id, sl_order_id, "stop-loss")

        leftover_position = _find_open_position(client, account_id, base)
        if leftover_position is not None:
            leftover_quantity = Decimal(str(leftover_position.get("quantity") or "0"))
            if leftover_quantity > Decimal("0"):
                print("  cleanup: leftover open position detected, attempting final market close")
                cleanup_preview = build_manual_order_submission_preview(
                    symbol=symbol,
                    side="sell",
                    position_side="long",
                    order_type="market",
                    quantity=leftover_quantity,
                    reduce_only=True,
                    close_position=True,
                )
                try:
                    cleanup_response, cleanup_order_id, cleanup_used_beta_asset_fallback = _submit_preview_with_beta_asset_fallback(
                        order_service,
                        account_id,
                        cleanup_preview,
                    )
                    print(f"  cleanup used beta asset fallback: {cleanup_used_beta_asset_fallback}")
                    print("  cleanup market close response:")
                    print(f"  {cleanup_response}")
                    print(f"  cleanup close orderId: {cleanup_order_id}")
                except Exception as cleanup_exc:
                    print(f"  cleanup market close failed: {cleanup_exc}")



def main() -> None:
    try:
        config = load_propr_config_from_env()
        settings = load_order_types_test_settings_from_env()
        hyperliquid_config = load_hyperliquid_config_from_env()

        print("Order types beta test started.")
        print(f"Environment: {settings.environment}")
        print(f"Base URL: {config.base_url}")
        print(f"Symbol: {settings.test_symbol}")
        print(f"Hyperliquid coin: {hyperliquid_config.coin}")
        print(f"Interval: {hyperliquid_config.interval}")
        print(f"Lookback bars: {hyperliquid_config.lookback_bars}")

        if settings.environment != "beta":
            raise ValueError("Order types test is only allowed in beta")
        if settings.confirm != "YES":
            raise ValueError("Order types test requires MANUAL_ORDER_TYPES_CONFIRM=YES")

        client = ProprClient(config)
        order_service = ProprOrderService(client)

        health_result = fetch_and_check_core_service_health(client)
        if not health_result.allow_trading:
            print(f"Core health check blocked order types test: {health_result.reason}")
            return
        print(f"Core health: {health_result.core_status}")

        challenge_context = get_active_challenge_context(client)
        if challenge_context is None:
            print("No active challenge attempt found. Order types test skipped.")
            return

        account_id = challenge_context.account_id
        reference_price = _load_reference_price(hyperliquid_config)
        print(f"Active challenge account_id: {account_id}")
        print(f"Reference market close: {reference_price}")

        results: list[tuple[str, str]] = []
        results.extend(_run_pending_order_tests(client, order_service, account_id, settings.test_symbol, reference_price))
        results.extend(_run_open_trade_lifecycle_test(client, order_service, account_id, settings.test_symbol, reference_price))

        print("Order types beta test summary:")
        for label, result in results:
            print(f"  {label}: {result}")
        print("Order types beta test finished.")
    except Exception as exc:
        print(f"Order types beta test failed: {exc}")


if __name__ == "__main__":
    main()

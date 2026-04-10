from __future__ import annotations

from pathlib import Path
import sys
from decimal import Decimal

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from broker.challenge_service import get_active_challenge_context
from broker.health_guard import fetch_and_check_core_service_health
from broker.order_service import (
    ProprOrderService,
    build_order_submission_preview,
    extract_order_id_from_submit_response,
)
from broker.propr_client import ProprClient
from models.order import Order, OrderType
from utils.env_loader import (
    load_propr_config_from_env,
    load_write_test_settings_from_env,
)


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


def _cancel_is_already_resolved(response: dict | None) -> bool:
    if response is None:
        return True

    numeric_status = _parse_numeric_status(response)
    lifecycle_status = str(response.get("status") or "").lower()
    message = str(response.get("message") or response.get("reason") or "").lower()

    if lifecycle_status == "cancelled":
        return False

    if numeric_status == 400 and any(text in message for text in ["already filled", "already cancelled", "already canceled", "expired"]):
        return True
    return False


def _log_asset_discovery(client: ProprClient, symbol: str) -> None:
    base_asset = symbol.split("/")[0].strip()

    if not hasattr(client, "get_leverage_limits"):
        print("Asset discovery not available on adapter.")
        return

    try:
        limits = client.get_leverage_limits()
    except Exception as exc:
        print(f"Asset discovery unavailable: {exc}")
        return

    overrides = limits.get("overrides", {}) if isinstance(limits, dict) else {}
    default_max = limits.get("defaultMax") if isinstance(limits, dict) else None
    supported_assets = sorted(overrides.keys()) if isinstance(overrides, dict) else []

    if supported_assets:
        preview = ", ".join(supported_assets[:10])
        print(f"Supported assets preview: {preview}")
    else:
        print("Supported assets preview unavailable; only default leverage info returned.")

    if isinstance(overrides, dict) and overrides and base_asset not in overrides:
        print(f"Warning: base asset '{base_asset}' is not explicitly listed in leverage overrides.")
    elif default_max is None and base_asset not in supported_assets:
        print(f"Warning: base asset '{base_asset}' could not be plausibly validated from discovery data.")


def main() -> None:
    try:
        config = load_propr_config_from_env()
        settings = load_write_test_settings_from_env()

        print("Write test started.")
        print(f"Environment: {settings.environment}")
        print(f"Base URL: {config.base_url}")

        if settings.environment != "beta":
            raise ValueError("Write test is only allowed in beta")
        if settings.write_test_confirm != "YES":
            raise ValueError("Write test requires WRITE_TEST_CONFIRM=YES")

        client = ProprClient(config)
        order_service = ProprOrderService(client)

        health_result = fetch_and_check_core_service_health(client)
        if not health_result.allow_trading:
            print(f"Core health check blocked write test: {health_result.reason}")
            return
        print(f"Core health: {health_result.core_status}")

        challenge_context = get_active_challenge_context(client)
        if challenge_context is None:
            print("No active challenge attempt found. Write test skipped.")
            return

        account_id = challenge_context.account_id
        symbol = settings.test_symbol

        print(f"Active challenge account_id: {account_id}")
        print(f"Symbol: {symbol}")
        _log_asset_discovery(client, symbol)

        test_order = Order(
            order_type=OrderType.BUY_LIMIT,
            entry=Decimal("1000"),
            stop_loss=Decimal("900"),
            take_profit=Decimal("1100"),
            position_size=Decimal("0.001"),
            signal_source="manual_beta_write_test",
        )

        submission_preview = build_order_submission_preview(test_order, symbol)

        print("DRY-RUN internal order:")
        print(test_order.model_dump())
        print("DRY-RUN mapped Propr payload:")
        print(submission_preview)
        print(f"intentId: {submission_preview.get('intent_id')}")
        print(f"side: {submission_preview.get('side')}")
        print(f"positionSide: {submission_preview.get('position_side')}")
        print(f"orderType: {submission_preview.get('order_type')}")
        print(f"quantity: {submission_preview.get('quantity')}")
        print(f"price: {submission_preview.get('price')}")
        print(f"reduceOnly: {submission_preview.get('reduce_only')}")
        print(f"closePosition: {submission_preview.get('close_position')}")

        submit_response = order_service.submit_pending_order(
            account_id,
            test_order,
            symbol,
            submission_preview=submission_preview,
        )
        submit_status = _parse_numeric_status(submit_response) or 200
        if submit_status not in {200, 201}:
            raise ValueError(f"Submit did not return a documented success status: {submit_status}")

        print("Submit response:")
        print(submit_response)

        order_id = extract_order_id_from_submit_response(submit_response)
        print(f"Extracted orderId: {order_id}")
        if not order_id:
            print("No orderId could be extracted from submit response. Stopping before cancel.")
            return

        cancel_response = order_service.cancel_order(account_id, order_id)
        if _cancel_is_already_resolved(cancel_response):
            print("Cancel result: order already resolved.")
            print(cancel_response)
            print("Write test finished.")
            return

        cancel_status = _parse_numeric_status(cancel_response)
        lifecycle_status = str((cancel_response or {}).get("status") or "").lower()
        if cancel_status is not None and cancel_status not in {200, 201}:
            raise ValueError(f"Cancel did not return a documented success status: {cancel_status}")
        if cancel_status is None and lifecycle_status and lifecycle_status != "cancelled":
            raise ValueError(f"Cancel returned unexpected lifecycle status: {lifecycle_status}")

        print("Cancel response:")
        print(cancel_response)
        print("Write test finished.")
    except Exception as exc:
        print(f"Write test failed: {exc}")


if __name__ == "__main__":
    main()

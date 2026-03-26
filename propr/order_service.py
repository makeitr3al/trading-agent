from propr.client import ProprClient
from propr.order_mapper import map_cancel_order_payload, map_internal_order_to_propr_payload
from models.order import Order

# TODO: Later add replace/modify order support.
# TODO: Later add batch orders.
# TODO: Later add retry logic.
# TODO: Later add idempotency support.


class ProprOrderService:
    def __init__(self, client: ProprClient) -> None:
        self.client = client

    def submit_pending_order(
        self,
        account_id: str,
        order: Order,
        symbol: str,
    ) -> dict:
        if not account_id or not account_id.strip():
            raise ValueError("account_id is required")

        payload = map_internal_order_to_propr_payload(order, symbol)
        return self.client.create_order(account_id, payload)

    def cancel_order(
        self,
        account_id: str,
        order_id: str,
    ) -> dict:
        if not account_id or not account_id.strip():
            raise ValueError("account_id is required")
        if not order_id or not order_id.strip():
            raise ValueError("order_id is required")

        payload = map_cancel_order_payload(order_id)
        return self.client.cancel_order(account_id, order_id, payload)

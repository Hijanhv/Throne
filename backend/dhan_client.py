"""Thin wrapper over the dhanhq v2 SDK. Credentials come from the environment only."""

from __future__ import annotations

import os
import time
from typing import Any

from models import Action


class DhanError(Exception):
    pass


# Dhan v2 orderStatus values that mean the order will never fill
DEAD_STATUSES = {"REJECTED", "CANCELLED", "EXPIRED"}


class DhanClient:
    def __init__(self) -> None:
        self.client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
        # point at https://sandbox.dhan.co/v2 (virtual money) or a local mock to test without real orders
        self.base_url = os.getenv("DHAN_API_BASE_URL", "").strip().rstrip("/")
        self._sdk: Any = None

    @property
    def configured(self) -> bool:
        placeholders = {"", "your_client_id", "your_access_token"}
        return self.client_id not in placeholders and self.access_token not in placeholders

    def _client(self) -> Any:
        if not self.configured:
            raise DhanError("DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN are not set in .env")
        if self._sdk is None:
            from dhanhq import DhanContext, dhanhq

            ctx = DhanContext(self.client_id, self.access_token)
            if self.base_url:
                ctx.dhan_http.base_url = self.base_url
            # the SDK default is 60s; a stuck broker call should not freeze an executor that long
            ctx.dhan_http.timeout = float(os.getenv("DHAN_HTTP_TIMEOUT", "20"))
            self._sdk = dhanhq(ctx)
        return self._sdk

    @property
    def is_sandbox(self) -> bool:
        return bool(self.base_url) and "api.dhan.co" not in self.base_url

    @staticmethod
    def _unwrap(resp: Any) -> Any:
        if isinstance(resp, dict) and resp.get("status") == "failure":
            remarks = resp.get("remarks") or resp.get("data") or "unknown error"
            raise DhanError(f"Dhan API error: {remarks}")
        return resp.get("data", resp) if isinstance(resp, dict) else resp

    def place_order(
        self,
        security_id: str,
        action: Action,
        quantity: int,
        order_type: str = "MARKET",
        exchange_segment: str = "NSE_EQ",
        product_type: str = "CNC",
        price: float = 0,
        tag: str | None = None,
    ) -> dict[str, Any]:
        if quantity <= 0:
            raise DhanError("quantity must be positive")
        sdk = self._client()
        resp = sdk.place_order(
            security_id=security_id,
            exchange_segment=exchange_segment,
            transaction_type=sdk.BUY if action == Action.BUY else sdk.SELL,
            quantity=int(quantity),
            order_type=order_type,
            product_type=product_type,
            price=price,
            tag=tag,
        )
        data = self._unwrap(resp)
        if not isinstance(data, dict):
            raise DhanError(f"unexpected order response: {data!r}")
        # Dhan answers HTTP 200 for orders its risk system rejects, so the status must be checked
        status = str(data.get("orderStatus", "")).upper()
        if status in DEAD_STATUSES:
            raise DhanError(f"order {status.lower()}: {data.get('omsErrorDescription') or 'no reason given'}")
        if not data.get("orderId"):
            raise DhanError(f"order response has no orderId: {data!r}")
        return data

    def get_order(self, order_id: str) -> dict[str, Any]:
        data = self._unwrap(self._client().get_order_by_id(order_id))
        if isinstance(data, list):  # some API versions wrap the order in a list
            data = data[0] if data else {}
        return data if isinstance(data, dict) else {}

    def confirm_fill(self, order_id: str, attempts: int = 5, delay: float = 1.0) -> tuple[str, float, int]:
        """Polls an order until it trades or dies. Returns (status, average price, filled quantity)."""
        status, price, qty = "UNKNOWN", 0.0, 0
        for i in range(attempts):
            order = self.get_order(order_id)
            status = str(order.get("orderStatus", "UNKNOWN")).upper()
            price = float(order.get("averageTradedPrice") or 0)
            qty = int(order.get("filledQty") or 0)
            if status == "TRADED":
                return status, price, qty
            if status in DEAD_STATUSES:
                raise DhanError(f"order {status.lower()}: {order.get('omsErrorDescription') or 'no reason given'}")
            if i + 1 < attempts:
                time.sleep(delay)
        return status, price, qty

    def get_positions(self) -> list[dict[str, Any]]:
        data = self._unwrap(self._client().get_positions())
        return data if isinstance(data, list) else []

    def get_order_history(self) -> list[dict[str, Any]]:
        data = self._unwrap(self._client().get_order_list())
        return data if isinstance(data, list) else []

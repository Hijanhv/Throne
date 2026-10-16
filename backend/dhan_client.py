"""Thin wrapper over the dhanhq v2 SDK. Credentials come from the environment only."""

from __future__ import annotations

import os
from typing import Any

from models import Action


class DhanError(Exception):
    pass


class DhanClient:
    def __init__(self) -> None:
        self.client_id = os.getenv("DHAN_CLIENT_ID", "").strip()
        self.access_token = os.getenv("DHAN_ACCESS_TOKEN", "").strip()
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

            self._sdk = dhanhq(DhanContext(self.client_id, self.access_token))
        return self._sdk

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
        return data if isinstance(data, dict) else {"raw": data}

    def get_positions(self) -> list[dict[str, Any]]:
        data = self._unwrap(self._client().get_positions())
        return data if isinstance(data, list) else []

    def get_order_history(self) -> list[dict[str, Any]]:
        data = self._unwrap(self._client().get_order_list())
        return data if isinstance(data, list) else []

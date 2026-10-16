"""Places one real order on Dhan's sandbox (virtual money) and walks it through Throne's client.

Usage, from backend/:  .venv/bin/python scripts/dhan_sandbox_check.py

Needs DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN and DHAN_API_BASE_URL=https://sandbox.dhan.co/v2 in .env.
Refuses to run against the production API, so it can never touch real money.
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
load_dotenv(BACKEND / ".env")
load_dotenv(BACKEND.parent / ".env")

from dhan_client import DhanClient, DhanError  # noqa: E402
from models import Action  # noqa: E402

SECURITY_ID = "2885"  # RELIANCE, NSE_EQ


def main() -> int:
    client = DhanClient()
    if not client.configured:
        print("FAIL  DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN are not set in .env")
        return 1
    if "sandbox.dhan.co" not in client.base_url:
        print("STOP  DHAN_API_BASE_URL is not the Dhan sandbox; refusing to place an order")
        return 1
    print(f"Using {client.base_url} (sandbox, virtual money)")

    try:
        positions = client.get_positions()
        print(f"OK    auth works, {len(positions)} open position(s)")

        resp = client.place_order(SECURITY_ID, Action.BUY, 1, product_type="INTRADAY", tag="throne-sandbox-check")
        order_id = str(resp["orderId"])
        print(f"OK    order accepted: id {order_id}, status {resp.get('orderStatus')}")

        status, price, qty = client.confirm_fill(order_id, attempts=10, delay=1.0)
        print(f"OK    order status {status}, filled {qty} @ {price}")

        book = client.get_order_history()
        mine = [o for o in book if str(o.get("orderId")) == order_id]
        print(f"OK    order book has {len(book)} order(s); ours present: {bool(mine)}")
        if mine:
            o = mine[0]
            print(
                f"      correlationId={o.get('correlationId')} product={o.get('productType')} qty={o.get('quantity')}"
            )

        if status == "TRADED":
            sell = client.place_order(
                SECURITY_ID, Action.SELL, qty or 1, product_type="INTRADAY", tag="throne-sandbox-check"
            )
            s_status, s_price, s_qty = client.confirm_fill(str(sell["orderId"]), attempts=10, delay=1.0)
            print(f"OK    closing sell {s_status}, filled {s_qty} @ {s_price}")
    except DhanError as exc:
        print(f"FAIL  {exc}")
        return 1
    print("PASS  Dhan sandbox round trip works through Throne's client")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

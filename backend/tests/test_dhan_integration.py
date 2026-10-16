"""Live mode end to end without real money.

A local HTTP server imitates the Dhan v2 order API. The real dhanhq SDK, our
DhanClient and the executor all run unmodified; only the base URL points at
the mock (the same DHAN_API_BASE_URL switch used for Dhan's sandbox).
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dhan_client import DhanClient, DhanError
from executor import StrategyExecutor
from models import Action, Indicator, Operator, ParsedStrategy, StrategyRule
from tests.test_executor import Feed

CLIENT_ID = "1100000001"
TOKEN = "test-token"


class MockDhan:
    """State shared with the request handler; each test sets `mode`."""

    def __init__(self):
        self.requests: list[dict] = []
        self.mode = "fill"  # fill | reject | pending | auth_error | hang
        self.fill_price = 1234.5
        self.orders: dict[str, dict] = {}


def make_server(state: MockDhan) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _reply(self, code: int, body: object) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _auth_ok(self) -> bool:
            if state.mode == "auth_error" or self.headers.get("access-token") != TOKEN:
                self._reply(
                    401,
                    {
                        "errorType": "Invalid_Authentication",
                        "errorCode": "DH-901",
                        "errorMessage": "Client ID or user generated access token is invalid or expired.",
                    },
                )
                return False
            return True

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append({"method": "POST", "path": self.path, "headers": dict(self.headers), "body": body})
            if state.mode == "hang":
                time.sleep(3)
            if not self._auth_ok():
                return
            order_id = str(len(state.orders) + 1)
            status = {"fill": "TRANSIT", "pending": "PENDING", "reject": "REJECTED"}[state.mode]
            order = {"orderId": order_id, "orderStatus": status}
            if state.mode == "reject":
                order["omsErrorDescription"] = "RMS:Margin Exceeds"
            state.orders[order_id] = {**body, **order}
            self._reply(200, order)

        def do_GET(self):
            state.requests.append({"method": "GET", "path": self.path, "headers": dict(self.headers)})
            if not self._auth_ok():
                return
            if self.path.startswith("/v2/orders/"):
                order = state.orders.get(self.path.rsplit("/", 1)[1])
                if order is None:
                    self._reply(404, {"errorType": "Order_Error", "errorCode": "DH-906", "errorMessage": "not found"})
                    return
                if state.mode == "fill":
                    order = {
                        **order,
                        "orderStatus": "TRADED",
                        "averageTradedPrice": state.fill_price,
                        "filledQty": order["quantity"],
                    }
                self._reply(200, order)
            elif self.path == "/v2/positions":
                self._reply(200, [])
            elif self.path == "/v2/orders":
                self._reply(200, list(state.orders.values()))
            else:
                self._reply(404, {})

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def dhan(monkeypatch):
    state = MockDhan()
    server = make_server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("DHAN_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("DHAN_API_BASE_URL", f"http://127.0.0.1:{server.server_port}/v2")
    client = DhanClient()
    # keep confirmation polling fast in tests
    real_confirm = client.confirm_fill
    client.confirm_fill = lambda order_id: real_confirm(order_id, attempts=2, delay=0.01)  # type: ignore[method-assign]
    yield client, state
    server.shutdown()


def executor(frame, client, closes, timeframe="1d"):
    s = ParsedStrategy(
        name="t",
        text="t",
        symbol="RELIANCE",
        timeframe=timeframe,
        parser="regex",
        confidence=1,
        rules=[
            StrategyRule(indicator=Indicator.PRICE, operator=Operator.CROSSES_ABOVE, value=105, action=Action.BUY),
            StrategyRule(indicator=Indicator.PRICE, operator=Operator.CROSSES_BELOW, value=100, action=Action.SELL),
        ],
    )
    ex = StrategyExecutor(s, "live", 100_000, client, security_id="2885", fetch=Feed(frame, closes))
    ex.running = True
    ex.status = "running"
    return ex


def test_order_payload_matches_dhan_v2(dhan):
    client, state = dhan
    resp = client.place_order("2885", Action.BUY, 10, product_type="CNC", tag="throne-abcd1234")
    assert resp["orderId"] == "1"
    req = state.requests[0]
    assert req["method"] == "POST" and req["path"] == "/v2/orders"
    assert req["headers"]["access-token"] == TOKEN and req["headers"]["client-id"] == CLIENT_ID
    body = req["body"]
    assert body == {
        "dhanClientId": CLIENT_ID,
        "transactionType": "BUY",
        "exchangeSegment": "NSE_EQ",
        "productType": "CNC",
        "orderType": "MARKET",
        "validity": "DAY",
        "securityId": "2885",
        "quantity": 10,
        "disclosedQuantity": 0,
        "price": 0.0,
        "afterMarketOrder": False,
        "boProfitValue": None,
        "boStopLossValue": None,
        "triggerPrice": 0.0,
        "correlationId": "throne-abcd1234",
    }


async def test_live_round_trip_uses_broker_fill_price(dhan, frame):
    client, state = dhan
    ex = executor(frame, client, [100, 102, 106, 108, 109, 99, 97, 96])
    for _ in range(6):
        await ex.tick()
    st = await ex.get_status()
    assert st.status == "running" and st.last_error is None
    posts = [r["body"] for r in state.requests if r["method"] == "POST"]
    assert [p["transactionType"] for p in posts] == ["BUY", "SELL"]
    # buy sized from capital at the candle price (108), sell closes exactly what was filled
    assert posts[0]["quantity"] == 100_000 // 108 and posts[1]["quantity"] == posts[0]["quantity"]
    assert all(p["productType"] == "CNC" for p in posts)  # daily strategies hold delivery
    # both fills booked at Dhan's averageTradedPrice, not our last candle
    assert [f.price for f in st.fills] == [1234.5, 1234.5]
    assert [f.order_id for f in st.fills] == ["2", "1"]
    assert st.position_qty == 0 and st.realized_pnl == 0


async def test_intraday_strategies_use_intraday_product(dhan, frame):
    client, state = dhan
    ex = executor(frame, client, [100, 102, 106, 108, 109], timeframe="1h")
    for _ in range(2):
        await ex.tick()
    assert state.requests[0]["body"]["productType"] == "INTRADAY"


async def test_rejected_order_stops_executor_without_position(dhan, frame):
    client, state = dhan
    state.mode = "reject"
    ex = executor(frame, client, [100, 102, 106, 108, 109])
    for _ in range(2):
        await ex.tick()
    st = await ex.get_status()
    assert st.status == "error" and "Margin Exceeds" in st.last_error and "rejected" in st.last_error
    assert st.position_qty == 0 and st.fills == []
    assert not ex.running


async def test_expired_token_stops_executor(dhan, frame):
    client, state = dhan
    state.mode = "auth_error"
    ex = executor(frame, client, [100, 102, 106, 108, 109])
    for _ in range(2):
        await ex.tick()
    st = await ex.get_status()
    assert st.status == "error" and "DH-901" in st.last_error
    assert st.fills == []


async def test_pending_order_is_booked_and_flagged(dhan, frame):
    client, state = dhan
    state.mode = "pending"
    ex = executor(frame, client, [100, 102, 106, 108, 109])
    for _ in range(2):
        await ex.tick()
    st = await ex.get_status()
    assert st.status == "running" and st.position_qty > 0
    assert "pending at broker" in st.fills[0].reason


async def test_broker_unreachable_stops_executor(frame, monkeypatch):
    monkeypatch.setenv("DHAN_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("DHAN_API_BASE_URL", "http://127.0.0.1:9/v2")  # nothing listens here
    ex = executor(frame, DhanClient(), [100, 102, 106, 108, 109])
    for _ in range(2):
        await ex.tick()
    st = await ex.get_status()
    assert st.status == "error" and st.fills == []


def test_read_endpoints(dhan):
    client, _ = dhan
    assert client.get_positions() == []
    client.place_order("2885", Action.BUY, 1)
    assert len(client.get_order_history()) == 1


def test_missing_credentials_never_calls_network(monkeypatch):
    monkeypatch.setenv("DHAN_CLIENT_ID", "your_client_id")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "your_access_token")
    with pytest.raises(DhanError, match="not set"):
        DhanClient().place_order("2885", Action.BUY, 1)


async def test_hung_broker_times_out_and_stops(dhan, frame, monkeypatch):
    _, state = dhan
    state.mode = "hang"
    monkeypatch.setenv("DHAN_HTTP_TIMEOUT", "0.5")
    client = DhanClient()  # picks up the short timeout
    ex = executor(frame, client, [100, 102, 106, 108, 109])
    started = time.monotonic()
    for _ in range(2):
        await ex.tick()
    st = await ex.get_status()
    assert time.monotonic() - started < 2.5
    assert st.status == "error" and "Check the Dhan order book" in st.last_error
    assert st.fills == [] and st.position_qty == 0

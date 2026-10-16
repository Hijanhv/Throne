import pytest

from executor import StrategyExecutor
from models import Action, Indicator, Operator, ParsedStrategy, StrategyRule


class FakeDhan:
    configured = True

    def __init__(self):
        self.orders = []

    def place_order(self, *args):
        self.orders.append(args)
        return {"orderId": f"ord-{len(self.orders)}"}


class Feed:
    """Returns a growing price series, one new bar per tick."""

    def __init__(self, frame, closes):
        self.frame, self.closes, self.n = frame, closes, 3

    def __call__(self, symbol, period, interval):
        df = self.frame(self.closes[: self.n])
        self.n += 1
        return df


def make(frame, closes, mode="paper", dhan=None, **kw):
    s = ParsedStrategy(
        name="t",
        text="t",
        symbol="TEST",
        timeframe="1d",
        parser="regex",
        confidence=1,
        rules=[
            StrategyRule(indicator=Indicator.PRICE, operator=Operator.CROSSES_ABOVE, value=105, action=Action.BUY),
            StrategyRule(indicator=Indicator.PRICE, operator=Operator.CROSSES_BELOW, value=100, action=Action.SELL),
        ],
        **kw,
    )
    return StrategyExecutor(s, mode, 10_000, dhan or FakeDhan(), security_id="1333", fetch=Feed(frame, closes))


async def test_paper_round_trip(frame):
    dhan = FakeDhan()
    ex = make(frame, [100, 102, 106, 108, 109, 99, 97, 96], dhan=dhan)
    for _ in range(6):
        await ex.tick()
    st = await ex.get_status()
    assert [f.side for f in st.fills] == [Action.SELL, Action.BUY]  # newest first
    buy = st.fills[1]
    assert buy.quantity == 10_000 // buy.price
    assert st.position_qty == 0
    assert st.realized_pnl < 0
    assert dhan.orders == []  # paper mode never calls the broker


async def test_stop_loss_uses_live_price(frame):
    ex = make(frame, [100, 102, 106, 108, 103, 103], stop_loss_pct=3)
    for _ in range(3):
        await ex.tick()
    st = await ex.get_status()
    assert st.fills[0].side == Action.SELL and "stop loss" in st.fills[0].reason


async def test_live_mode_sends_orders(frame):
    dhan = FakeDhan()
    ex = make(frame, [100, 102, 106, 108, 109], mode="live", dhan=dhan)
    for _ in range(2):
        await ex.tick()
    assert len(dhan.orders) == 1
    security_id, side, qty = dhan.orders[0][:3]
    assert security_id == "1333" and side == Action.BUY and qty > 0
    assert (await ex.get_status()).fills[0].order_id == "ord-1"


async def test_live_rejection_stops_executor(frame):
    class Broken(FakeDhan):
        def place_order(self, *args):
            raise RuntimeError("insufficient funds")

    ex = make(frame, [100, 102, 106, 108, 109], mode="live", dhan=Broken())
    ex.running = True
    for _ in range(2):
        await ex.tick()
    st = await ex.get_status()
    assert st.status == "error" and "insufficient funds" in st.last_error
    assert not ex.running and st.position_qty == 0


async def test_data_errors_do_not_crash(frame):
    ex = make(frame, [100])

    def boom(*_):
        raise ConnectionError("offline")

    ex._fetch = boom
    await ex.tick()
    assert "offline" in (await ex.get_status()).last_error


@pytest.mark.parametrize("closes", [[100, 102, 106, 108]])
async def test_start_and_stop(frame, closes):
    import asyncio

    ex = make(frame, closes)
    ex.poll_seconds = 5
    task = asyncio.create_task(ex.start())
    await asyncio.sleep(0.05)
    assert ex.status == "running"
    await ex.stop()
    await asyncio.wait_for(task, 1)
    assert ex.status == "stopped"

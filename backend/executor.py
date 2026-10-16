"""Live and paper trading loop.

Each tick fetches recent candles, computes signals with the same code the
backtester uses, and acts on the last completed bar. The newest bar is treated
as still forming, which mirrors the backtest rule of deciding on a close and
filling on the next bar. Stop loss and take profit are checked on every tick
against the latest price.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pandas as pd

from backtester import compute_signals, fetch_ohlcv
from dhan_client import DhanClient
from models import Action, ExecutorStatus, Fill, Mode, ParsedStrategy

log = logging.getLogger("throne.executor")

IST = timezone(timedelta(hours=5, minutes=30))

# enough history for the slowest indicator (SMA 200) at each timeframe
_LOOKBACK = {"1d": "2y", "1h": "3mo", "15m": "30d"}

Fetcher = Callable[[str, str, str], pd.DataFrame]


class StrategyExecutor:
    def __init__(
        self,
        strategy: ParsedStrategy,
        mode: Mode,
        capital: float,
        dhan_client: DhanClient,
        security_id: str | None = None,
        exchange_segment: str = "NSE_EQ",
        poll_seconds: int = 60,
        fetch: Fetcher = fetch_ohlcv,
    ) -> None:
        self.strategy = strategy
        self.mode: Mode = mode
        self.capital = capital
        self.dhan = dhan_client
        self.security_id = security_id
        self.exchange_segment = exchange_segment
        self.poll_seconds = poll_seconds
        self._fetch = fetch

        self.running = False
        self.status: str = "stopped"
        self.position_qty = 0
        self.entry_price: float | None = None
        self.realized_pnl = 0.0
        self.last_price: float | None = None
        self.last_signal: str | None = None
        self.last_tick: datetime | None = None
        self.last_error: str | None = None
        self.fills: list[Fill] = []
        self._last_decision_bar: pd.Timestamp | None = None
        self._wake = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self.running = True
        self.status = "running"
        self._wake.clear()
        while self.running:
            await self.tick()
            if not self.running:
                break
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass
        if self.status == "running":
            self.status = "stopped"

    async def stop(self) -> None:
        self.running = False
        if self.status == "running":
            self.status = "stopped"
        self._wake.set()

    async def get_status(self) -> ExecutorStatus:
        unrealized = 0.0
        if self.position_qty and self.entry_price is not None and self.last_price is not None:
            unrealized = (self.last_price - self.entry_price) * self.position_qty
        today = datetime.now(IST).date()
        return ExecutorStatus(
            strategy_id=self.strategy.id,
            mode=self.mode,
            status=self.status,  # type: ignore[arg-type]
            capital=self.capital,
            current_pnl=round(self.realized_pnl + unrealized, 2),
            realized_pnl=round(self.realized_pnl, 2),
            unrealized_pnl=round(unrealized, 2),
            position_qty=self.position_qty,
            entry_price=self.entry_price,
            last_price=self.last_price,
            trades_today=sum(1 for f in self.fills if f.time.astimezone(IST).date() == today),
            last_signal=self.last_signal,
            last_tick=self.last_tick,
            last_error=self.last_error,
            fills=list(reversed(self.fills[-50:])),
        )

    # -- trading logic -----------------------------------------------------

    async def tick(self) -> None:
        tf = self.strategy.timeframe
        try:
            df = await asyncio.to_thread(self._fetch, self.strategy.symbol, _LOOKBACK[tf], tf)
        except Exception as exc:
            self.last_error = f"data fetch failed: {exc}"
            log.warning("executor %s: %s", self.strategy.id, self.last_error)
            return
        self.last_tick = datetime.now(UTC)
        if len(df) < 3:
            self.last_error = "not enough candles yet"
            return

        signal, _ = compute_signals(df, self.strategy)
        price = float(df["Close"].iloc[-1])
        self.last_price = price
        self.last_error = None

        # risk exits use the live price, every tick
        if self.position_qty and self.entry_price is not None:
            sl = self.strategy.effective_stop_loss
            tp = self.strategy.effective_take_profit
            if sl and price <= self.entry_price * (1 - sl / 100):
                await self._order(Action.SELL, price, f"stop loss {sl:g}%")
                return
            if tp and price >= self.entry_price * (1 + tp / 100):
                await self._order(Action.SELL, price, f"take profit {tp:g}%")
                return

        decision_bar = df.index[-2]
        if decision_bar == self._last_decision_bar:
            return
        self._last_decision_bar = decision_bar
        sig = int(signal[-2])
        bar = decision_bar.strftime("%Y-%m-%d" if tf == "1d" else "%Y-%m-%d %H:%M")
        if sig == 1 and not self.position_qty:
            self.last_signal = f"BUY signal on {bar} bar"
            await self._order(Action.BUY, price, "entry signal")
        elif sig == -1 and self.position_qty:
            self.last_signal = f"SELL signal on {bar} bar"
            await self._order(Action.SELL, price, "exit signal")
        else:
            self.last_signal = f"HOLD on {bar} bar"

    async def _order(self, side: Action, price: float, reason: str) -> None:
        if side == Action.BUY:
            qty = math.floor((self.capital + self.realized_pnl) / price)
            if qty < 1:
                self.last_error = f"capital too small to buy one unit at {price:,.2f}"
                return
        else:
            qty = self.position_qty

        order_id: str | None = None
        if self.mode == "live":
            if not self.security_id:
                self._fail("live mode needs a Dhan security_id")
                return
            try:
                resp = await asyncio.to_thread(
                    self.dhan.place_order,
                    self.security_id,
                    side,
                    qty,
                    "MARKET",
                    self.exchange_segment,
                    "CNC" if self.strategy.timeframe == "1d" else "INTRADAY",
                    0,
                    f"throne-{self.strategy.id[:8]}",
                )
                order_id = str(resp["orderId"])
                status, avg_price, filled = await asyncio.to_thread(self.dhan.confirm_fill, order_id)
            except Exception as exc:  # DhanError, network errors, SDK errors
                self._fail(f"order not confirmed: {exc}. Check the Dhan order book before deploying again")
                return
            if status == "TRADED" or (status == "PART_TRADED" and filled):
                # book what actually executed; on a partial fill the rest is still working at Dhan
                price = avg_price or price
                qty = filled or qty
                if status == "PART_TRADED":
                    reason = f"{reason}, partly filled, rest still open at broker"
            else:
                # still working at the exchange; book it at the last price and say so
                reason = f"{reason}, {status.lower()} at broker"

        # paper fills, and unconfirmed live fills, are marked at the last price
        if side == Action.BUY:
            self.position_qty = qty
            self.entry_price = price
        else:
            assert self.entry_price is not None
            self.realized_pnl += (price - self.entry_price) * qty
            self.position_qty -= qty  # a partial sell leaves the rest open
            if self.position_qty <= 0:
                self.position_qty = 0
                self.entry_price = None
        self.fills.append(
            Fill(
                time=datetime.now(UTC), side=side, price=round(price, 2), quantity=qty, reason=reason, order_id=order_id
            )
        )
        self.last_signal = f"{side.value} {qty} @ {price:,.2f} ({reason})"

    def _fail(self, msg: str) -> None:
        """Live order problems stop the executor; we never keep trading blind."""
        self.last_error = msg
        self.status = "error"
        self.running = False
        self._wake.set()
        log.error("executor %s: %s", self.strategy.id, msg)

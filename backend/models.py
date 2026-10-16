"""Pydantic v2 models shared by the parser, backtester, executor and API."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Indicator(str, Enum):
    RSI = "RSI"
    MACD = "MACD"
    EMA = "EMA"
    SMA = "SMA"
    BB = "BB"  # Bollinger %B: 0 = lower band, 1 = upper band
    VOLUME = "VOLUME"  # volume / 20-bar average volume
    PRICE = "PRICE"  # close price


class Operator(str, Enum):
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


Timeframe = Literal["1d", "1h", "15m"]
Mode = Literal["paper", "live"]

DEFAULT_PERIODS: dict[Indicator, int | None] = {
    Indicator.RSI: 14,
    Indicator.MACD: None,
    Indicator.EMA: 20,
    Indicator.SMA: 50,
    Indicator.BB: 20,
    Indicator.VOLUME: 20,
    Indicator.PRICE: None,
}


class StrategyRule(BaseModel):
    """One condition. Compares an indicator against a constant or another indicator.

    Examples:
      RSI(14) CROSSES_BELOW 30            -> indicator=RSI, value=30
      EMA(20) CROSSES_ABOVE SMA(50)       -> indicator=EMA, period=20, compare_to=SMA, compare_period=50
      MACD CROSSES_ABOVE (signal line)    -> indicator=MACD, value=None, compare_to=None
      VOLUME GREATER_THAN 2 (x average)   -> indicator=VOLUME, value=2
    """

    model_config = ConfigDict(use_enum_values=False)

    indicator: Indicator
    period: int | None = Field(default=None, ge=1, le=500)
    operator: Operator
    value: float | None = None
    compare_to: Indicator | None = None
    compare_period: int | None = Field(default=None, ge=1, le=500)
    action: Action
    stop_loss_pct: float | None = Field(default=None, gt=0, lt=100)
    take_profit_pct: float | None = Field(default=None, gt=0, le=1000)

    @field_validator("indicator", "compare_to", "operator", "action", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip().upper().replace(" ", "_")
        return v

    @model_validator(mode="after")
    def _check_target(self) -> StrategyRule:
        if self.period is None:
            self.period = DEFAULT_PERIODS[self.indicator]
        if self.compare_to is not None and self.compare_period is None:
            self.compare_period = DEFAULT_PERIODS[self.compare_to]
        if self.value is None and self.compare_to is None and self.indicator != Indicator.MACD:
            raise ValueError(f"{self.indicator.value} rule needs a value or compare_to")
        if self.compare_to is not None and self.compare_to == self.indicator and self.compare_period == self.period:
            raise ValueError("rule compares an indicator with itself")
        return self

    def describe(self) -> str:
        left = _label(self.indicator, self.period)
        if self.compare_to is not None:
            right = _label(self.compare_to, self.compare_period)
        elif self.value is None:
            right = "SIGNAL LINE"
        elif self.indicator == Indicator.VOLUME:
            right = f"{self.value:g}x AVG VOLUME"
        else:
            right = f"{self.value:g}"
        op = self.operator.value.replace("_", " ")
        return f"IF {left} {op} {right} -> {self.action.value}"


def _label(ind: Indicator, period: int | None) -> str:
    if ind in (Indicator.PRICE, Indicator.MACD, Indicator.VOLUME):
        return ind.value
    return f"{ind.value}({period})"


class ParseRequest(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    symbol: str | None = Field(default=None, max_length=32)
    timeframe: Timeframe = "1d"


class ParsedStrategy(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    text: str
    rules: list[StrategyRule]
    entry_logic: Literal["all", "any"] = "all"
    exit_logic: Literal["all", "any"] = "any"
    stop_loss_pct: float | None = Field(default=None, gt=0, lt=100)
    take_profit_pct: float | None = Field(default=None, gt=0, le=1000)
    symbol: str
    timeframe: Timeframe
    parser: Literal["ai", "regex"]
    confidence: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def effective_stop_loss(self) -> float | None:
        vals = [v for v in [self.stop_loss_pct, *(r.stop_loss_pct for r in self.rules)] if v]
        return min(vals) if vals else None

    @property
    def effective_take_profit(self) -> float | None:
        vals = [v for v in [self.take_profit_pct, *(r.take_profit_pct for r in self.rules)] if v]
        return min(vals) if vals else None

    def rules_for(self, action: Action) -> list[StrategyRule]:
        return [r for r in self.rules if r.action == action]


class BacktestRequest(BaseModel):
    strategy_id: str
    period: Literal["1mo", "3mo", "6mo", "1y", "2y", "5y"] = "1y"
    interval: Timeframe | None = None  # defaults to the strategy timeframe
    initial_capital: float = Field(default=100_000, gt=0, le=1e10)
    fee_bps: float = Field(default=5, ge=0, le=100)


class Trade(BaseModel):
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    pnl: float  # rupees
    pnl_pct: float
    exit_reason: Literal["signal", "stop_loss", "take_profit", "end_of_data"]
    action: Literal["LONG"] = "LONG"


class EquityPoint(BaseModel):
    date: str
    time: int  # unix seconds, for the chart
    value: float  # indexed to 100 at start


class BacktestResult(BaseModel):
    strategy_id: str
    symbol: str
    ticker: str
    period: str
    interval: str
    initial_capital: float
    trades: list[Trade]
    total_pnl: float
    total_return_pct: float
    benchmark_return_pct: float
    sharpe_ratio: float
    max_drawdown: float  # percent, negative
    win_rate: float  # percent
    total_trades: int
    bars: int
    equity_curve: list[EquityPoint]
    warnings: list[str] = Field(default_factory=list)


class DeployRequest(BaseModel):
    strategy_id: str
    mode: Mode = "paper"
    capital: float = Field(gt=0, le=1e10)
    # Live mode only. Dhan identifies instruments by security id, not ticker.
    security_id: str | None = Field(default=None, max_length=32)
    exchange_segment: Literal["NSE_EQ", "BSE_EQ", "NSE_FNO"] = "NSE_EQ"
    confirm_live: bool = False
    poll_seconds: int = Field(default=60, ge=5, le=3600)


class Fill(BaseModel):
    time: datetime
    side: Action
    price: float
    quantity: int
    reason: str
    order_id: str | None = None


class ExecutorStatus(BaseModel):
    strategy_id: str
    mode: Mode
    status: Literal["running", "stopped", "error"]
    capital: float
    current_pnl: float
    realized_pnl: float
    unrealized_pnl: float
    position_qty: int
    entry_price: float | None
    last_price: float | None
    trades_today: int
    last_signal: str | None
    last_tick: datetime | None
    last_error: str | None
    fills: list[Fill]

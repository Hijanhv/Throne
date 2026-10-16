"""Deterministic backtest engine.

Indicators and entry/exit signals are computed vectorized over the whole
series. The position state machine (entries, stops, targets) is a single
pass over numpy arrays, because stop and target exits are path dependent.

Execution model, chosen to avoid lookahead:
  * a signal is evaluated on the close of bar t and filled at the open of bar t+1
  * stop loss and take profit are checked intrabar against low/high; a gap
    through the level fills at the open; if both levels sit inside one bar the
    stop is assumed to hit first
  * long only, fully invested, compounding; fees charged per side in bps
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator, SMAIndicator
from ta.volatility import BollingerBands

from models import (
    Action,
    BacktestResult,
    EquityPoint,
    Indicator,
    Operator,
    ParsedStrategy,
    StrategyRule,
    Trade,
)

_TICKERS = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "SENSEX": "^BSESN",
}

# Bars per trading day on NSE (09:15 to 15:30)
_BARS_PER_DAY = {"1d": 1, "1h": 7, "15m": 25}

# yfinance limits on how far back intraday data goes
_MAX_PERIOD = {"15m": "60d", "1h": "2y"}
_PERIOD_DAYS = {"1mo": 30, "3mo": 90, "6mo": 180, "60d": 60, "1y": 365, "2y": 730, "5y": 1825}


class DataError(Exception):
    pass


def to_ticker(symbol: str) -> str:
    s = symbol.strip().upper()
    if s in _TICKERS:
        return _TICKERS[s]
    if s.startswith("^") or "." in s or "=" in s:
        return s
    return f"{s}.NS"  # default to NSE equities


def clamp_period(period: str, interval: str) -> str:
    cap = _MAX_PERIOD.get(interval)
    if cap and _PERIOD_DAYS.get(period, 0) > _PERIOD_DAYS[cap]:
        return cap
    return period


def fetch_ohlcv(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    ticker = to_ticker(symbol)
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    if df is None or df.empty:
        raise DataError(f"No data from yfinance for {ticker} ({period}, {interval})")
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 2:
        raise DataError(f"Not enough bars for {ticker}")
    return df


# ---------------------------------------------------------------------------
# Indicators and signals
# ---------------------------------------------------------------------------


def series_for(df: pd.DataFrame, ind: Indicator, period: int | None) -> pd.Series:
    close = df["Close"]
    if ind == Indicator.PRICE:
        return close
    if ind == Indicator.RSI:
        return RSIIndicator(close, window=period or 14).rsi()
    if ind == Indicator.EMA:
        return EMAIndicator(close, window=period or 20).ema_indicator()
    if ind == Indicator.SMA:
        return SMAIndicator(close, window=period or 50).sma_indicator()
    if ind == Indicator.MACD:
        return MACD(close, window_slow=26, window_fast=12, window_sign=9).macd()
    if ind == Indicator.BB:
        return BollingerBands(close, window=period or 20, window_dev=2).bollinger_pband()
    if ind == Indicator.VOLUME:
        vol = df["Volume"].astype(float)
        avg = vol.rolling(period or 20).mean().shift(1)  # compare against the prior bars only
        return vol / avg.replace(0, np.nan)
    raise ValueError(f"unsupported indicator {ind}")


def rule_mask(df: pd.DataFrame, rule: StrategyRule) -> np.ndarray:
    left = series_for(df, rule.indicator, rule.period)
    if rule.compare_to is not None:
        right: pd.Series = series_for(df, rule.compare_to, rule.compare_period)
    elif rule.value is None and rule.indicator == Indicator.MACD:
        right = MACD(df["Close"], window_slow=26, window_fast=12, window_sign=9).macd_signal()
    else:
        right = pd.Series(float(rule.value or 0.0), index=df.index)

    l_now, r_now = left.to_numpy(dtype=float), right.to_numpy(dtype=float)
    l_prev = np.concatenate([[np.nan], l_now[:-1]])
    r_prev = np.concatenate([[np.nan], r_now[:-1]])
    with np.errstate(invalid="ignore"):
        if rule.operator == Operator.GREATER_THAN:
            mask = l_now > r_now
        elif rule.operator == Operator.LESS_THAN:
            mask = l_now < r_now
        elif rule.operator == Operator.CROSSES_ABOVE:
            mask = (l_now > r_now) & (l_prev <= r_prev)
        else:
            mask = (l_now < r_now) & (l_prev >= r_prev)
    return np.nan_to_num(mask, nan=0).astype(bool)


def _combine(masks: list[np.ndarray], logic: str, n: int) -> np.ndarray:
    if not masks:
        return np.zeros(n, dtype=bool)
    stack = np.vstack(masks)
    return stack.all(axis=0) if logic == "all" else stack.any(axis=0)


def compute_signals(df: pd.DataFrame, strategy: ParsedStrategy) -> tuple[np.ndarray, list[str]]:
    """Returns the signal column (+1 buy, -1 sell, 0 hold) and any warnings."""
    warnings: list[str] = []
    has_volume = bool((df["Volume"].fillna(0) > 0).mean() > 0.5)
    n = len(df)

    def masks_for(action: Action) -> list[np.ndarray]:
        out = []
        for rule in strategy.rules_for(action):
            if Indicator.VOLUME in (rule.indicator, rule.compare_to) and not has_volume:
                warnings.append(
                    f"{to_ticker(strategy.symbol)} has no volume data at this interval, so "
                    f'"{rule.describe()}" was skipped'
                )
                continue
            out.append(rule_mask(df, rule))
        return out

    entry = _combine(masks_for(Action.BUY), strategy.entry_logic, n)
    exit_ = _combine(masks_for(Action.SELL), strategy.exit_logic, n)
    signal = np.where(entry, 1, np.where(exit_, -1, 0)).astype(np.int8)
    return signal, warnings


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------


@dataclass
class SimResult:
    equity: np.ndarray  # indexed to 100
    trades: list[Trade]


def _fmt(ts: pd.Timestamp, interval: str) -> str:
    return ts.strftime("%Y-%m-%d") if interval == "1d" else ts.strftime("%Y-%m-%d %H:%M")


def simulate(
    df: pd.DataFrame,
    signal: np.ndarray,
    stop_loss_pct: float | None,
    take_profit_pct: float | None,
    fee_bps: float,
    capital: float,
    interval: str,
) -> SimResult:
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    lo = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    idx = df.index
    n = len(df)
    fee = fee_bps / 10_000

    equity = np.empty(n)
    cash = 100.0  # equity while flat, indexed to 100
    in_pos = False
    entry_px = 0.0
    entry_i = 0
    entry_equity = 0.0
    trades: list[Trade] = []

    def close_trade(i: int, px: float, reason: str) -> None:
        nonlocal cash, in_pos
        gross = px / entry_px
        cash = entry_equity * (1 - fee) * gross * (1 - fee)
        ret = cash / entry_equity - 1
        rupee_base = capital * entry_equity / 100
        trades.append(
            Trade(
                entry_date=_fmt(idx[entry_i], interval),
                exit_date=_fmt(idx[i], interval),
                entry_price=round(entry_px, 2),
                exit_price=round(px, 2),
                pnl=round(rupee_base * ret, 2),
                pnl_pct=round(ret * 100, 2),
                exit_reason=reason,  # type: ignore[arg-type]
            )
        )
        in_pos = False

    for i in range(n):
        if in_pos:
            stop = entry_px * (1 - stop_loss_pct / 100) if stop_loss_pct else None
            target = entry_px * (1 + take_profit_pct / 100) if take_profit_pct else None
            # a gap through the level fills at the open (on the entry bar the open is the entry price)
            if stop is not None and lo[i] <= stop:
                close_trade(i, min(o[i], stop), "stop_loss")
            elif target is not None and h[i] >= target:
                close_trade(i, max(o[i], target), "take_profit")

        if in_pos:
            equity[i] = entry_equity * (1 - fee) * c[i] / entry_px
        else:
            equity[i] = cash

        # act on this bar's close at the next bar's open
        if i + 1 < n:
            if not in_pos and signal[i] == 1:
                in_pos = True
                entry_i = i + 1
                entry_px = o[i + 1]
                entry_equity = cash
            elif in_pos and signal[i] == -1:
                # the fill is recorded on the next bar; that bar's equity is set in its own iteration
                close_trade(i + 1, o[i + 1], "signal")

    if in_pos:
        close_trade(n - 1, c[-1], "end_of_data")
        equity[-1] = cash

    return SimResult(equity=equity, trades=trades)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def sharpe(equity: np.ndarray, interval: str) -> float:
    rets = np.diff(equity) / equity[:-1]
    if len(rets) < 2 or np.std(rets, ddof=1) == 0:
        return 0.0
    periods = 252 * _BARS_PER_DAY.get(interval, 1)
    return float(np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(periods))


def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd = equity / peak - 1
    return float(dd.min() * 100)


def run_backtest(
    strategy: ParsedStrategy,
    period: str = "1y",
    interval: str | None = None,
    initial_capital: float = 100_000,
    fee_bps: float = 5,
    data: pd.DataFrame | None = None,
) -> BacktestResult:
    interval = interval or strategy.timeframe
    warnings: list[str] = []
    eff_period = clamp_period(period, interval)
    if eff_period != period:
        warnings.append(f"yfinance only serves {interval} bars for the last {eff_period}, period reduced")

    df = data if data is not None else fetch_ohlcv(strategy.symbol, eff_period, interval)
    signal, sig_warnings = compute_signals(df, strategy)
    warnings.extend(sig_warnings)

    sim = simulate(
        df,
        signal,
        strategy.effective_stop_loss,
        strategy.effective_take_profit,
        fee_bps,
        initial_capital,
        interval,
    )
    equity = sim.equity
    trades = sim.trades
    if not trades:
        warnings.append("No trades were triggered in this period")

    wins = sum(1 for t in trades if t.pnl > 0)
    total_return = equity[-1] / 100 - 1
    close = df["Close"].to_numpy(dtype=float)

    epoch = df.index.tz_convert("UTC") if df.index.tz is not None else df.index.tz_localize("UTC")
    times = (epoch.asi8 // 1_000_000_000).tolist()
    curve = [
        EquityPoint(date=_fmt(ts, interval), time=int(t), value=round(float(v), 4))
        for ts, t, v in zip(df.index, times, equity, strict=True)
    ]

    return BacktestResult(
        strategy_id=strategy.id,
        symbol=strategy.symbol,
        ticker=to_ticker(strategy.symbol),
        period=eff_period,
        interval=interval,
        initial_capital=initial_capital,
        trades=trades,
        total_pnl=round(initial_capital * total_return, 2),
        total_return_pct=round(total_return * 100, 2),
        benchmark_return_pct=round((close[-1] / close[0] - 1) * 100, 2),
        sharpe_ratio=round(sharpe(equity, interval), 2),
        max_drawdown=round(max_drawdown(equity), 2),
        win_rate=round(wins / len(trades) * 100, 2) if trades else 0.0,
        total_trades=len(trades),
        bars=len(df),
        equity_curve=curve,
        warnings=warnings,
    )

import numpy as np
import pytest

from backtester import clamp_period, max_drawdown, run_backtest, sharpe, simulate, to_ticker
from models import Action, Indicator, Operator, ParsedStrategy, StrategyRule


def strategy(rules, **kw):
    return ParsedStrategy(
        name="t", text="t", rules=rules, symbol="TEST", timeframe="1d", parser="regex", confidence=1, **kw
    )


BUY_ABOVE_105 = StrategyRule(indicator=Indicator.PRICE, operator=Operator.CROSSES_ABOVE, value=105, action=Action.BUY)
SELL_BELOW_100 = StrategyRule(indicator=Indicator.PRICE, operator=Operator.CROSSES_BELOW, value=100, action=Action.SELL)


def test_signal_fills_next_open_no_lookahead(frame):
    closes = [100, 102, 104, 106, 110, 120, 99, 98]
    df = frame(closes)
    res = run_backtest(strategy([BUY_ABOVE_105, SELL_BELOW_100]), data=df, fee_bps=0)
    assert res.total_trades == 1
    t = res.trades[0]
    # cross happens on the close of bar 3 (106), so we buy the open of bar 4, which equals close of bar 3
    assert t.entry_price == 106
    # exit signal on close of bar 6 (99), filled at open of bar 7 (= 99)
    assert t.exit_price == 99
    assert t.exit_reason == "signal"
    assert res.total_return_pct == pytest.approx((99 / 106 - 1) * 100, abs=0.01)
    assert res.total_pnl == pytest.approx(100_000 * (99 / 106 - 1), abs=1)
    # equity is flat before entry
    assert res.equity_curve[0].value == 100 and res.equity_curve[3].value == 100


def test_stop_loss_and_gap_fill(frame):
    df = frame([100, 106, 107, 108, 90, 91])
    s = strategy([BUY_ABOVE_105], stop_loss_pct=2)
    res = run_backtest(s, data=df, fee_bps=0)
    t = res.trades[0]
    assert t.entry_price == 106 and t.exit_reason == "stop_loss"
    # bar 4 opens at 108 and trades down to ~89.9, stop at 103.88 is inside the bar
    assert t.exit_price == pytest.approx(106 * 0.98, abs=0.01)


def test_take_profit(frame):
    df = frame([100, 106, 107, 120, 121])
    res = run_backtest(strategy([BUY_ABOVE_105], take_profit_pct=5), data=df, fee_bps=0)
    t = res.trades[0]
    assert t.exit_reason == "take_profit"
    # bar 3 opens at 107 (below target 111.3) and its high crosses it
    assert t.exit_price == pytest.approx(106 * 1.05, abs=0.01)


def test_fees_reduce_return(frame):
    df = frame([100, 102, 104, 106, 110, 120, 99, 98])
    s = strategy([BUY_ABOVE_105, SELL_BELOW_100])
    free = run_backtest(s, data=df, fee_bps=0)
    paid = run_backtest(s, data=df, fee_bps=10)
    assert paid.total_return_pct < free.total_return_pct


def test_open_position_closes_at_end(frame):
    res = run_backtest(strategy([BUY_ABOVE_105]), data=frame([100, 106, 110, 115]), fee_bps=0)
    assert res.trades[-1].exit_reason == "end_of_data"
    assert res.trades[-1].exit_price == 115


def test_no_volume_rule_is_skipped_with_warning(frame):
    vol = StrategyRule(indicator=Indicator.VOLUME, operator=Operator.GREATER_THAN, value=2, action=Action.BUY)
    res = run_backtest(strategy([BUY_ABOVE_105, vol]), data=frame([100, 106, 110], volume=0), fee_bps=0)
    assert res.total_trades == 1
    assert any("no volume" in w for w in res.warnings)


def test_rsi_strategy_runs_on_random_walk(frame):
    rng = np.random.default_rng(1)
    closes = list(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 400))))
    rules = [
        StrategyRule(indicator=Indicator.RSI, operator=Operator.CROSSES_BELOW, value=35, action=Action.BUY),
        StrategyRule(indicator=Indicator.RSI, operator=Operator.CROSSES_ABOVE, value=65, action=Action.SELL),
    ]
    a = run_backtest(strategy(rules), data=frame(closes))
    b = run_backtest(strategy(rules), data=frame(closes))
    assert a.total_trades > 0
    assert a.model_dump(exclude={"strategy_id"}) == b.model_dump(exclude={"strategy_id"})  # deterministic
    assert 0 <= a.win_rate <= 100 and a.max_drawdown <= 0
    assert len(a.equity_curve) == 400


def test_metrics():
    eq = np.array([100, 110, 99, 120, 108])
    assert max_drawdown(eq) == pytest.approx(-10.0)
    assert sharpe(np.array([100.0, 100.0, 100.0]), "1d") == 0.0
    assert sharpe(np.array([100, 101, 102.5, 103]), "1d") > 0


def test_tickers_and_periods():
    assert to_ticker("NIFTY50") == "^NSEI"
    assert to_ticker("reliance") == "RELIANCE.NS"
    assert to_ticker("^GSPC") == "^GSPC"
    assert clamp_period("1y", "15m") == "60d"
    assert clamp_period("5y", "1h") == "2y"
    assert clamp_period("5y", "1d") == "5y"


def test_simulate_signal_on_last_bar_is_ignored(frame):
    df = frame([100, 101, 102])
    sim = simulate(df, np.array([0, 0, 1]), None, None, 0, 100_000, "1d")
    assert sim.trades == []

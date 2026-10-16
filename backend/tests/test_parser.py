import json

import pytest

import parser as p
from models import Action, Indicator, Operator


def rules_of(text):
    return [
        (r.indicator, r.period, r.operator, r.value, r.compare_to, r.compare_period, r.action)
        for r in p.parse_with_regex(text).rules
    ]


def test_spec_example_one():
    res = p.parse_with_regex(
        "Buy NIFTY when RSI(14) crosses below 30 and volume spikes 2x. Sell when RSI crosses above 70 or stop loss hits 2%."
    )
    got = {(r.indicator, r.operator, r.value, r.action) for r in res.rules}
    assert got == {
        (Indicator.RSI, Operator.CROSSES_BELOW, 30.0, Action.BUY),
        (Indicator.VOLUME, Operator.GREATER_THAN, 2.0, Action.BUY),
        (Indicator.RSI, Operator.CROSSES_ABOVE, 70.0, Action.SELL),
    }
    assert res.stop_loss_pct == 2.0
    assert res.entry_logic == "all" and res.exit_logic == "any"
    assert res.confidence == 1.0


def test_ma_crossover_and_trailing_percent_stop():
    text = "Buy NIFTY50 when RSI drops below 30 and 20 EMA crosses above 50 EMA. Sell when RSI exceeds 70 or 2% stop loss hits."
    res = p.parse_with_regex(text)
    assert (Indicator.EMA, 20, Operator.CROSSES_ABOVE, None, Indicator.EMA, 50, Action.BUY) in rules_of(text)
    assert res.stop_loss_pct == 2.0
    # two crossovers required on the same bar gets flagged
    assert any("same bar" in w for w in res.warnings)


def test_macd_price_ma_targets():
    res = p.parse_with_regex(
        "Buy when MACD crosses above signal line and price is above 200 SMA. Exit when MACD crosses below signal. "
        "Target 5%, stop loss 1.5%"
    )
    got = {(r.indicator, r.operator, r.compare_to, r.compare_period, r.action) for r in res.rules}
    assert (Indicator.MACD, Operator.CROSSES_ABOVE, None, None, Action.BUY) in got
    assert (Indicator.PRICE, Operator.GREATER_THAN, Indicator.SMA, 200, Action.BUY) in got
    assert (Indicator.MACD, Operator.CROSSES_BELOW, None, None, Action.SELL) in got
    assert res.take_profit_pct == 5.0 and res.stop_loss_pct == 1.5


def test_golden_cross_and_bollinger():
    assert rules_of("Buy on golden cross, sell on death cross") == [
        (Indicator.SMA, 50, Operator.CROSSES_ABOVE, None, Indicator.SMA, 200, Action.BUY),
        (Indicator.SMA, 50, Operator.CROSSES_BELOW, None, Indicator.SMA, 200, Action.SELL),
    ]
    got = rules_of("Buy when price touches the lower bollinger band. Sell at the upper band.")
    assert [(g[0], g[2], g[3], g[6]) for g in got] == [
        (Indicator.BB, Operator.LESS_THAN, 0.0, Action.BUY),
        (Indicator.BB, Operator.GREATER_THAN, 1.0, Action.SELL),
    ]


def test_unknown_clause_lowers_confidence():
    res = p.parse_with_regex("Buy when RSI is below 30 and the moon is full. Sell when RSI is above 70.")
    assert len(res.rules) == 2
    assert res.confidence < 1
    assert any("moon" in w for w in res.warnings)


def test_or_entry_logic():
    res = p.parse_with_regex("Buy when RSI is below 25 or price crosses above 20 EMA. Sell when RSI is above 75.")
    assert res.entry_logic == "any"


def test_detect_symbol():
    assert p.detect_symbol("buy banknifty on dips") == "BANKNIFTY"
    assert p.detect_symbol("Buy NIFTY when") == "NIFTY50"
    assert p.detect_symbol("buy when rsi < 30") is None


TEXT = "Buy when RSI drops below 35. Sell when RSI exceeds 65. 2% stop loss."


def _ai(rules, **extra):
    return json.dumps({"rules": rules, **extra})


def test_ai_accepts_faithful_output():
    raw = _ai(
        [
            {"indicator": "RSI", "operator": "CROSSES_BELOW", "value": 35, "action": "BUY"},
            {"indicator": "RSI", "operator": "GREATER_THAN", "value": 65, "action": "SELL"},
        ],
        stop_loss_pct=2,
    )
    rules, sl, _, reason = p._validate_ai_output(raw, TEXT)
    assert reason is None and len(rules) == 2 and sl == 2


@pytest.mark.parametrize(
    "bad, why",
    [
        ({"indicator": "RSI", "operator": "CROSSES_ABOVE", "value": 35, "action": "BUY"}, "flipped"),
        ({"indicator": "EMA", "operator": "CROSSES_BELOW", "value": 35, "action": "BUY"}, "invented an indicator"),
        ({"indicator": "RSI", "operator": "CROSSES_BELOW", "value": 25, "action": "BUY"}, "invented a number"),
        ({"indicator": "RSI", "operator": "SIDEWAYS", "value": 35, "action": "BUY"}, "failed validation"),
    ],
)
def test_ai_rejects_hallucinations(bad, why):
    rules, _, _, reason = p._validate_ai_output(_ai([bad]), TEXT)
    assert rules == [] and why in reason


def test_ai_invalid_json():
    _, _, _, reason = p._validate_ai_output("not json at all", TEXT)
    assert "invalid JSON" in reason


async def test_ollama_offline_falls_back(monkeypatch):
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    s = await p.parse_strategy(TEXT, "RELIANCE", "1d")
    assert s.parser == "regex"
    assert s.symbol == "RELIANCE"
    assert len(s.rules) == 2 and s.stop_loss_pct == 2
    assert "unreachable" in s.warnings[0]


async def test_ai_used_when_it_matches(monkeypatch):
    async def fake(_text):
        return _ai(
            [
                {"indicator": "RSI", "operator": "CROSSES_BELOW", "value": 35, "action": "BUY"},
                {"indicator": "RSI", "operator": "GREATER_THAN", "value": 65, "action": "SELL"},
            ]
        )

    monkeypatch.setattr(p, "_call_ollama", fake)
    s = await p.parse_strategy(TEXT)
    assert s.parser == "ai" and s.confidence == 1.0


def test_ai_junk_compare_to_is_dropped():
    raw = _ai(
        [
            {
                "indicator": "RSI",
                "operator": "CROSSES_BELOW",
                "value": 35,
                "compare_to": "65",
                "action": "BUY",
                "stop_loss_pct": 7,
            },
            {"indicator": "RSI", "operator": "GREATER_THAN", "value": 65, "compare_to": "70 RSI", "action": "SELL"},
        ]
    )
    rules, _, _, reason = p._validate_ai_output(raw, TEXT)
    assert reason is None and all(r.compare_to is None and r.stop_loss_pct is None for r in rules)


async def test_ai_disagreeing_with_regex_is_rejected(monkeypatch):
    async def fake(_text):
        # "is below 30" means LESS_THAN, not a cross
        return _ai(
            [
                {"indicator": "RSI", "operator": "CROSSES_BELOW", "value": 30, "action": "BUY"},
                {"indicator": "RSI", "operator": "GREATER_THAN", "value": 70, "action": "SELL"},
            ]
        )

    monkeypatch.setattr(p, "_call_ollama", fake)
    s = await p.parse_strategy("Buy when RSI is below 30. Sell when RSI is above 70.")
    assert s.parser == "regex" and "differently" in s.warnings[0]
    assert s.rules[0].operator == Operator.LESS_THAN

"""Natural language strategy parser.

Primary path: a local Ollama model (tinyllama by default) asked for JSON.
Fallback path: a deterministic regex parser that works fully offline.

Small local models hallucinate, so AI output is only accepted if every rule
validates, refers to indicators and numbers that actually appear in the text,
and covers at least as many conditions as the regex parser found. Otherwise
the regex result wins and the reason is reported in `warnings`.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field

import httpx
from pydantic import ValidationError

from models import Action, Indicator, Operator, ParsedStrategy, StrategyRule, Timeframe

log = logging.getLogger("throne.parser")

OLLAMA_TIMEOUT_S = float(os.getenv("OLLAMA_TIMEOUT", "45"))


def ollama_url() -> str:
    return os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")


def ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", "tinyllama")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def parse_strategy(text: str, symbol: str | None = None, timeframe: Timeframe = "1d") -> ParsedStrategy:
    regex = parse_with_regex(text)
    sym = (symbol or detect_symbol(text) or "NIFTY50").upper()

    ai_rules: list[StrategyRule] | None = None
    ai_reason: str | None = None
    try:
        raw = await _call_ollama(text)
        ai_rules, ai_sl, ai_tp, ai_reason = _validate_ai_output(raw, text)
        if ai_rules and not _agrees_with_regex(ai_rules, regex.rules):
            ai_rules, ai_reason = [], "AI read a condition differently from the deterministic parser, used regex parser"
    except (httpx.HTTPError, OSError) as exc:
        ai_reason = f"Ollama unreachable ({type(exc).__name__}), used regex parser"
    except Exception as exc:  # never let the LLM path crash a request
        log.exception("unexpected ollama failure")
        ai_reason = f"Ollama call failed ({type(exc).__name__}), used regex parser"

    use_ai = ai_rules is not None and len(ai_rules) > 0 and len(ai_rules) >= len(regex.rules)
    if ai_rules is not None and not use_ai and ai_reason is None:
        ai_reason = f"AI found {len(ai_rules)} usable rule(s) vs {len(regex.rules)} from regex, used regex parser"

    if use_ai:
        assert ai_rules is not None
        rules = ai_rules
        stop_loss = regex.stop_loss_pct or ai_sl
        take_profit = regex.take_profit_pct or ai_tp
        parser, confidence = "ai", 1.0
        warnings = list(regex.warnings_for_ai)
    else:
        rules = regex.rules
        stop_loss, take_profit = regex.stop_loss_pct, regex.take_profit_pct
        parser, confidence = "regex", regex.confidence
        warnings = list(regex.warnings)
        if ai_reason:
            warnings.insert(0, ai_reason)

    if not any(r.action == Action.BUY for r in rules):
        warnings.append("No entry (BUY) condition found, so the strategy will never open a position")
    if not any(r.action == Action.SELL for r in rules) and not stop_loss and not take_profit:
        warnings.append("No exit condition, stop loss or take profit found; positions close only at end of data")

    return ParsedStrategy(
        name=_name(rules, sym),
        text=text,
        rules=rules,
        entry_logic=regex.entry_logic,
        exit_logic=regex.exit_logic,
        stop_loss_pct=stop_loss,
        take_profit_pct=take_profit,
        symbol=sym,
        timeframe=timeframe,
        parser=parser,
        confidence=round(confidence, 2),
        warnings=warnings,
    )


def _name(rules: list[StrategyRule], symbol: str) -> str:
    seen: list[str] = []
    for r in rules:
        for ind in (r.indicator, r.compare_to):
            if ind is not None and ind != Indicator.PRICE and ind.value not in seen:
                seen.append(ind.value)
    return f"{' + '.join(seen) or 'Custom'} on {symbol}"


# ---------------------------------------------------------------------------
# Ollama path
# ---------------------------------------------------------------------------

PROMPT = """Extract trading rules from this strategy as JSON with fields: indicator, period, operator, value, compare_to, compare_period, action, stop_loss_pct, take_profit_pct.
indicator and compare_to are one of RSI, MACD, EMA, SMA, BB, VOLUME, PRICE. operator is one of CROSSES_ABOVE, CROSSES_BELOW, GREATER_THAN, LESS_THAN. action is BUY or SELL.
Use compare_to when one indicator is compared with another, for example 20 EMA crossing 50 EMA. VOLUME value is a multiple of average volume.
Strategy: {text}
Return only valid JSON: {{"rules": [...], "stop_loss_pct": number or null, "take_profit_pct": number or null}}"""


async def _call_ollama(text: str) -> str:
    payload = {
        "model": ollama_model(),
        "prompt": PROMPT.format(text=text),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0, "seed": 7, "num_predict": 512},
    }
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_S) as client:
        resp = await client.post(f"{ollama_url()}/api/generate", json=payload)
        resp.raise_for_status()
        return str(resp.json().get("response", ""))


async def ollama_online() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{ollama_url()}/api/tags")
            return resp.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def _extract_json(raw: str) -> object:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
    if not match:
        raise ValueError("no JSON in model output")
    return json.loads(match.group(1))


_IND_WORDS: dict[Indicator, tuple[str, ...]] = {
    Indicator.RSI: ("rsi", "relative strength"),
    Indicator.MACD: ("macd",),
    Indicator.EMA: ("ema", "exponential"),
    Indicator.SMA: ("sma", "dma", "moving average", " ma", "golden cross", "death cross"),
    Indicator.BB: ("bollinger", "band"),
    Indicator.VOLUME: ("volume",),
    Indicator.PRICE: ("price", "close", "ema", "sma", "dma", "moving average", "band"),
}


def _validate_ai_output(raw: str, text: str) -> tuple[list[StrategyRule], float | None, float | None, str | None]:
    """Returns (sane rules, stop loss, take profit, rejection reason or None)."""
    try:
        data = _extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        return [], None, None, "AI returned invalid JSON, used regex parser"

    sl = tp = None
    if isinstance(data, dict):
        sl = _num(data.get("stop_loss_pct"))
        tp = _num(data.get("take_profit_pct"))
        items = data.get("rules", [data] if "indicator" in data else [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    if not isinstance(items, list):
        return [], None, None, "AI JSON had no rule list, used regex parser"

    lowered = f" {text.lower()} "
    numbers = {float(n) for n in re.findall(r"\d+(?:\.\d+)?", lowered)}
    rules: list[StrategyRule] = []
    for item in items:
        if not isinstance(item, dict):
            return [], None, None, "AI JSON rule was not an object, used regex parser"
        item = _tidy_ai_rule(item)
        try:
            rule = StrategyRule.model_validate(item)
        except ValidationError:
            return [], None, None, "AI rule failed validation, used regex parser"
        for ind in (rule.indicator, rule.compare_to):
            if ind is not None and not _mentioned(ind, lowered):
                return [], None, None, f"AI invented an indicator ({ind.value}), used regex parser"
        if rule.value is not None and rule.value not in numbers and rule.value not in (0.0, 1.0):
            return [], None, None, f"AI invented a number ({rule.value:g}), used regex parser"
        if rule.indicator == Indicator.RSI and rule.value is not None and not 0 <= rule.value <= 100:
            return [], None, None, "AI produced an RSI level outside 0 to 100, used regex parser"
        if not _direction_ok(rule, lowered):
            return [], None, None, f"AI flipped the direction of a {rule.indicator.value} rule, used regex parser"
        # risk levels come from the strategy level fields, which are checked against "N%" below
        rules.append(rule.model_copy(update={"stop_loss_pct": None, "take_profit_pct": None}))
    percents = {float(n) for n in re.findall(r"(\d+(?:\.\d+)?)\s*%", lowered)}
    if sl is not None and sl not in percents:
        sl = None
    if tp is not None and tp not in percents:
        tp = None
    return rules, sl, tp, None


_UP_WORDS = ("above", "over", "exceed", "rise", "climb", "jump", ">", "greater", "higher", "more", "spike", "surge")
_DOWN_WORDS = ("below", "under", "drop", "fall", "dip", "slip", "<", "less", "lower")


def _direction_ok(rule: StrategyRule, lowered: str) -> bool:
    """For a rule with a numeric level, the words just before that number must agree with the operator."""
    if rule.value is None or rule.compare_to is not None:
        return True
    up = rule.operator in (Operator.CROSSES_ABOVE, Operator.GREATER_THAN)
    wanted, opposite = (_UP_WORDS, _DOWN_WORDS) if up else (_DOWN_WORDS, _UP_WORDS)
    for m in re.finditer(rf"(?<![\d.]){re.escape(f'{rule.value:g}')}(?![\d])", lowered):
        before = lowered[max(0, m.start() - 30) : m.start()]
        last_wanted = max((before.rfind(w) for w in wanted), default=-1)
        last_opposite = max((before.rfind(w) for w in opposite), default=-1)
        if last_wanted > last_opposite:
            return True
    return False


_VALID_INDICATORS = {i.value for i in Indicator}


def _tidy_ai_rule(item: dict[str, object]) -> dict[str, object]:
    """Drops fields small models fill with junk. Risk levels are taken from the strategy level fields."""
    out = {k: v for k, v in item.items() if k not in ("stop_loss_pct", "take_profit_pct")}
    target = out.get("compare_to")
    if isinstance(target, str) and target.strip().upper() not in _VALID_INDICATORS:
        target = None
    if target is None or target == "":
        out.pop("compare_to", None)
        out.pop("compare_period", None)
    return out


def _agrees_with_regex(ai_rules: list[StrategyRule], regex_rules: list[StrategyRule]) -> bool:
    """Where both parsers read the same condition, they must agree on the operator."""
    for a in ai_rules:
        for r in regex_rules:
            same_target = (a.compare_to, a.compare_period, a.value) == (r.compare_to, r.compare_period, r.value)
            if a.indicator == r.indicator and a.period == r.period and a.action == r.action and same_target:
                if a.operator != r.operator:
                    return False
    return True


def _mentioned(ind: Indicator, lowered: str) -> bool:
    return any(w in lowered for w in _IND_WORDS[ind])


def _num(v: object) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        return float(v)
    return None


# ---------------------------------------------------------------------------
# Regex path
# ---------------------------------------------------------------------------

NUM = r"(\d+(?:\.\d+)?)"

_OP_PHRASES: dict[Operator, tuple[str, ...]] = {
    Operator.CROSSES_ABOVE: (
        "crosses back above",
        "crosses above",
        "crossed above",
        "cross above",
        "crosses over",
        "rises above",
        "breaks above",
        "moves above",
        "goes above",
        "climbs above",
        "jumps above",
        "rises over",
        "crosses into",
    ),
    Operator.CROSSES_BELOW: (
        "crosses back below",
        "crosses below",
        "crossed below",
        "cross below",
        "crosses under",
        "drops below",
        "falls below",
        "dips below",
        "breaks below",
        "moves below",
        "goes below",
        "slips below",
        "drops under",
        "falls under",
        "dips under",
    ),
    Operator.GREATER_THAN: (
        "is greater than",
        "greater than",
        "is higher than",
        "higher than",
        "more than",
        "is above",
        "stays above",
        "exceeds",
        "above",
        "over",
        ">=",
        ">",
    ),
    Operator.LESS_THAN: (
        "is less than",
        "less than",
        "is lower than",
        "lower than",
        "is below",
        "stays below",
        "below",
        "under",
        "<=",
        "<",
    ),
}
_PHRASE_TO_OP: dict[str, Operator] = {p: op for op, ps in _OP_PHRASES.items() for p in ps}
OP = "(" + "|".join(re.escape(p) for p in sorted(_PHRASE_TO_OP, key=len, reverse=True)) + ")"

MA = r"(?:\d+\s*-?\s*(?:day\s+|period\s+|bar\s+)?(?:ema|sma|dma|ma)\b|(?:ema|sma|dma)\s*\(?\s*\d+\s*\)?|(?:ema|sma|dma|ma)\b)"

_BUY_KW = re.compile(r"\b(buy|go long|enter(?: a)? long|enter|entry)\b")
_SELL_KW = re.compile(r"\b(sell|exit|square off|close (?:the |my )?position|book profits?|get out)\b")

_SYMBOLS = {
    "banknifty": "BANKNIFTY",
    "bank nifty": "BANKNIFTY",
    "finnifty": "FINNIFTY",
    "nifty50": "NIFTY50",
    "nifty 50": "NIFTY50",
    "nifty": "NIFTY50",
    "sensex": "SENSEX",
}


def detect_symbol(text: str) -> str | None:
    lowered = text.lower()
    for key in sorted(_SYMBOLS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", lowered):
            return _SYMBOLS[key]
    return None


@dataclass
class RegexResult:
    rules: list[StrategyRule] = field(default_factory=list)
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    entry_logic: str = "all"
    exit_logic: str = "any"
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    warnings_for_ai: list[str] = field(default_factory=list)


def _ma(token: str) -> tuple[Indicator, int | None]:
    kind = Indicator.EMA if "ema" in token else Indicator.SMA
    digits = re.search(r"\d+", token)
    return kind, int(digits.group()) if digits else None


def _op(phrase: str) -> Operator:
    return _PHRASE_TO_OP[phrase.strip()]


def _blank(s: str, m: re.Match[str]) -> str:
    return s[: m.start()] + " " * (m.end() - m.start()) + s[m.end() :]


def _normalize(text: str) -> str:
    s = text.lower()
    s = s.replace("×", "x").replace("–", "-")
    s = re.sub(r"\s+", " ", s)
    return s


def _extract_risk(s: str, res: RegexResult) -> str:
    sl_patterns = [
        rf"(?:stop[\s-]*loss|stoploss|\bsl\b)\D{{0,25}}?{NUM}\s*%",
        rf"{NUM}\s*%\s*(?:stop[\s-]*loss|stoploss|\bsl\b|stop\b)",
    ]
    tp_patterns = [
        rf"(?:take[\s-]*profit|profit[\s-]*target|\btarget\b|\btp\b)\D{{0,25}}?{NUM}\s*%",
        rf"{NUM}\s*%\s*(?:take[\s-]*profit|profit|target|gain)",
    ]
    for pats, attr in ((sl_patterns, "stop_loss_pct"), (tp_patterns, "take_profit_pct")):
        for pat in pats:
            m = re.search(pat, s)
            if m:
                val = float(m.group(1))
                if 0 < val < 100:
                    setattr(res, attr, val)
                s = _blank(s, m)
                break
    return s


def _segments(s: str) -> list[tuple[Action, str]]:
    marks: list[tuple[int, int, Action]] = []
    for m in _BUY_KW.finditer(s):
        marks.append((m.start(), m.end(), Action.BUY))
    for m in _SELL_KW.finditer(s):
        marks.append((m.start(), m.end(), Action.SELL))
    marks.sort()
    out: list[tuple[Action, str]] = []
    for i, (_start, end, action) in enumerate(marks):
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(s)
        out.append((action, s[end:stop]))
    return out


def _conditions(seg: str, action: Action) -> tuple[list[StrategyRule], str]:
    """Extract every condition in a segment. Returns rules and the unmatched leftovers."""
    rules: list[StrategyRule] = []

    def add(**kw: object) -> None:
        try:
            rules.append(StrategyRule(action=action, **kw))  # type: ignore[arg-type]
        except ValidationError:
            pass

    # golden / death cross
    for m in list(re.finditer(r"golden cross", seg)):
        add(
            indicator=Indicator.SMA,
            period=50,
            operator=Operator.CROSSES_ABOVE,
            compare_to=Indicator.SMA,
            compare_period=200,
        )
        seg = _blank(seg, m)
    for m in list(re.finditer(r"death cross", seg)):
        add(
            indicator=Indicator.SMA,
            period=50,
            operator=Operator.CROSSES_BELOW,
            compare_to=Indicator.SMA,
            compare_period=200,
        )
        seg = _blank(seg, m)

    # MACD vs signal line / zero, and named crossovers
    for m in list(re.finditer(rf"macd(?:\s+line)?\s*{OP}\s*(?:the\s+)?(signal(?:\s+line)?|zero(?:\s+line)?|0)", seg)):
        target = m.group(2)
        value = None if target.startswith("signal") else 0.0
        add(indicator=Indicator.MACD, operator=_op(m.group(1)), value=value)
        seg = _blank(seg, m)
    for m in list(
        re.finditer(r"(bullish|bearish)?\s*macd\s*(bullish|bearish)?\s*(?:cross\s*over|crossover|cross)", seg)
    ):
        mood = m.group(1) or m.group(2) or ("bullish" if action == Action.BUY else "bearish")
        op = Operator.CROSSES_ABOVE if mood == "bullish" else Operator.CROSSES_BELOW
        add(indicator=Indicator.MACD, operator=op, value=None)
        seg = _blank(seg, m)

    # moving average vs moving average
    for m in list(re.finditer(rf"({MA})\s*(?:line\s*)?{OP}\s*(?:the\s+)?({MA})", seg)):
        k1, p1 = _ma(m.group(1))
        k2, p2 = _ma(m.group(3))
        add(indicator=k1, period=p1, operator=_op(m.group(2)), compare_to=k2, compare_period=p2)
        seg = _blank(seg, m)

    # Bollinger bands, expressed through %B (0 = lower band, 1 = upper band)
    bb = rf"(?:(?:price|close)\s+)?(?:{OP}|touches|touch|hits|tags|reaches|at|near)\s*(?:the\s+)?(?:bollinger\s+)?(lower|upper)\s+(?:bollinger\s+)?band"
    for m in list(re.finditer(bb, seg)):
        band = m.group(2)
        level = 0.0 if band == "lower" else 1.0
        if m.group(1):
            op = _op(m.group(1))
        else:
            op = Operator.LESS_THAN if band == "lower" else Operator.GREATER_THAN
        add(indicator=Indicator.BB, operator=op, value=level)
        seg = _blank(seg, m)

    # price vs moving average
    for m in list(re.finditer(rf"(?:(?:price|close|closing price|it)\s+)?{OP}\s*(?:the\s+)?({MA})", seg)):
        kind, period = _ma(m.group(2))
        add(indicator=Indicator.PRICE, operator=_op(m.group(1)), compare_to=kind, compare_period=period)
        seg = _blank(seg, m)

    # price vs level
    for m in list(re.finditer(rf"(?:price|close|closing price)\s*{OP}\s*{NUM}(?!\s*%)", seg)):
        add(indicator=Indicator.PRICE, operator=_op(m.group(1)), value=float(m.group(2)))
        seg = _blank(seg, m)

    # RSI
    rsi = rf"rsi\s*(?:\(\s*(\d+)\s*\)|(\d+)(?=\s+[a-z<>]))?\s*(?:period\s+|reading\s+|value\s+|level\s+)?(?:is\s+|goes\s+)?{OP}\s*{NUM}"
    for m in list(re.finditer(rsi, seg)):
        period = int(m.group(1) or m.group(2) or 14)
        add(indicator=Indicator.RSI, period=period, operator=_op(m.group(3)), value=float(m.group(4)))
        seg = _blank(seg, m)
    for m in list(
        re.finditer(r"rsi\s*(?:\(\s*(\d+)\s*\))?\s*(?:is\s+|becomes\s+|turns\s+|gets\s+)?(oversold|overbought)", seg)
    ):
        period = int(m.group(1) or 14)
        if m.group(2) == "oversold":
            add(indicator=Indicator.RSI, period=period, operator=Operator.LESS_THAN, value=30.0)
        else:
            add(indicator=Indicator.RSI, period=period, operator=Operator.GREATER_THAN, value=70.0)
        seg = _blank(seg, m)

    # volume spikes, as a multiple of the 20 bar average
    vol_patterns = [
        rf"volume\s+(?:spikes?|surges?|jumps?|rises|increases|is|goes|grows|expands)?\s*(?:by\s+|to\s+|above\s+|over\s+|more than\s+|>\s*)?{NUM}\s*(?:x\b|times\b)(?:\s*(?:the\s+)?(?:average|avg|normal|usual)(?:\s+volume)?)?",
        rf"{NUM}\s*(?:x\b|times\b)\s*(?:the\s+)?(?:average\s+|avg\s+|normal\s+)?volume",
    ]
    for pat in vol_patterns:
        for m in list(re.finditer(pat, seg)):
            add(indicator=Indicator.VOLUME, operator=Operator.GREATER_THAN, value=float(m.group(1)))
            seg = _blank(seg, m)
    for m in list(
        re.finditer(
            r"(?:volume\s+(?:spikes?|surges?|jumps?)|(?:high|heavy|rising)\s+volume|above[\s-]average\s+volume)", seg
        )
    ):
        mult = 1.0 if "average" in m.group(0) else 2.0
        add(indicator=Indicator.VOLUME, operator=Operator.GREATER_THAN, value=mult)
        seg = _blank(seg, m)

    return rules, seg


_FILLER = re.compile(
    r"\b(when|whenever|if|once|then|the|a|an|and|or|also|it|its|is|on|of|at|to|my|position|"
    r"nifty50|nifty|banknifty|bank|sensex|finnifty|stock|shares?|index|price|close|hits|"
    r"triggers|gets|hit|daily|chart|candle|both|either|after|with)\b|[,.;:()%]"
)


def _leftover_clauses(seg: str) -> list[str]:
    out = []
    for clause in re.split(r"\band\b|\bor\b|,|;|\.", seg):
        stripped = _FILLER.sub(" ", clause)
        if re.search(r"[a-z]{3,}|\d", stripped):
            out.append(re.sub(r"\s+", " ", clause).strip())
    return out


def _logic(seg_texts: list[str], default: str) -> tuple[str, bool]:
    joined = " ".join(seg_texts)
    has_and = re.search(r"\band\b", joined) is not None
    has_or = re.search(r"\bor\b", joined) is not None
    if has_or and not has_and:
        return "any", False
    if has_and and not has_or:
        return "all", False
    return default, has_and and has_or


def parse_with_regex(text: str) -> RegexResult:
    res = RegexResult()
    s = _extract_risk(_normalize(text), res)

    segments = _segments(s)
    if not segments:
        segments = [(Action.BUY, s)]
        res.warnings.append("No buy or sell keyword found, so all conditions were treated as entry rules")

    matched = 0
    unmatched: list[str] = []
    seg_text: dict[Action, list[str]] = {Action.BUY: [], Action.SELL: []}
    for action, seg in segments:
        seg_text[action].append(seg)
        rules, leftover = _conditions(seg, action)
        res.rules.extend(rules)
        matched += len(rules)
        unmatched.extend(_leftover_clauses(leftover))

    res.entry_logic, entry_mixed = _logic(seg_text[Action.BUY], "all")
    res.exit_logic, exit_mixed = _logic(seg_text[Action.SELL], "any")
    if entry_mixed:
        res.warnings.append("Entry mixes AND with OR; treated as all conditions required")
    if exit_mixed:
        res.warnings.append("Exit mixes AND with OR; treated as any condition triggers")

    for clause in unmatched:
        res.warnings.append(f'Could not understand: "{clause}"')
        res.warnings_for_ai.append(f'Regex parser could not confirm: "{clause}"')

    for action, logic in ((Action.BUY, res.entry_logic), (Action.SELL, res.exit_logic)):
        crosses = [
            r
            for r in res.rules
            if r.action == action and r.operator in (Operator.CROSSES_ABOVE, Operator.CROSSES_BELOW)
        ]
        if logic == "all" and len(crosses) > 1:
            res.warnings.append(
                f"{action.value} needs {len(crosses)} crossovers on the same bar, which rarely happens; "
                "consider phrasing one as 'is above' or 'is below'"
            )
            res.warnings_for_ai.append(res.warnings[-1])

    total = matched + len(unmatched)
    res.confidence = matched / total if total else 0.0
    return res

"""Multi-call trade ideas: several intraday calls and staged delivery (positional) calls.

Delivery calls come from the daily chart (e.g. an early W / double bottom); intraday calls come from
the intraday chart's S/R and patterns, sized down when they trade against the daily bias.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import pandas as pd

from .indicators import atr, ema
from .levels import Level, build_levels
from .patterns import Pattern, detect_patterns
from .similarity import find_analogs
from .trade import build_plan

BULL_REVERSALS = ("Double Bottom", "Inverse Head", "Falling Wedge", "Ascending Triangle", "Resistance Breakout")


@dataclass
class Call:
    name: str
    horizon: str  # intraday | delivery
    side: str  # BUY | SELL | EXIT
    style: str
    entry: float
    entry_type: str
    stop: float
    targets: list[float]
    rr: list[float]
    qty: int
    position_value: float
    risk_amount: float
    when: str
    with_trend: bool = True
    notes: list[str] = field(default_factory=list)


@dataclass
class Context:
    price: float
    atr: float
    levels: list[Level]
    patterns: list[Pattern]
    score: float
    trend: float


def context(df: pd.DataFrame, interval: str) -> Context:
    price, a = float(df["close"].iloc[-1]), float(atr(df).iloc[-1])
    e20, e50 = ema(df["close"], 20).iloc[-1], ema(df["close"], 50).iloc[-1]
    trend = (0.5 if price > e20 else -0.5) + (0.5 if e20 > e50 else -0.5)
    levels = build_levels(df)
    pats = detect_patterns(df, levels)
    w, h = (30, 10) if interval in ("1d", "1wk") else (40, 20)
    _, stats = find_analogs(df, w, h, current_patterns=[p.name for p in pats])
    return Context(price, a, levels, pats, build_plan(price, a, pats, levels, stats, trend).score, trend)


def _targets(s: int, entry: float, risk: float, prices: list[float]) -> list[float]:
    ahead = sorted((x for x in prices if s * (x - entry) > 0), key=lambda x: s * (x - entry))
    t1 = next((x for x in ahead if s * (x - entry) >= risk), entry + s * 1.5 * risk)
    t2 = next((x for x in ahead if s * (x - t1) > 0.3 * risk), entry + s * max(2.5 * risk, abs(t1 - entry) + risk))
    return [t1, t2]


def _make(name, horizon, side, style, entry, entry_type, stop, prices, when, capital, risk_pct,
          scale=1.0, with_trend=True, notes=None, targets=None, early=False) -> Call | None:
    s = 1 if side == "BUY" else -1
    entry, stop = round(float(entry), 2), round(float(stop), 2)
    risk = s * (entry - stop)
    if risk <= 0:
        return None
    t = targets or _targets(s, entry, risk, prices)
    if any(s * (x - entry) <= 0 for x in t):
        return None
    rr = [round(float(s * (x - entry) / risk), 2) for x in t]
    if rr[0] < 1.0 and not (early and rr[-1] >= 2.0):  # early entries may have a near T1 if the full target pays 2R+
        return None
    notes = list(notes or [])
    if rr[0] < 1.0:
        notes.append(f"T1 is only {rr[0]}R: treat it as a partial-profit / stop-to-cost level, the payoff is in T2.")
    if not with_trend:
        scale *= 0.5
        notes.append("Counter to the daily bias: half size, take profits quickly.")
    risk_amt = capital * risk_pct / 100 * scale
    qty = min(math.floor(risk_amt / risk), math.floor(capital / entry))
    if qty < 1:
        notes.append("Risk budget is below one unit's risk: raise capital / risk %, or use a smaller lot or instrument.")
    r2 = lambda x: round(float(x), 2)  # noqa: E731
    return Call(name, horizon, side, style, entry, entry_type, stop, [r2(x) for x in t], rr, int(qty),
                r2(qty * entry), r2(risk_amt), when, with_trend, notes)


def intraday_calls(c: Context, bias: str, capital: float, risk_pct: float) -> list[Call]:
    p, a = c.price, c.atr
    sup = sorted((x for x in c.levels if x.kind == "support"), key=lambda x: p - x.price)
    res = sorted((x for x in c.levels if x.kind == "resistance"), key=lambda x: x.price - p)
    up_ok, dn_ok = bias != "bearish", bias != "bullish"
    sq = "Intraday: square off before the close."
    out: list[Call | None] = []

    for pat in c.patterns:  # live pattern triggers first
        if pat.bias == "neutral" or pat.trigger is None or pat.status != "forming":
            continue
        s = 1 if pat.bias == "bullish" else -1
        if not 0 < s * (pat.trigger - p) <= 1.5 * a:
            continue
        entry = pat.trigger + s * 0.1 * a
        stop = pat.invalidation if pat.invalidation is not None and 0.75 * a <= s * (entry - pat.invalidation) <= 3 * a else entry - s * 1.5 * a
        out.append(_make(f"{pat.name} trigger", "intraday", "BUY" if s == 1 else "SELL", "pattern", entry,
                         "stop order", stop, [x.price for x in (res if s == 1 else sup)], f"Act only when price trades through {entry:.2f}. {sq}",
                         capital, risk_pct, with_trend=(up_ok if s == 1 else dn_ok),
                         targets=[pat.target] if False else None, notes=[pat.description]))
        break

    if sup:
        s0 = sup[0]
        entry = p if p - s0.price <= 0.3 * a else s0.price + 0.1 * a
        out.append(_make("Pullback buy at support", "intraday", "BUY", "pullback", entry,
                         "market (at support)" if entry == p else "limit order", s0.low - 0.3 * a,
                         [x.price for x in res], f"Buy a dip into {s0.price:.2f}; skip if a 15m candle closes below {s0.low:.2f} first. {sq}",
                         capital, risk_pct, with_trend=up_ok, notes=[f"Support strength {s0.strength}."]))
    if res and res[0].price - p <= 2 * a:
        r0 = res[0]
        out.append(_make("Breakout buy above resistance", "intraday", "BUY", "breakout", r0.price + 0.1 * a,
                         "stop order", r0.price - 0.6 * a, [x.price for x in res[1:]],
                         f"Buy only on a close above {r0.high:.2f} with rising volume. {sq}", capital, risk_pct, with_trend=up_ok,
                         notes=[f"Resistance strength {r0.strength}."]))
        out.append(_make("Fade short at resistance", "intraday", "SELL", "fade", r0.price - 0.1 * a,
                         "limit order", r0.high + 0.3 * a, [x.price for x in sup],
                         f"Short a rejection (upper-wick candle) at {r0.price:.2f}. {sq}", capital, risk_pct, with_trend=dn_ok))
    if sup and p - sup[0].price <= 2 * a:
        s0 = sup[0]
        out.append(_make("Breakdown short below support", "intraday", "SELL", "breakdown", s0.price - 0.1 * a,
                         "stop order", s0.price + 0.6 * a, [x.price for x in sup[1:]],
                         f"Short only on a close below {s0.low:.2f}. {sq}", capital, risk_pct, with_trend=dn_ok))

    calls = [x for x in out if x is not None]
    calls.sort(key=lambda x: (not x.with_trend, -x.rr[0]))
    return calls[:4]


def delivery_calls(c: Context, capital: float, risk_pct: float) -> tuple[str, list[Call], list[str]]:
    p, a = c.price, c.atr
    res_prices = [x.price for x in c.levels if x.kind == "resistance"]
    sup = sorted((x for x in c.levels if x.kind == "support"), key=lambda x: p - x.price)
    hold = "Delivery: hold days to weeks; manage on daily closes."
    bull = [x for x in c.patterns if x.bias == "bullish" and x.confidence >= 50 and x.trigger and x.status != "failed"
            and x.name.startswith(BULL_REVERSALS) and x.target]
    bear = [x for x in c.patterns if x.bias == "bearish" and x.confidence >= 55 and x.status == "confirmed"]

    if bull and not bear:
        pat = max(bull, key=lambda x: x.confidence)
        n, inval = pat.trigger, pat.invalidation
        counter = c.trend < 0
        calls: list[Call | None] = []
        if pat.status == "forming" and p < n:
            calls.append(_make(f"Starter: early entry on {pat.name}", "delivery", "BUY", "starter", p, "market / on daily close",
                               inval, res_prices, f"Early entry while the pattern is still forming; exit if a daily close breaks {inval:.2f}. {hold}",
                               capital, risk_pct, scale=0.5, targets=[n, pat.target], early=True,
                               notes=["Half size: neckline not yet broken.", pat.description] + (["Pattern is a reversal against a downtrend; keep size small."] if counter else [])))
            conf_entry, conf_stop = n + 0.1 * a, max(inval, n - 1.2 * a)
            calls.append(_make("Add: neckline breakout confirmation", "delivery", "BUY", "confirmation", conf_entry, "buy on daily close above",
                               conf_stop, res_prices, f"Add the other half only after a daily close above {n:.2f}. {hold}",
                               capital, risk_pct, scale=0.5, targets=[pat.target, pat.target + 0.5 * (pat.target - n)]))
        else:
            calls.append(_make(f"Entry: {pat.name} confirmed", "delivery", "BUY", "confirmation", p, "market / on daily close",
                               max(inval, n - 1.2 * a), res_prices, f"Neckline {n:.2f} is broken; a retest of it is the lower-risk entry. {hold}",
                               capital, risk_pct, targets=[pat.target, pat.target + 0.5 * abs(pat.target - n)]))
        calls = [x for x in calls if x]
        if calls:
            return f"{pat.name} ({pat.status}, {pat.confidence}%) on the daily chart: early reversal setup.", calls, [
                f"Trade plan fails on a daily close below {inval:.2f}."]
    if bear:
        pat = bear[0]
        return f"{pat.name} confirmed on daily: bearish. Avoid fresh delivery buys.", [], [
            "Exit or trail stops on existing longs; shorting in delivery isn't possible in cash equity (use futures/options if you short).",
            f"Pattern target {pat.target:.2f}." if pat.target else ""]
    if c.score >= 0.2:
        calls = []
        if sup:
            s0 = sup[0]
            calls.append(_make("Pullback buy at daily support", "delivery", "BUY", "pullback", p if p - s0.price <= 0.5 * a else s0.price + 0.1 * a,
                               "limit order", s0.low - 0.5 * a, res_prices, f"Buy dips toward {s0.price:.2f}. {hold}", capital, risk_pct))
        r0 = min((x for x in c.levels if x.kind == "resistance"), key=lambda x: x.price - p, default=None)
        if r0:
            calls.append(_make("Breakout buy above daily resistance", "delivery", "BUY", "breakout", r0.price + 0.1 * a, "buy on daily close above",
                               r0.price - 1.0 * a, res_prices, f"Buy on a daily close above {r0.price:.2f}. {hold}", capital, risk_pct))
        calls = [x for x in calls if x]
        return "Bullish daily bias.", calls, []
    r0 = min((x for x in c.levels if x.kind == "resistance"), key=lambda x: x.price - p, default=None)
    s0 = sup[0] if sup else None
    watch = [f"Watch: daily close above {r0.price:.2f} turns this bullish." if r0 else "", f"Daily close below {s0.low:.2f} turns it bearish." if s0 else ""]
    return "No delivery edge yet: wait for a breakout or a clearer pattern.", [], [w for w in watch if w]


def build_calls(daily: pd.DataFrame, intra: pd.DataFrame | None, intra_interval: str, capital: float, risk_pct: float, index: bool = False) -> dict:
    d = context(daily, "1d")
    view, dcalls, dnotes = delivery_calls(d, capital, risk_pct)
    bias = "bullish" if d.score >= 0.2 or any(c.side == "BUY" for c in dcalls) else "bearish" if d.score <= -0.2 else "neutral"
    icalls: list[Call] = []
    ictx = None
    if intra is not None and len(intra) >= 120:
        ictx = context(intra, intra_interval)
        icalls = intraday_calls(ictx, bias, capital, risk_pct)
    notes = [n for n in dnotes if n]
    if index:
        notes.append("Index: not directly tradable. Use index futures/options or an index ETF; quantities are notional units.")
    return {
        "daily_bias": bias, "daily_score": d.score, "delivery_view": view,
        "delivery": [asdict(x) for x in dcalls], "intraday": [asdict(x) for x in icalls],
        "intraday_interval": intra_interval if ictx else None, "notes": notes,
    }

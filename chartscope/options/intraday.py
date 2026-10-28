"""Intraday context on the underlying and the option-trade setups built from it."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from ..calls import _targets
from ..indicators import atr, ema, rsi
from ..levels import Level, build_levels
from ..patterns import detect_patterns
from .profile import Profile, open_location, tpo_profile


@dataclass
class DayContext:
    ts: datetime  # end of the last completed 5m bar
    spot: float
    atr: float  # 15-minute ATR: sizing unit for stops/targets
    vwap: float
    vwap_is_volume_weighted: bool
    or_high: float | None
    or_low: float | None
    day_high: float
    day_low: float
    prev_high: float | None
    prev_low: float | None
    prev_close: float | None
    gap_pct: float
    ema9: float
    ema21: float
    rsi: float
    trend: str  # up | down | flat
    bias_score: float  # -1..+1
    daily_bias: str
    levels: list[Level] = field(default_factory=list)
    patterns: list = field(default_factory=list)
    expected_move: float | None = None  # 1-day 1-sigma from VIX, in points
    profile: Profile | None = None  # previous session value area
    open_loc: str = "unknown"
    day_open: float = 0.0
    ib_high: float | None = None  # first-hour (initial balance) range, once complete
    ib_low: float | None = None
    efficiency: float = 0.0  # Kaufman efficiency ratio of the last 24 bars (1 = clean trend, 0 = chop)


@dataclass
class Idea:
    setup: str
    side: str  # LONG (buy CE) | SHORT (buy PE)
    mode: str  # market | stop | limit
    entry: float
    stop: float
    targets: list[float]
    confidence: int
    aligned: bool
    rationale: list[str]
    valid_minutes: int = 30
    family: str = ""


def _atr15(df5: pd.DataFrame) -> float:
    d = df5.iloc[-900:]
    r = d.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    return float(atr(r).iloc[-1]) if len(r) > 5 else float(atr(d).iloc[-1] * 1.7)


def session_vwap(day: pd.DataFrame) -> tuple[float, bool]:
    typical = (day["high"] + day["low"] + day["close"]) / 3
    vol = day["volume"]
    if vol.sum() > 0:
        return float((typical * vol).sum() / vol.sum()), True
    return float(typical.mean()), False  # Yahoo gives no volume for indices: equal-weight fallback


def build_context(df5: pd.DataFrame, daily_bias: str, vix: float | None) -> DayContext:
    last_date = df5.index[-1].date()
    day = df5[df5.index.date == last_date]
    prev = df5[df5.index.date < last_date]
    pday = prev[prev.index.date == prev.index[-1].date()] if len(prev) else None
    spot = float(day["close"].iloc[-1])
    a = _atr15(df5)
    vwap, real = session_vwap(day)
    e9, e21 = float(ema(df5["close"], 9).iloc[-1]), float(ema(df5["close"], 21).iloc[-1])
    trend = "up" if (e9 > e21 and spot > vwap) else "down" if (e9 < e21 and spot < vwap) else "flat"
    orh = orl = None
    if len(day) >= 3:
        orh, orl = float(day["high"].iloc[:3].max()), float(day["low"].iloc[:3].min())
    score = {"bullish": 0.4, "bearish": -0.4}.get(daily_bias, 0.0) + {"up": 0.4, "down": -0.4}.get(trend, 0.0)
    if orh is not None:
        score += 0.2 if spot > orh else -0.2 if spot < orl else 0.0
    levels = build_levels(df5.iloc[-400:])
    ctx = DayContext(
        ts=(day.index[-1] + pd.Timedelta(minutes=5)).to_pydatetime(), spot=spot, atr=a, vwap=vwap, vwap_is_volume_weighted=real,
        or_high=orh, or_low=orl, day_high=float(day["high"].max()), day_low=float(day["low"].min()),
        prev_high=float(pday["high"].max()) if pday is not None and len(pday) else None,
        prev_low=float(pday["low"].min()) if pday is not None and len(pday) else None,
        prev_close=float(pday["close"].iloc[-1]) if pday is not None and len(pday) else None,
        gap_pct=0.0, ema9=e9, ema21=e21, rsi=float(rsi(df5["close"]).iloc[-1]), trend=trend,
        bias_score=max(-1.0, min(1.0, score)), daily_bias=daily_bias, levels=levels,
        patterns=detect_patterns(df5.iloc[-150:], levels, lookback=120),
        expected_move=(spot * vix / 100 / np.sqrt(252)) if vix else None,
    )
    ctx.day_open = float(day["open"].iloc[0])
    ctx.profile = tpo_profile(pday) if pday is not None else None
    ctx.open_loc = open_location(ctx.day_open, ctx.profile)
    if len(day) >= 12:
        ctx.ib_high, ctx.ib_low = float(day["high"].iloc[:12].max()), float(day["low"].iloc[:12].min())
    c = df5["close"].iloc[-25:].to_numpy()
    path = np.abs(np.diff(c)).sum()
    ctx.efficiency = float(abs(c[-1] - c[0]) / path) if path > 0 else 0.0
    if ctx.prev_close:
        ctx.gap_pct = round((float(day["open"].iloc[0]) / ctx.prev_close - 1) * 100, 2)
    return ctx


_RAW = False  # study mode: keep counter-bias ideas so their edge can be measured too


def _mk(setup, s, mode, entry, stop, prices, conf, why, ctx, valid=30, family="") -> Idea | None:
    a = ctx.atr
    risk = s * (entry - stop)
    if not (0.6 * a <= risk <= 2.5 * a):
        return None
    aligned = s * ctx.bias_score >= 0.2  # informational: trend alignment did not predict intraday outcomes in tests
    conf = FAMILY_CONF.get(family, conf)
    t = _targets(s, entry, risk, prices)
    return Idea(setup, "LONG" if s == 1 else "SHORT", mode, float(entry), float(stop), [float(x) for x in t],
                int(max(0, min(95, conf))), aligned, why, valid, family)


def _linfit(y: np.ndarray) -> tuple[float, float]:
    """slope per bar and R^2 of a straight-line fit."""
    x = np.arange(len(y))
    if len(y) < 3 or np.ptp(y) == 0:
        return 0.0, 0.0
    k, c = np.polyfit(x, y, 1)
    resid = y - (k * x + c)
    ss = ((y - y.mean()) ** 2).sum()
    return float(k), float(1 - (resid ** 2).sum() / ss) if ss > 0 else 0.0


def _orb(ctx, day, p, a, res, sup):
    out = []
    if ctx.or_high is None or len(day) < 3:
        return out
    w = ctx.or_high - ctx.or_low
    if not 0.4 * a <= w <= 3.5 * a:
        return out
    closes = day["close"].iloc[-3:]
    for s, lvl in ((1, ctx.or_high), (-1, ctx.or_low)):
        trig = lvl + s * 0.1 * a
        broke = bool((s * (closes - lvl) > 0).any())
        if s * (p - trig) < 0 and s * (trig - p) <= 1.2 * a:
            mode, entry = "stop", trig
        elif 0 <= s * (p - trig) <= 0.5 * a and broke:
            mode, entry = "market", p
        else:
            continue
        risk = min(max(0.5 * w, 0.9 * a), 1.8 * a)
        why = [f"Opening range {ctx.or_low:.0f}-{ctx.or_high:.0f}; {'above' if s == 1 else 'below'} {lvl:.0f} is a breakout."]
        out.append(_mk("Opening range breakout", s, mode, entry, entry - s * risk, res if s == 1 else sup,
                       58 - (10 if s * (p - ctx.vwap) < 0 else 0), why, ctx, 45, "orb"))
    return out


def _ib(ctx, day, p, a, res, sup):
    """Initial-balance (first hour) breakout: the classic trend-day trigger."""
    out = []
    if ctx.ib_high is None or len(day) < 13:
        return out
    w = ctx.ib_high - ctx.ib_low
    if not 0.8 * a <= w <= 5 * a:
        return out
    closes = day["close"].iloc[12:]
    for s, lvl in ((1, ctx.ib_high), (-1, ctx.ib_low)):
        if (s * (closes.iloc[:-1] - lvl) > 0).any():
            continue  # only the first break of the IB counts
        if s * (p - lvl) > 0.05 * a and s * (p - lvl) <= 0.6 * a:
            stop = p - s * min(max(0.5 * w, 1.0 * a), 2.0 * a)
            out.append(_mk("Initial balance breakout", s, "market", p, stop, res if s == 1 else sup, 58,
                           [f"First close {'above' if s == 1 else 'below'} the first-hour range {ctx.ib_low:.0f}-{ctx.ib_high:.0f}."], ctx, 20, "ib"))
    return out


def _vwap_pullback(ctx, day, p, a, res, sup, last):
    out = []
    for s, tr in ((1, "up"), (-1, "down")):
        if ctx.trend != tr or len(day) < 8:
            continue
        l3 = day.iloc[-3:]
        zone = max(ctx.vwap, ctx.ema21) if s == 1 else min(ctx.vwap, ctx.ema21)
        touched = (l3["low"].min() <= zone + 0.15 * a) if s == 1 else (l3["high"].max() >= zone - 0.15 * a)
        bounce = s * (last["close"] - last["open"]) > 0
        rsi_ok = 40 < ctx.rsi < 65 if s == 1 else 35 < ctx.rsi < 60
        if touched and bounce and rsi_ok and s * (p - ctx.vwap) > 0:
            swing = day["low"].iloc[-12:].min() if s == 1 else day["high"].iloc[-12:].max()
            stop = min(swing, ctx.vwap) - 0.3 * a if s == 1 else max(swing, ctx.vwap) + 0.3 * a
            ahead = ([ctx.day_high] if s == 1 else [ctx.day_low]) + (res if s == 1 else sup)
            out.append(_mk("VWAP trend pullback", s, "market", p, stop, ahead, 56,
                           [f"Trend {tr}; pulled back to VWAP/EMA21 ({zone:.0f}) and bounced; RSI {ctx.rsi:.0f}."], ctx, 20, "vwap_pullback"))
    return out


def _levels(ctx, p, a, res, sup, last):
    out = []
    for lv in ctx.levels:
        if lv.strength < 55 or abs(p - lv.price) > 0.5 * a:
            continue
        if lv.kind == "support" and last["close"] > last["open"] and last["low"] <= lv.high + 0.1 * a and last["close"] > lv.price:
            out.append(_mk("Support bounce", 1, "market", p, lv.low - 0.4 * a, res, 50 + lv.strength // 10,
                           [f"Bullish candle off support {lv.price:.0f} (strength {lv.strength})."], ctx, 20, "level_bounce"))
        if lv.kind == "resistance" and last["close"] < last["open"] and last["high"] >= lv.low - 0.1 * a and last["close"] < lv.price:
            out.append(_mk("Resistance rejection", -1, "market", p, lv.high + 0.4 * a, sup, 50 + lv.strength // 10,
                           [f"Bearish candle rejected at resistance {lv.price:.0f} (strength {lv.strength})."], ctx, 20, "level_reject"))
    return out


def _patterns(ctx, p, a, res, sup):
    out = []
    for pat in ctx.patterns:
        if pat.bias == "neutral" or pat.trigger is None or pat.confidence < 60:
            continue
        s = 1 if pat.bias == "bullish" else -1
        if pat.status == "forming" and 0 < s * (pat.trigger - p) <= 1.5 * a:
            entry = pat.trigger + s * 0.1 * a
            inval = pat.invalidation if pat.invalidation is not None and 0.6 * a <= s * (entry - pat.invalidation) <= 2.5 * a else entry - s * 1.2 * a
            ahead = ([pat.target] if pat.target else []) + (res if s == 1 else sup)
            out.append(_mk(f"{pat.name} trigger", s, "stop", entry, inval, ahead, int(pat.confidence * 0.9), [pat.description], ctx, 30, "pattern_trigger"))
        elif pat.status == "confirmed" and "Retest" in pat.name:
            inval = pat.invalidation if pat.invalidation is not None and 0.6 * a <= s * (p - pat.invalidation) <= 2.5 * a else p - s * 1.0 * a
            out.append(_mk(pat.name, s, "market", p, inval, res if s == 1 else sup, int(pat.confidence * 0.9), [pat.description], ctx, 20, "pattern_retest"))
    return out


def _sweep(ctx, day, p, a, res, sup, last):
    """Liquidity sweep / failed breakout: a wick through an obvious level that closes back inside."""
    out = []
    if len(day) < 6:
        return out
    prior = day.iloc[:-1]
    refs_hi = [x for x in (float(prior["high"].max()), ctx.prev_high, ctx.or_high) if x]
    refs_lo = [x for x in (float(prior["low"].min()), ctx.prev_low, ctx.or_low) if x]
    for lvl in refs_hi:
        if last["high"] > lvl + 0.05 * a and last["close"] < lvl and last["close"] < last["open"]:
            out.append(_mk("Liquidity sweep reversal", -1, "market", p, last["high"] + 0.2 * a, sup + [ctx.vwap], 56,
                           [f"Wicked above {lvl:.0f} and closed back below: trapped buyers."], ctx, 20, "sweep"))
            break
    for lvl in refs_lo:
        if last["low"] < lvl - 0.05 * a and last["close"] > lvl and last["close"] > last["open"]:
            out.append(_mk("Liquidity sweep reversal", 1, "market", p, last["low"] - 0.2 * a, res + [ctx.vwap], 56,
                           [f"Wicked below {lvl:.0f} and closed back above: trapped sellers."], ctx, 20, "sweep"))
            break
    return out


def _value_area(ctx, day, p, a, res, sup, last):
    """Yesterday's value area: rejection at its edge (rotational days) or acceptance back inside (80% rule)."""
    out = []
    pr = ctx.profile
    if pr is None or len(day) < 6:
        return out
    if ctx.open_loc == "inside_value":
        if abs(last["high"] - pr.vah) <= 0.3 * a and last["close"] < last["open"] and p < pr.vah:
            out.append(_mk("Value-area high rejection", -1, "market", p, max(pr.vah, last["high"]) + 0.3 * a, [pr.poc, pr.val] + sup, 54,
                           [f"Opened inside yesterday's value; rejected at VAH {pr.vah:.0f}, POC {pr.poc:.0f} is the magnet."], ctx, 20, "va_reject"))
        if abs(last["low"] - pr.val) <= 0.3 * a and last["close"] > last["open"] and p > pr.val:
            out.append(_mk("Value-area low rejection", 1, "market", p, min(pr.val, last["low"]) - 0.3 * a, [pr.poc, pr.vah] + res, 54,
                           [f"Opened inside yesterday's value; held VAL {pr.val:.0f}, POC {pr.poc:.0f} is the magnet."], ctx, 20, "va_reject"))
    else:
        closes = day["close"].iloc[-6:]  # 30 minutes back inside value -> traverse to the other side
        inside = ((closes > pr.val) & (closes < pr.vah)).all()
        if inside and ctx.open_loc == "above_value":
            out.append(_mk("80% rule (back into value)", -1, "market", p, pr.vah + 0.4 * a, [pr.poc, pr.val], 55,
                           [f"Opened above value, now accepted back inside for 30 min: target VAL {pr.val:.0f}."], ctx, 30, "va_accept"))
        if inside and ctx.open_loc == "below_value":
            out.append(_mk("80% rule (back into value)", 1, "market", p, pr.val - 0.4 * a, [pr.poc, pr.vah], 55,
                           [f"Opened below value, now accepted back inside for 30 min: target VAH {pr.vah:.0f}."], ctx, 30, "va_accept"))
    return out


def _divergence(ctx, df5, day, p, a, res, sup, last):
    """RSI divergence at a fresh session extreme."""
    out = []
    if len(day) < 14:
        return out
    r = rsi(df5["close"]).iloc[-14:].to_numpy()
    h, l = day["high"].iloc[-14:].to_numpy(), day["low"].iloc[-14:].to_numpy()
    if h[-1] >= h[:-3].max() and r[-1] < r[:-3][np.argmax(h[:-3])] - 3 and last["close"] < last["open"]:
        out.append(_mk("Bearish RSI divergence", -1, "market", p, h[-1] + 0.3 * a, sup + [ctx.vwap], 54,
                       ["New high on weaker RSI, then a red candle."], ctx, 20, "divergence"))
    if l[-1] <= l[:-3].min() and r[-1] > r[:-3][np.argmin(l[:-3])] + 3 and last["close"] > last["open"]:
        out.append(_mk("Bullish RSI divergence", 1, "market", p, l[-1] - 0.3 * a, res + [ctx.vwap], 54,
                       ["New low on stronger RSI, then a green candle."], ctx, 20, "divergence"))
    return out


def _flag(ctx, day, p, a, res, sup):
    """Bull/bear flag: a sharp impulse, then a tight, orderly (high R^2) counter-drift; enter on the break."""
    out = []
    if len(day) < 14:
        return out
    for n_flag in (5, 7, 9):
        if len(day) < n_flag + 6:
            continue
        flag = day.iloc[-n_flag:]
        pole = day.iloc[-n_flag - 6 : -n_flag]
        move = float(pole["close"].iloc[-1] - pole["open"].iloc[0])
        if abs(move) < 2.0 * a:
            continue
        s = 1 if move > 0 else -1
        rng = float(flag["high"].max() - flag["low"].min())
        if rng > 0.6 * abs(move):
            continue
        kh, r2h = _linfit(flag["high"].to_numpy())
        kl, r2l = _linfit(flag["low"].to_numpy())
        if s * kh > 0.05 * a or s * kl > 0.05 * a or min(r2h, r2l) < 0.4:
            continue  # must drift against the pole in an orderly channel
        edge = float(flag["high"].max()) if s == 1 else float(flag["low"].min())
        if 0 < s * (edge - p) <= 1.0 * a:
            entry = edge + s * 0.1 * a
            stop = (float(flag["low"].min()) if s == 1 else float(flag["high"].max())) - s * 0.2 * a
            out.append(_mk("Bull flag breakout" if s == 1 else "Bear flag breakdown", s, "stop", entry, stop,
                           [entry + s * abs(move)] + (res if s == 1 else sup), 58,
                           [f"Pole of {abs(move):.0f} pts, flag of {n_flag} bars (fit R² {min(r2h, r2l):.2f})."], ctx, 25, "flag"))
            break
    return out


FAMILIES = ("orb", "ib", "vwap_pullback", "level_bounce", "level_reject", "pattern_trigger", "pattern_retest",
            "sweep", "va_reject", "va_accept", "divergence", "flag")
# Signal study (13 NSE instruments, ~26k ideas, Aug-Oct 2026, dev/holdout split): reversal families beat same-day
# ideas by ~+0.08R in BOTH halves (t 6-8); breakout/continuation families lagged by ~-0.08R. Only reversals are enabled.
REVERSAL = {"divergence", "sweep", "va_reject", "level_bounce", "level_reject"}
ENABLED: set[str] | None = set(REVERSAL)
# Confidence ranks families by their measured excess R (dev / holdout): divergence +0.26/+0.25, sweep +0.17/+0.22,
# value-area rejection +0.09/+0.06, level bounce/reject +0.04/+0.03.
FAMILY_CONF = {"divergence": 72, "sweep": 70, "va_reject": 62, "level_bounce": 58, "level_reject": 58}


def generate_ideas(ctx: DayContext, df5: pd.DataFrame, min_conf: int = 55, raw: bool = False, families: set[str] | None = None) -> list[Idea]:
    global _RAW
    _RAW = raw
    p, a = ctx.spot, ctx.atr
    day = df5[df5.index.date == df5.index[-1].date()]
    last = day.iloc[-1]
    res = [x.price for x in ctx.levels if x.kind == "resistance"]
    sup = [x.price for x in ctx.levels if x.kind == "support"]
    out = (_orb(ctx, day, p, a, res, sup) + _ib(ctx, day, p, a, res, sup) + _vwap_pullback(ctx, day, p, a, res, sup, last)
           + _levels(ctx, p, a, res, sup, last) + _patterns(ctx, p, a, res, sup) + _sweep(ctx, day, p, a, res, sup, last)
           + _value_area(ctx, day, p, a, res, sup, last) + _divergence(ctx, df5, day, p, a, res, sup, last) + _flag(ctx, day, p, a, res, sup))
    _RAW = False
    allow = families if families is not None else ENABLED
    ideas = [i for i in out if i and i.confidence >= min_conf and (allow is None or i.family in allow)]
    if raw:
        return ideas
    ideas.sort(key=lambda i: -i.confidence)
    if ideas:  # don't publish a bullish and a bearish call of similar strength at the same time
        top = ideas[0]
        ideas = [i for i in ideas if i.side == top.side or i.confidence >= top.confidence - 5]
    return ideas[:3]


def premarket_ideas(ctx: DayContext) -> list[Idea]:
    """Conditional plan for the next session: fade the previous day's extremes (breakouts tested worse)."""
    a, out = ctx.atr, []
    if ctx.prev_high is None or ctx.prev_low is None:
        return out
    mid = ctx.prev_close if ctx.prev_close else (ctx.prev_high + ctx.prev_low) / 2
    sup = [x.price for x in ctx.levels if x.kind == "support"] + [mid, ctx.prev_low]
    res = [x.price for x in ctx.levels if x.kind == "resistance"] + [mid, ctx.prev_high]
    for s, lvl, name, fam, ahead in ((-1, ctx.prev_high, "Prev-day high rejection", "level_reject", sup),
                                     (1, ctx.prev_low, "Prev-day low bounce", "level_bounce", res)):
        entry = lvl + s * 0.1 * a  # just inside the level
        stop = lvl - s * 1.0 * a  # ~1.1 ATR of risk: tighter stops fail the cost gate
        t = _targets(s, entry, 1.1 * a, ahead)
        why = [f"Only if price tests {lvl:.0f} (previous day {'high' if s == -1 else 'low'}) and a 5m candle closes back "
               f"{'below' if s == -1 else 'above'} it before 12:00. Skip if it opens beyond the level."]
        out.append(Idea(name, "LONG" if s == 1 else "SHORT", "limit", float(entry), float(stop), [float(x) for x in t],
                        FAMILY_CONF.get(fam, 58), True, why, 150, fam))
    return out

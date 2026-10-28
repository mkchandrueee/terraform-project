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
    if ctx.prev_close:
        ctx.gap_pct = round((float(day["open"].iloc[0]) / ctx.prev_close - 1) * 100, 2)
    return ctx


def _mk(setup, s, mode, entry, stop, prices, conf, why, ctx, valid=30) -> Idea | None:
    a = ctx.atr
    risk = s * (entry - stop)
    if not (0.6 * a <= risk <= 2.5 * a):
        return None
    aligned = s * ctx.bias_score >= 0.2
    if s * ctx.bias_score <= -0.5:
        return None  # never buy options against a strong multi-timeframe bias
    conf = conf + (15 if aligned else -10 if s * ctx.bias_score < 0 else 0)
    t = _targets(s, entry, risk, prices)
    return Idea(setup, "LONG" if s == 1 else "SHORT", mode, float(entry), float(stop), [float(x) for x in t],
                int(max(0, min(95, conf))), aligned, why, valid)


def generate_ideas(ctx: DayContext, df5: pd.DataFrame, min_conf: int = 55) -> list[Idea]:
    p, a = ctx.spot, ctx.atr
    day = df5[df5.index.date == df5.index[-1].date()]
    last = day.iloc[-1]
    res = [x.price for x in ctx.levels if x.kind == "resistance"]
    sup = [x.price for x in ctx.levels if x.kind == "support"]
    out: list[Idea | None] = []

    # 1) Opening-range breakout
    if ctx.or_high is not None and len(day) >= 3:
        w = ctx.or_high - ctx.or_low
        if 0.4 * a <= w <= 3.5 * a:
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
                if s * (p - ctx.vwap) < 0:
                    why.append("Price is on the wrong side of VWAP, so confidence is reduced.")
                out.append(_mk("Opening range breakout", s, mode, entry, entry - s * risk, res if s == 1 else sup,
                               58 - (10 if s * (p - ctx.vwap) < 0 else 0), why, ctx, 45))

    # 2) Trend pullback to VWAP / EMA21
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
                           [f"Trend {tr}; pulled back to VWAP/EMA21 ({zone:.0f}) and bounced; RSI {ctx.rsi:.0f}."], ctx, 20))

    # 3) Reaction at a strong support / resistance
    for lv in ctx.levels:
        if lv.strength < 55 or abs(p - lv.price) > 0.5 * a:
            continue
        if lv.kind == "support" and last["close"] > last["open"] and last["low"] <= lv.high + 0.1 * a and last["close"] > lv.price:
            out.append(_mk("Support bounce", 1, "market", p, lv.low - 0.4 * a, res, 50 + lv.strength // 10,
                           [f"Bullish candle off support {lv.price:.0f} (strength {lv.strength})."], ctx, 20))
        if lv.kind == "resistance" and last["close"] < last["open"] and last["high"] >= lv.low - 0.1 * a and last["close"] < lv.price:
            out.append(_mk("Resistance rejection", -1, "market", p, lv.high + 0.4 * a, sup, 50 + lv.strength // 10,
                           [f"Bearish candle rejected at resistance {lv.price:.0f} (strength {lv.strength})."], ctx, 20))

    # 4) Chart patterns forming / retesting on the 5m chart
    for pat in ctx.patterns:
        if pat.bias == "neutral" or pat.trigger is None or pat.confidence < 60:
            continue
        s = 1 if pat.bias == "bullish" else -1
        if pat.status == "forming" and 0 < s * (pat.trigger - p) <= 1.5 * a:
            entry = pat.trigger + s * 0.1 * a
            inval = pat.invalidation if pat.invalidation is not None and 0.6 * a <= s * (entry - pat.invalidation) <= 2.5 * a else entry - s * 1.2 * a
            ahead = ([pat.target] if pat.target else []) + (res if s == 1 else sup)
            out.append(_mk(f"{pat.name} trigger", s, "stop", entry, inval, ahead, int(pat.confidence * 0.9), [pat.description], ctx, 30))
        elif pat.status == "confirmed" and "Retest" in pat.name:
            inval = pat.invalidation if pat.invalidation is not None and 0.6 * a <= s * (p - pat.invalidation) <= 2.5 * a else p - s * 1.0 * a
            out.append(_mk(pat.name, s, "market", p, inval, res if s == 1 else sup, int(pat.confidence * 0.9), [pat.description], ctx, 20))

    ideas = [i for i in out if i and i.confidence >= min_conf]
    ideas.sort(key=lambda i: -i.confidence)
    if ideas:  # don't publish a bullish and a bearish call of similar strength at the same time
        top = ideas[0]
        ideas = [i for i in ideas if i.side == top.side or i.confidence >= top.confidence - 5]
    return ideas[:3]


def premarket_ideas(ctx: DayContext) -> list[Idea]:
    """Conditional plan for the next session: trade the break of the previous day's range."""
    a, out = ctx.atr, []
    if ctx.prev_high is None or ctx.prev_low is None:
        return out
    res = [x.price for x in ctx.levels if x.kind == "resistance"] + [ctx.prev_high]
    sup = [x.price for x in ctx.levels if x.kind == "support"] + [ctx.prev_low]
    bias = {"bullish": 1, "bearish": -1}.get(ctx.daily_bias, 0)
    for s, lvl, name, ahead in ((1, ctx.prev_high, "Prev-day high breakout", res), (-1, ctx.prev_low, "Prev-day low breakdown", sup)):
        trig = lvl + s * 0.1 * a
        stop = trig - s * 1.0 * a
        t = _targets(s, trig, 1.0 * a, ahead)
        why = [f"Buy only if {'above' if s == 1 else 'below'} {trig:.0f} after the opening range (09:30+); previous day {'high' if s == 1 else 'low'} is {lvl:.0f}."]
        if s * bias < 0:
            why.append("Against the daily trend: lower confidence.")
        out.append(Idea(name, "LONG" if s == 1 else "SHORT", "stop", float(trig), float(stop), [float(x) for x in t],
                        55 + (10 if s * bias > 0 else -5 if s * bias < 0 else 0), s * bias >= 0, why, 360))
    return out

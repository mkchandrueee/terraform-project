"""Chart-pattern detection on ATR zig-zag swings, S/R breaks and candlestick triggers."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import atr, rsi
from .levels import Level, Pivot, zigzag


@dataclass
class Pattern:
    name: str
    bias: str  # bullish | bearish | neutral
    status: str  # forming | confirmed
    confidence: int  # 0-100
    description: str
    trigger: float | None = None  # price that confirms the pattern
    target: float | None = None  # measured-move target
    invalidation: float | None = None
    points: list[tuple[int, float]] = field(default_factory=list)  # positional idx, price
    lines: list[list[tuple[int, float]]] = field(default_factory=list)  # [(idx,price),(idx,price)]


def _tails(p: list[Pivot], k: int):
    """Last k pivots, and the k before the (possibly provisional) final pivot."""
    if len(p) >= k:
        yield p[-k:]
    if len(p) >= k + 1:
        yield p[-k - 1 : -1]


def _double(d: pd.DataFrame, piv: list[Pivot], a: float, top: bool) -> list[Pattern]:
    """M (double top) / W (double bottom). Detects the second leg while it is still forming."""
    out = []
    price = float(d["close"].iloc[-1])
    n = len(d)
    r = rsi(d["close"]).to_numpy()
    ex, mid_kind = ("H", "L") if top else ("L", "H")
    for t in _tails(piv, 3):
        if [x.kind for x in t] != [ex, mid_kind, ex]:
            continue
        e1, m, e2 = t
        tol = max(1.0 * a, 0.005 * price)
        # second extreme may be a little "better" than the first (higher low in a W / lower high in an M)
        better = (e1.price - e2.price) if top else (e2.price - e1.price)
        worse = -better
        if worse > tol or better > 1.5 * tol:
            continue
        depth = (min(e1.price, e2.price) - m.price) if top else (m.price - max(e1.price, e2.price))
        if depth < 1.5 * a or (n - 1 - e2.idx) > max(15, int(0.45 * n)):
            continue
        div = (r[e2.idx] < r[e1.idx] - 2) if top else (r[e2.idx] > r[e1.idx] + 2)
        conf = 55 + 15 * (1 - max(worse, 0) / tol) + (8 if div else 0) + (5 if better > 0 else 0)
        if top:
            if price > max(e1.price, e2.price) + 0.5 * a:
                continue
            confirmed = price < m.price - 0.1 * a
            if not confirmed and price < m.price + 0.3 * depth:
                continue  # drifted into the middle without breaking: not a live setup
            stage = "neckline broken" if confirmed else ("second top in progress" if not e2.confirmed else "second top made, awaiting neckline break")
            name, bias, trig = "Double Top (M)", "bearish", m.price
            target, inval = m.price - depth, max(e1.price, e2.price) + 0.25 * a
            what = f"Two highs near {e1.price:.2f}/{e2.price:.2f}; neckline {m.price:.2f}"
        else:
            if price < min(e1.price, e2.price) - 0.5 * a:
                continue
            confirmed = price > m.price + 0.1 * a
            if not confirmed and price > m.price - 0.3 * depth:
                continue
            stage = "neckline broken" if confirmed else ("second low in progress" if not e2.confirmed else "second low made, awaiting neckline break")
            name, bias, trig = "Double Bottom (W)", "bullish", m.price
            target, inval = m.price + depth, min(e1.price, e2.price) - 0.25 * a
            what = f"Two lows near {e1.price:.2f}/{e2.price:.2f}; neckline {m.price:.2f}"
        out.append(
            Pattern(
                name, bias, "confirmed" if confirmed else "forming", int(min(90, conf + (15 if confirmed else 0))),
                f"{what}. Stage: {stage}." + (" RSI divergence supports it." if div else ""),
                trigger=trig, target=target, invalidation=inval,
                points=[(e1.idx, e1.price), (e2.idx, e2.price)],
                lines=[[(e1.idx, m.price), (n - 1, m.price)]],
            )
        )
    return out


def _head_shoulders(d: pd.DataFrame, piv: list[Pivot], a: float, top: bool) -> list[Pattern]:
    out = []
    price = float(d["close"].iloc[-1])
    n = len(d)
    kinds = ["H", "L", "H", "L", "H"] if top else ["L", "H", "L", "H", "L"]
    for t in _tails(piv, 5):
        if [x.kind for x in t] != kinds:
            continue
        ls, n1, hd, n2, rs = t
        neck = (n1.price + n2.price) / 2
        head_h = abs(hd.price - neck)
        ok_head = hd.price > max(ls.price, rs.price) if top else hd.price < min(ls.price, rs.price)
        if not ok_head or head_h < 2 * a:
            continue
        if abs(ls.price - rs.price) > 0.4 * head_h or abs(n1.price - n2.price) > 0.5 * head_h:
            continue
        if (n - 1 - rs.idx) > max(15, int(0.45 * n)):
            continue
        if top:
            confirmed = price < neck - 0.1 * a
            if price > hd.price:
                continue
            out.append(
                Pattern(
                    "Head & Shoulders", "bearish", "confirmed" if confirmed else "forming",
                    int(min(92, 60 + (15 if confirmed else 0) + 15 * (1 - abs(ls.price - rs.price) / (0.4 * head_h)))),
                    f"Head {hd.price:.2f} over shoulders {ls.price:.2f}/{rs.price:.2f}; neckline ~{neck:.2f}.",
                    trigger=neck, target=neck - head_h, invalidation=hd.price + 0.25 * a,
                    points=[(ls.idx, ls.price), (hd.idx, hd.price), (rs.idx, rs.price)],
                    lines=[[(n1.idx, n1.price), (n2.idx, n2.price)]],
                )
            )
        else:
            confirmed = price > neck + 0.1 * a
            if price < hd.price:
                continue
            out.append(
                Pattern(
                    "Inverse Head & Shoulders", "bullish", "confirmed" if confirmed else "forming",
                    int(min(92, 60 + (15 if confirmed else 0) + 15 * (1 - abs(ls.price - rs.price) / (0.4 * head_h)))),
                    f"Head {hd.price:.2f} under shoulders {ls.price:.2f}/{rs.price:.2f}; neckline ~{neck:.2f}.",
                    trigger=neck, target=neck + head_h, invalidation=hd.price - 0.25 * a,
                    points=[(ls.idx, ls.price), (hd.idx, hd.price), (rs.idx, rs.price)],
                    lines=[[(n1.idx, n1.price), (n2.idx, n2.price)]],
                )
            )
    return out


def _trendline_patterns(d: pd.DataFrame, piv: list[Pivot], a: float) -> list[Pattern]:
    n = len(d)
    price = float(d["close"].iloc[-1])
    highs = [p for p in piv if p.kind == "H"][-3:]
    lows = [p for p in piv if p.kind == "L"][-3:]
    if len(highs) < 2 or len(lows) < 2:
        return []
    start = min(highs[0].idx, lows[0].idx)
    end = n - 1
    if end - start < 12 or (end - max(highs[-1].idx, lows[-1].idx)) > max(12, int(0.3 * n)):
        return []
    hs, hi = np.polyfit([p.idx for p in highs], [p.price for p in highs], 1)
    ls, li = np.polyfit([p.idx for p in lows], [p.price for p in lows], 1)
    hl = lambda x: hs * x + hi  # noqa: E731
    ll = lambda x: ls * x + li  # noqa: E731
    w0, w1 = hl(start) - ll(start), hl(end) - ll(end)
    if w0 < 2 * a or w1 < 0.3 * a:
        return []
    dh, dl = hl(end) - hl(start), ll(end) - ll(start)
    k = 0.25 * w0
    cls = lambda v: "r" if v > k else ("f" if v < -k else "0")  # noqa: E731
    ch, cl = cls(dh), cls(dl)
    converging = w1 < 0.75 * w0
    table = {
        ("0", "r"): ("Ascending Triangle", "bullish"),
        ("f", "0"): ("Descending Triangle", "bearish"),
        ("f", "r"): ("Symmetrical Triangle", "neutral"),
        ("0", "0"): ("Rectangle Range", "neutral"),
    }
    if (ch, cl) in table:
        name, bias = table[(ch, cl)]
    elif (ch, cl) == ("r", "r"):
        name, bias = ("Rising Wedge", "bearish") if converging else ("Ascending Channel", "bullish")
    elif (ch, cl) == ("f", "f"):
        name, bias = ("Falling Wedge", "bullish") if converging else ("Descending Channel", "bearish")
    else:
        return []
    upper, lower = hl(end), ll(end)
    status, conf = "forming", 50 + 5 * (len(highs) + len(lows)) + (8 if converging else 0)
    desc = f"{name}: upper {upper:.2f}, lower {lower:.2f} over {end - start} bars."
    if price > upper + 0.1 * a:
        status, bias = "confirmed", "bullish"
        name += " (upside breakout)"
        desc += " Broke out above the upper line."
    elif price < lower - 0.1 * a:
        status, bias = "confirmed", "bearish"
        name += " (downside breakdown)"
        desc += " Broke down below the lower line."
    trigger = upper if bias in ("bullish", "neutral") else lower
    target = (upper + w0) if bias == "bullish" else ((lower - w0) if bias == "bearish" else None)
    inval = (lower - 0.25 * a) if bias == "bullish" else ((upper + 0.25 * a) if bias == "bearish" else None)
    return [
        Pattern(
            name, bias, status, int(min(75, conf + (5 if status == "confirmed" else 0))), desc,
            trigger=float(trigger), target=None if target is None else float(target),
            invalidation=None if inval is None else float(inval),
            points=[(p.idx, p.price) for p in highs + lows],
            lines=[[(start, float(hl(start))), (end, float(upper))], [(start, float(ll(start))), (end, float(lower))]],
        )
    ]


def _level_breaks(d: pd.DataFrame, levels: list[Level], a: float) -> list[Pattern]:
    out: list[Pattern] = []
    c = d["close"].to_numpy()
    n = len(d)
    if n < 15:
        return out
    vol = d["volume"].to_numpy()
    vol_ratio = vol[-3:].mean() / max(vol[-23:-3].mean(), 1.0) if n > 25 else 1.0
    for lv in levels:
        before = float(np.median(c[-12:-4]))
        now = c[-1]
        broke_up = before < lv.price - 0.2 * a and now > lv.price + 0.1 * a and c[-4:].max() >= now
        broke_dn = before > lv.price + 0.2 * a and now < lv.price - 0.1 * a and c[-4:].min() <= now
        if not (broke_up or broke_dn):
            continue
        up = broke_up
        retest = abs(now - lv.price) <= 0.4 * a
        conf = 55 + min(20, lv.strength // 5) + (10 if vol_ratio > 1.3 else 0) + (5 if retest else 0)
        out.append(
            Pattern(
                ("Resistance Breakout" if up else "Support Breakdown") + (" + Retest" if retest else ""),
                "bullish" if up else "bearish", "confirmed", int(min(90, conf)),
                f"Closed {'above' if up else 'below'} {lv.price:.2f} (strength {lv.strength}); "
                f"volume {vol_ratio:.1f}x recent average.",
                trigger=lv.price, invalidation=lv.price - 0.5 * a if up else lv.price + 0.5 * a,
                lines=[[(max(lv.last_idx, 0) if lv.last_idx < n else 0, lv.price), (n - 1, lv.price)]],
            )
        )
    return out


def _candles(d: pd.DataFrame, levels: list[Level], a: float) -> list[Pattern]:
    if len(d) < 8:
        return []
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    i = len(d) - 1
    body, rng = abs(c[i] - o[i]), h[i] - l[i]
    if rng <= 0:
        return []
    lw, uw = min(o[i], c[i]) - l[i], h[i] - max(o[i], c[i])
    down, up = c[i] < c[i - 5], c[i] > c[i - 5]
    near = [lv for lv in levels if lv.low - 0.5 * a <= c[i] <= lv.high + 0.5 * a]
    bonus = 12 if near else 0
    where = f" at {'support' if near[0].kind == 'support' else 'resistance'} {near[0].price:.2f}" if near else ""
    pts = [(i, float(c[i]))]
    out = []
    if c[i - 1] < o[i - 1] and c[i] > o[i] and c[i] >= o[i - 1] and o[i] <= c[i - 1] and body > 0.8 * abs(c[i - 1] - o[i - 1]) and down:
        out.append(Pattern("Bullish Engulfing", "bullish", "confirmed", 50 + bonus, "Bullish body engulfs prior bearish candle" + where, trigger=float(h[i]), invalidation=float(l[i]), points=pts))
    if c[i - 1] > o[i - 1] and c[i] < o[i] and c[i] <= o[i - 1] and o[i] >= c[i - 1] and body > 0.8 * abs(c[i - 1] - o[i - 1]) and up:
        out.append(Pattern("Bearish Engulfing", "bearish", "confirmed", 50 + bonus, "Bearish body engulfs prior bullish candle" + where, trigger=float(l[i]), invalidation=float(h[i]), points=pts))
    if lw >= 2 * max(body, 0.05 * rng) and uw <= 0.35 * rng and down and rng >= 0.8 * a:
        out.append(Pattern("Hammer", "bullish", "confirmed", 48 + bonus, "Long lower wick after a decline" + where, trigger=float(h[i]), invalidation=float(l[i]), points=pts))
    if uw >= 2 * max(body, 0.05 * rng) and lw <= 0.35 * rng and up and rng >= 0.8 * a:
        out.append(Pattern("Shooting Star", "bearish", "confirmed", 48 + bonus, "Long upper wick after a rally" + where, trigger=float(l[i]), invalidation=float(h[i]), points=pts))
    if body <= 0.1 * rng and rng >= 0.5 * a:
        out.append(Pattern("Doji", "neutral", "confirmed", 35 + bonus, "Indecision candle" + where, points=pts))
    return out


def detect_patterns(df: pd.DataFrame, levels: list[Level] | None = None, lookback: int = 120) -> list[Pattern]:
    """Detect patterns on the last `lookback` bars. Point/line indices are positional in `df`."""
    off = max(len(df) - lookback, 0)
    d = df.iloc[off:]
    if len(d) < 20:
        return []
    a = float(atr(d).iloc[-1])
    piv = zigzag(d, mult=2.0)
    lv = []
    for x in levels or []:
        y = Level(**{**x.__dict__})
        y.last_idx = x.last_idx - off
        lv.append(y)
    found = (
        _double(d, piv, a, True) + _double(d, piv, a, False)
        + _head_shoulders(d, piv, a, True) + _head_shoulders(d, piv, a, False)
        + _trendline_patterns(d, piv, a) + _level_breaks(d, lv, a) + _candles(d, lv, a)
    )
    for p in found:  # shift back to df-positional indices
        p.points = [(i + off, v) for i, v in p.points]
        p.lines = [[(i + off, v) for i, v in ln] for ln in p.lines]
    found.sort(key=lambda p: p.confidence + (10 if p.status == "confirmed" else 0), reverse=True)
    return found[:7]

"""Swing detection (ATR zig-zag) and clustered support / resistance levels."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .indicators import atr, is_intraday


@dataclass
class Pivot:
    idx: int  # positional index into the df it was computed on
    price: float
    kind: str  # "H" or "L"
    confirmed: bool = True


@dataclass
class Level:
    price: float
    low: float
    high: float
    kind: str  # "support" | "resistance" (relative to last close)
    touches: int
    strength: int  # 0-100
    last_idx: int
    sources: list[str] = field(default_factory=list)


def zigzag(df: pd.DataFrame, mult: float = 2.0) -> list[Pivot]:
    """Alternating swing highs/lows; a reversal needs `mult` x ATR. Last pivot is provisional."""
    n = len(df)
    if n < 3:
        return []
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    a = atr(df).to_numpy()
    piv: list[Pivot] = []
    direction = 0
    hi, hi_i, lo, lo_i = h[0], 0, l[0], 0
    for i in range(1, n):
        thr = mult * a[i]
        if direction == 0:
            if h[i] > hi:
                hi, hi_i = h[i], i
            if l[i] < lo:
                lo, lo_i = l[i], i
            if h[i] - lo >= thr and lo_i < i:
                piv.append(Pivot(lo_i, lo, "L"))
                direction, hi, hi_i = 1, h[i], i
            elif hi - l[i] >= thr and hi_i < i:
                piv.append(Pivot(hi_i, hi, "H"))
                direction, lo, lo_i = -1, l[i], i
        elif direction == 1:
            if h[i] > hi:
                hi, hi_i = h[i], i
            elif hi - l[i] >= thr:
                piv.append(Pivot(hi_i, hi, "H"))
                direction, lo, lo_i = -1, l[i], i
        else:
            if l[i] < lo:
                lo, lo_i = l[i], i
            elif h[i] - lo >= thr:
                piv.append(Pivot(lo_i, lo, "L"))
                direction, hi, hi_i = 1, h[i], i
    if direction == 1:
        piv.append(Pivot(hi_i, hi, "H", confirmed=False))
    elif direction == -1:
        piv.append(Pivot(lo_i, lo, "L", confirmed=False))
    return piv


def build_levels(df: pd.DataFrame, lookback: int = 300, max_per_side: int = 4) -> list[Level]:
    """Cluster swing prices (plus prior-session H/L when intraday) into scored S/R zones."""
    d = df.iloc[-lookback:]
    n = len(d)
    last = float(d["close"].iloc[-1])
    a_last = float(atr(d).iloc[-1])
    tol = max(0.5 * a_last, 0.0015 * last)

    # (price, idx, weight, label)
    entries: list[tuple[float, int, float, str]] = []
    for p in zigzag(d, mult=1.2):
        recency = 0.5 + 0.5 * p.idx / max(n - 1, 1)
        entries.append((p.price, p.idx, recency, "swing"))

    if is_intraday(d):
        days = d.groupby(d.index.normalize())
        dates = list(days.groups)
        if len(dates) >= 2:
            prev = d.loc[days.groups[dates[-2]]]
            pos = {ts: i for i, ts in enumerate(d.index)}
            end_i = pos[prev.index[-1]]
            entries.append((float(prev["high"].max()), end_i, 0.9, "prev-day high"))
            entries.append((float(prev["low"].min()), end_i, 0.9, "prev-day low"))
            entries.append((float(prev["close"].iloc[-1]), end_i, 0.6, "prev-day close"))

    entries.sort(key=lambda e: e[0])
    clusters: list[list[tuple[float, int, float, str]]] = []
    for e in entries:
        if clusters and e[0] - np.mean([x[0] for x in clusters[-1]]) <= tol:
            clusters[-1].append(e)
        else:
            clusters.append([e])

    levels: list[Level] = []
    for c in clusters:
        prices = [x[0] for x in c]
        w = sum(x[2] for x in c)
        last_idx = max(x[1] for x in c)
        recent = (n - 1 - last_idx) < 40
        if len(c) < 2 and not recent and not any(x[3] != "swing" for x in c):
            continue
        price = float(np.average(prices, weights=[x[2] for x in c]))
        levels.append(
            Level(
                price=price,
                low=min(prices) - 0.1 * a_last,
                high=max(prices) + 0.1 * a_last,
                kind="support" if price < last else "resistance",
                touches=len(c),
                strength=int(round(100 * (1 - np.exp(-w / 2.5)))),
                last_idx=last_idx + (len(df) - n),
                sources=sorted({x[3] for x in c}),
            )
        )

    sup = sorted((x for x in levels if x.kind == "support"), key=lambda x: last - x.price)[:max_per_side]
    res = sorted((x for x in levels if x.kind == "resistance"), key=lambda x: x.price - last)[:max_per_side]
    return sorted(sup + res, key=lambda x: x.price)


def nearest(levels: list[Level], kind: str) -> Level | None:
    side = [x for x in levels if x.kind == kind]
    if not side:
        return None
    return max(side, key=lambda x: x.price) if kind == "support" else min(side, key=lambda x: x.price)

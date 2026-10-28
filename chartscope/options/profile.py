"""Market-profile (TPO) value area from the previous session, plus the day's open location.

Idea from profile-framing systems: where the open sits relative to yesterday's value area (and the
shape of yesterday's profile) separates trend days from rotational days. Uses time-at-price so it works
for indices whose feeds carry no volume.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Profile:
    poc: float
    vah: float
    val: float
    shape: str  # P (top-heavy, buyers) | b (bottom-heavy, sellers) | D (balanced)
    high: float
    low: float


def tpo_profile(day: pd.DataFrame, bins: int = 40) -> Profile | None:
    if len(day) < 20:
        return None
    lo, hi = float(day["low"].min()), float(day["high"].max())
    if hi <= lo:
        return None
    edges = np.linspace(lo, hi, bins + 1)
    counts = np.zeros(bins)
    for h, l in zip(day["high"].to_numpy(), day["low"].to_numpy()):
        a = max(int(np.searchsorted(edges, l, side="right")) - 1, 0)
        b = min(int(np.searchsorted(edges, h, side="left")), bins)
        counts[a:max(b, a + 1)] += 1
    mid = (edges[:-1] + edges[1:]) / 2
    poc_i = int(np.argmax(counts + 1e-6 * (1 - np.abs(mid - (lo + hi) / 2) / (hi - lo))))
    total, acc, i0, i1 = counts.sum(), counts[poc_i], poc_i, poc_i
    while acc < 0.7 * total and (i0 > 0 or i1 < bins - 1):
        up = counts[i1 + 1] if i1 < bins - 1 else -1
        dn = counts[i0 - 1] if i0 > 0 else -1
        if up >= dn:
            i1 += 1
            acc += counts[i1]
        else:
            i0 -= 1
            acc += counts[i0]
    pos = (mid[poc_i] - lo) / (hi - lo)
    return Profile(float(mid[poc_i]), float(edges[i1 + 1]), float(edges[i0]), "P" if pos > 0.65 else "b" if pos < 0.35 else "D", hi, lo)


def open_location(day_open: float, prof: Profile | None) -> str:
    """above_value | below_value | inside_value | unknown"""
    if prof is None:
        return "unknown"
    return "above_value" if day_open > prof.vah else "below_value" if day_open < prof.val else "inside_value"

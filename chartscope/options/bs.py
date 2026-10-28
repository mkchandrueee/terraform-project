"""Black-Scholes pricing helpers (European, no dividends)."""

from __future__ import annotations

import math

RATE = 0.065
MIN_PER_YEAR = 365 * 24 * 60


def _cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def price(S: float, K: float, minutes: float, sigma: float, kind: str, r: float = RATE) -> float:
    T = max(minutes, 0.5) / MIN_PER_YEAR
    intrinsic = max(S - K, 0.0) if kind == "CE" else max(K - S, 0.0)
    if sigma <= 0:
        return intrinsic
    sq = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / sq
    d2 = d1 - sq
    if kind == "CE":
        v = S * _cdf(d1) - K * math.exp(-r * T) * _cdf(d2)
    else:
        v = K * math.exp(-r * T) * _cdf(-d2) - S * _cdf(-d1)
    return max(v, intrinsic * 0.999, 0.05)


def delta(S: float, K: float, minutes: float, sigma: float, kind: str, r: float = RATE) -> float:
    T = max(minutes, 0.5) / MIN_PER_YEAR
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return _cdf(d1) if kind == "CE" else _cdf(d1) - 1


def implied_vol(p: float, S: float, K: float, minutes: float, kind: str) -> float | None:
    """Bisection IV; None if the quote is below intrinsic or unsolvable."""
    lo, hi = 0.01, 3.0
    if p <= max(S - K, 0.0) if kind == "CE" else p <= max(K - S, 0.0):
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        if price(S, K, minutes, mid, kind) > p:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2

"""Option chain: NSE public JSON when reachable, otherwise a Black-Scholes model off India VIX."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date, datetime

from . import bs, contracts

_NSE = "https://www.nseindia.com"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{_NSE}/option-chain",
}


@dataclass
class Quote:
    strike: int
    kind: str  # CE | PE
    ltp: float
    iv: float | None = None  # fraction (0.16 = 16%)
    oi: int = 0
    oi_chg: int = 0


@dataclass
class Chain:
    underlying: str
    spot: float
    expiry: date
    source: str  # "nse" | "model"
    quotes: dict[tuple[int, str], Quote] = field(default_factory=dict)
    pcr: float | None = None
    max_pain: int | None = None
    call_wall: int | None = None  # strike with the most call OI (resistance)
    put_wall: int | None = None  # strike with the most put OI (support)

    def quote(self, strike: int, kind: str) -> Quote | None:
        return self.quotes.get((strike, kind))


def parse_nse(payload: dict, underlying: str) -> Chain | None:
    """Parse NSE /api/option-chain-* JSON for the nearest expiry."""
    rec = payload.get("records") or {}
    rows = rec.get("data") or []
    if not rows:
        return None
    exps = sorted({datetime.strptime(r["expiryDate"], "%d-%b-%Y").date() for r in rows if "expiryDate" in r})
    if not exps:
        return None
    exp = next((e for e in exps if e >= date.today()), exps[0])
    spot = float(rec.get("underlyingValue") or 0)
    ch = Chain(underlying.upper(), spot, exp, "nse")
    coi: dict[int, int] = {}
    poi: dict[int, int] = {}
    for r in rows:
        if datetime.strptime(r["expiryDate"], "%d-%b-%Y").date() != exp:
            continue
        k = int(r["strikePrice"])
        for kind in ("CE", "PE"):
            q = r.get(kind)
            if not q:
                continue
            iv = q.get("impliedVolatility")
            ch.quotes[(k, kind)] = Quote(k, kind, float(q.get("lastPrice") or 0), (iv / 100 if iv else None),
                                         int(q.get("openInterest") or 0), int(q.get("changeinOpenInterest") or 0))
            (coi if kind == "CE" else poi)[k] = int(q.get("openInterest") or 0)
    if not ch.quotes:
        return None
    if sum(coi.values()):
        ch.pcr = round(sum(poi.values()) / sum(coi.values()), 2)
        ch.call_wall = max(coi, key=coi.get)
    if poi:
        ch.put_wall = max(poi, key=poi.get)
    strikes = sorted(set(coi) | set(poi))

    def pain(s: int) -> float:
        return sum(coi.get(k, 0) * max(s - k, 0) + poi.get(k, 0) * max(k - s, 0) for k in strikes)

    ch.max_pain = min(strikes, key=pain) if strikes else None
    return ch


_cache: dict[str, tuple[float, Chain | None]] = {}


def fetch_nse(underlying: str) -> Chain | None:
    """Best-effort live chain. NSE needs a cookie from the home page and blocks many networks."""
    hit = _cache.get(underlying)
    if hit and time.time() - hit[0] < 30:
        return hit[1]
    chain = None
    try:
        import httpx

        path = "option-chain-indices" if underlying.upper() in contracts.SPECS and underlying.upper() != "SENSEX" else None
        if path:
            with httpx.Client(headers=_HEADERS, timeout=8, follow_redirects=True) as c:
                c.get(_NSE)
                r = c.get(f"{_NSE}/api/{path}", params={"symbol": underlying.upper()})
                if r.status_code == 200:
                    chain = parse_nse(r.json(), underlying)
    except Exception:
        chain = None
    _cache[underlying] = (time.time(), chain)
    return chain


def model_chain(underlying: str, spot: float, vix: float, now: datetime, strikes_each_side: int = 12) -> Chain:
    exp = contracts.next_expiry(underlying, now)
    mins = contracts.minutes_to_expiry(exp, now)
    step, c0 = contracts.spec(underlying)["step"], contracts.atm(underlying, spot)
    ch = Chain(underlying.upper(), spot, exp, "model")
    sigma = vix / 100
    for i in range(-strikes_each_side, strikes_each_side + 1):
        k = c0 + i * step
        for kind in ("CE", "PE"):
            ch.quotes[(k, kind)] = Quote(k, kind, round(bs.price(spot, k, mins, sigma, kind), 2), sigma)
    return ch


def get_chain(underlying: str, spot: float, vix: float, now: datetime) -> Chain:
    live = fetch_nse(underlying)
    return live if live and live.spot > 0 else model_chain(underlying, spot, vix, now)

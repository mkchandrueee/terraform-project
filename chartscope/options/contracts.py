"""Index option contract specs: lot size, strike step, expiry calendar.

Lot sizes and expiry weekdays are set by the exchanges and change; they are defaults here and can be
overridden with env vars CHARTSCOPE_LOT_<UNDERLYING> (e.g. CHARTSCOPE_LOT_NIFTY=75). Verify against the
latest NSE/BSE circular before trading. Holiday-shifted expiries are not modelled.
"""

from __future__ import annotations

import calendar
import os
from datetime import date, datetime, time, timedelta

SPECS = {
    "NIFTY": {"yf": "^NSEI", "step": 50, "lot": 65, "expiry": ("weekly", 1)},  # Tuesday
    "BANKNIFTY": {"yf": "^NSEBANK", "step": 100, "lot": 30, "expiry": ("monthly", 1)},  # last Tuesday
    "SENSEX": {"yf": "^BSESN", "step": 100, "lot": 20, "expiry": ("weekly", 3)},  # Thursday (BSE)
}
CLOSE = time(15, 30)
OPEN = time(9, 15)


def spec(und: str) -> dict:
    u = und.upper()
    if u not in SPECS:
        raise ValueError(f"underlying must be one of {sorted(SPECS)}")
    return SPECS[u]


def lot_size(und: str) -> int:
    env = os.environ.get(f"CHARTSCOPE_LOT_{und.upper()}")
    return int(env) if env and env.isdigit() else spec(und)["lot"]


def atm(und: str, price: float) -> int:
    step = spec(und)["step"]
    return int(round(price / step) * step)


def _last_weekday(year: int, month: int, wd: int) -> date:
    d = date(year, month, calendar.monthrange(year, month)[1])
    return d - timedelta(days=(d.weekday() - wd) % 7)


def next_expiry(und: str, now: datetime) -> date:
    kind, wd = spec(und)["expiry"]
    today = now.date()
    live_today = now.time() < CLOSE

    def ok(d: date) -> bool:
        return d > today or (d == today and live_today)

    if kind == "weekly":
        d = today + timedelta(days=(wd - today.weekday()) % 7)
        return d if ok(d) else d + timedelta(days=7)
    d = _last_weekday(today.year, today.month, wd)
    if ok(d):
        return d
    y, m = (today.year + (today.month == 12), today.month % 12 + 1)
    return _last_weekday(y, m, wd)


def minutes_to_expiry(expiry: date, ts: datetime) -> float:
    return max((datetime.combine(expiry, CLOSE) - ts).total_seconds() / 60, 1.0)


def label(und: str, expiry: date, strike: int, kind: str) -> str:
    return f"{und.upper()} {expiry.strftime('%d%b').upper()} {strike} {kind}"

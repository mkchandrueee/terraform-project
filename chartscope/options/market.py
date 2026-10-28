"""Live inputs for the options engine: IST clock, session state, India VIX, index bars."""

from __future__ import annotations

import time
from datetime import datetime, time as dtime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from .. import data
from . import contracts

DEFAULT_VIX = 15.0
_vix: tuple[float, float] | None = None


def ist_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Kolkata")).replace(tzinfo=None, microsecond=0)


def is_session(ts: datetime) -> bool:
    return ts.weekday() < 5 and contracts.OPEN <= ts.time() < contracts.CLOSE


def get_vix() -> float:
    global _vix
    if _vix and time.time() - _vix[0] < 60:
        return _vix[1]
    v = DEFAULT_VIX
    try:
        import yfinance as yf

        h = yf.Ticker("^INDIAVIX").history(period="5d", interval="5m")
        if h.empty:
            h = yf.Ticker("^INDIAVIX").history(period="5d", interval="1d")
        if not h.empty:
            v = float(h["Close"].iloc[-1])
    except Exception:
        pass
    _vix = (time.time(), v)
    return v


def index_bars(und: str, interval: str) -> pd.DataFrame:
    return data.fetch(contracts.spec(und)["yf"], interval)


def daily_bias(daily: pd.DataFrame) -> str:
    """Cheap, deterministic daily trend read (also used in replay, so it avoids look-ahead)."""
    c = daily["close"]
    if len(c) < 55:
        return "neutral"
    e20, e50 = c.ewm(span=20, adjust=False).mean().iloc[-1], c.ewm(span=50, adjust=False).mean().iloc[-1]
    if c.iloc[-1] > e20 > e50:
        return "bullish"
    if c.iloc[-1] < e20 < e50:
        return "bearish"
    return "neutral"


def session_clock(df5: pd.DataFrame, now: datetime) -> dict:
    last = df5.index[-1].to_pydatetime()
    fresh = (now - last) <= timedelta(minutes=12)
    live = is_session(now) and last.date() == now.date() and fresh
    return {"now": str(now), "last_bar": str(last), "market_open": bool(live)}


def next_session_open(now: datetime) -> datetime:
    d = now.date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return datetime.combine(d, dtime(9, 30))

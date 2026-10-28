"""Market data: Yahoo Finance (via yfinance) with a synthetic DEMO feed for offline use."""

from __future__ import annotations

import threading
import time

import numpy as np
import pandas as pd

# How much history to pull per bar size. Long history is what the analog search runs on.
HISTORY_PERIOD = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "30m": "60d",
    "1h": "730d",
    "1d": "10y",
    "1wk": "20y",
}
INTERVALS = tuple(HISTORY_PERIOD)

INDEX_ALIASES = {
    "NIFTY": "^NSEI",
    "NIFTY50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "NIFTYBANK": "^NSEBANK",
    "SENSEX": "^BSESN",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
}

_CACHE: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}
_LOCK = threading.Lock()
CACHE_TTL = 15.0  # seconds; keeps a 30s UI poll cheap while staying "live"


def resolve_symbol(symbol: str) -> str:
    """RELIANCE -> RELIANCE.NS, NIFTY -> ^NSEI. Anything with a suffix/caret is passed through."""
    s = symbol.strip().upper()
    if s in INDEX_ALIASES:
        return INDEX_ALIASES[s]
    if s.startswith("^") or "." in s or "=" in s or "-" in s or s.startswith("DEMO"):
        return s
    return s + ".NS"


def _clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].copy()
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[(df["high"] >= df["low"]) & (df["close"] > 0)]
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:  # show exchange-local wall clock, naive
        idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
    df.index = idx
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.astype(float)


def fetch(symbol: str, interval: str = "15m", *, use_cache: bool = True) -> pd.DataFrame:
    """Return OHLCV (lowercase columns, naive IST index) with the longest useful history."""
    if interval not in HISTORY_PERIOD:
        raise ValueError(f"interval must be one of {INTERVALS}")
    sym = resolve_symbol(symbol)
    key = (sym, interval)
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if use_cache and hit and now - hit[0] < CACHE_TTL:
            return hit[1]

    if sym.startswith("DEMO"):
        df = synthetic(interval=interval)
    else:
        import yfinance as yf

        raw = yf.Ticker(sym).history(period=HISTORY_PERIOD[interval], interval=interval, auto_adjust=True)
        if raw is None or raw.empty:
            raise LookupError(f"No data for {sym} ({interval}). Check the symbol; Indian stocks use NSE tickers like RELIANCE.")
        df = _clean(raw)
    if len(df) < 120:
        raise LookupError(f"Only {len(df)} bars for {sym} ({interval}); need at least 120.")
    with _LOCK:
        _CACHE[key] = (now, df)
    return df


def synthetic(n: int = 4000, interval: str = "15m", seed: int = 7) -> pd.DataFrame:
    """Seeded random walk with recurring swing structure, so patterns and analogs exist offline."""
    rng = np.random.default_rng(seed)
    t = np.arange(n)
    drift = 0.0009 * np.sin(t / 55.0) + 0.0003 * np.sin(t / 17.0)
    rets = drift + rng.normal(0, 0.0045, n)
    close = 1000 * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[close[0]], close[:-1]]) * (1 + rng.normal(0, 0.0008, n))
    span = np.abs(rng.normal(0, 0.003, n)) + 0.001
    high = np.maximum(open_, close) * (1 + span)
    low = np.minimum(open_, close) * (1 - span)
    vol = rng.integers(50_000, 400_000, n).astype(float)
    freq = {"1d": "B", "1wk": "W-FRI", "1h": "h"}.get(interval, interval.replace("m", "min"))
    if freq in ("B", "W-FRI"):
        idx = pd.date_range(end=pd.Timestamp.now().normalize(), periods=n, freq=freq)
    else:
        idx = pd.date_range(end=pd.Timestamp.now().floor("min"), periods=n, freq=freq)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)

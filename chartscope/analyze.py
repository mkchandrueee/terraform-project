"""Orchestrates data -> levels -> patterns -> analogs -> trade plan into one JSON-able dict."""

from __future__ import annotations

from dataclasses import asdict

import pandas as pd

from . import data
from .indicators import atr, ema, is_intraday, rsi
from .levels import build_levels
from .patterns import detect_patterns
from .calls import build_calls
from .similarity import find_analogs
from .trade import build_plan

CHART_BARS = 300


def _ts(idx: pd.Timestamp) -> int:
    """Naive IST wall-clock -> epoch seconds as if UTC (what lightweight-charts displays)."""
    return int(pd.Timestamp(idx).replace(tzinfo=None).tz_localize("UTC").timestamp())


def analyze(
    symbol: str,
    interval: str = "15m",
    capital: float = 100_000.0,
    risk_pct: float = 1.0,
    window: int | None = None,
    horizon: int | None = None,
    df: pd.DataFrame | None = None,
) -> dict:
    explicit = df is not None
    if df is None:
        df = data.fetch(symbol, interval)
    window = window or (30 if interval in ("1d", "1wk") else 40)
    horizon = horizon or (10 if interval in ("1d", "1wk") else 20)

    price = float(df["close"].iloc[-1])
    a = float(atr(df).iloc[-1])
    e20, e50 = ema(df["close"], 20), ema(df["close"], 50)
    r = float(rsi(df["close"]).iloc[-1])
    trend = 0.0
    trend += 0.5 if price > e20.iloc[-1] else -0.5
    trend += 0.5 if e20.iloc[-1] > e50.iloc[-1] else -0.5

    levels = build_levels(df)
    patterns = detect_patterns(df, levels)
    analogs, stats = find_analogs(df, window, horizon, current_patterns=[p.name for p in patterns])
    plan = build_plan(price, a, patterns, levels, stats, trend, capital, risk_pct)

    tail = df.iloc[-CHART_BARS:]
    base = len(df) - len(tail)
    t_of = lambda i: _ts(df.index[min(max(int(i), 0), len(df) - 1)])  # noqa: E731

    cur = df["close"].iloc[-window:].to_numpy()
    cur_path = ((cur / cur[0] - 1) * 100).round(3).tolist()
    ana = []
    for x in analogs:
        seg = df["close"].iloc[x.start_idx : x.end_idx + horizon + 1].to_numpy()
        d = asdict(x)
        d.update(
            start=str(df.index[x.start_idx]), end=str(df.index[x.end_idx]),
            path=((seg / seg[0] - 1) * 100).round(3).tolist(),
        )
        ana.append(d)

    daily_df, intra_df, intra_iv = df, df, interval
    if not explicit:
        try:
            if interval not in ("1d", "1wk") or interval == "1wk":
                daily_df = data.fetch(symbol, "1d")
            if interval in ("1d", "1wk"):
                intra_iv = "15m"
                intra_df = data.fetch(symbol, "15m")
        except Exception:  # missing intraday feed shouldn't kill the main analysis
            intra_df = None
    calls = build_calls(daily_df, intra_df, intra_iv, capital, risk_pct, index=data.resolve_symbol(symbol).startswith("^"))

    return {
        "calls": calls,
        "symbol": symbol.upper(),
        "resolved": data.resolve_symbol(symbol),
        "interval": interval,
        "intraday": is_intraday(df),
        "asof": str(df.index[-1]),
        "bars_total": len(df),
        "history_start": str(df.index[0]),
        "price": round(price, 2),
        "atr": round(a, 2),
        "rsi": round(r, 1),
        "ema20": round(float(e20.iloc[-1]), 2),
        "ema50": round(float(e50.iloc[-1]), 2),
        "trend": "up" if trend > 0.5 else "down" if trend < -0.5 else "sideways",
        "candles": [
            {"time": _ts(i), "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2), "volume": v}
            for i, o, h, l, c, v in tail[["open", "high", "low", "close", "volume"]].itertuples(index=True, name=None)
        ],
        "levels": [
            {**asdict(lv), "last_time": t_of(lv.last_idx)} for lv in levels
        ],
        "patterns": [
            {
                **{k: v for k, v in asdict(p).items() if k not in ("points", "lines")},
                "points": [{"time": t_of(i), "price": round(v, 2), "visible": i >= base} for i, v in p.points],
                "lines": [[{"time": t_of(max(i, base)), "price": round(v, 2)} for i, v in ln] for ln in p.lines],
            }
            for p in patterns
        ],
        "analogs": ana,
        "analog_stats": asdict(stats),
        "current_path": cur_path,
        "plan": asdict(plan),
    }

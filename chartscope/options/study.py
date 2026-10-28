"""Signal study: does each setup have a directional edge on the underlying, before options and costs?

Every raw idea is simulated on the underlying with the live management rules (half at T1, stop to cost,
60-minute time stop, 15:15 exit) and scored in R. Pooling a basket of instruments gives thousands of samples,
so setup/filter choices rest on more than one index's 45 sessions. Split by date for out-of-sample checks.
"""

from __future__ import annotations

from datetime import time as dtime

import numpy as np
import pandas as pd

from .. import data
from . import market
from .intraday import build_context, generate_ideas

BASKET = ["^NSEI", "^NSEBANK", "^BSESN", "RELIANCE.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "TCS.NS",
          "SBIN.NS", "AXISBANK.NS", "LT.NS", "ITC.NS", "KOTAKBANK.NS"]
COOLDOWN_BARS = 6


def simulate(idea, future: pd.DataFrame) -> dict | None:
    """Underlying-only outcome in R using the live rules. `future` = bars after the idea, same session."""
    s = 1 if idea.side == "LONG" else -1
    risk = s * (idea.entry - idea.stop)
    entered, entry_px, stop, t1hit, start = False, None, idea.stop, False, None
    for k, (ts, b) in enumerate(future.iterrows()):
        hi, lo = (b["high"], b["low"]) if s == 1 else (-b["low"], -b["high"])
        if not entered:
            if k * 5 >= idea.valid_minutes and idea.mode != "market":
                return None
            if idea.mode == "market":
                entered, entry_px, start = True, idea.entry, k
            elif (idea.mode == "stop" and hi >= s * idea.entry) or (idea.mode == "limit" and lo <= s * idea.entry):
                entered, entry_px, start = True, idea.entry, k
            elif lo <= s * idea.stop:
                return None
            else:
                continue
        r_of = lambda px: s * (px - entry_px) / risk  # noqa: E731
        if lo <= s * stop:
            exit_r = r_of(stop)
            return {"r": (0.5 * r_of(idea.targets[0]) + 0.5 * exit_r) if t1hit else exit_r, "bars": k - start, "how": "be" if t1hit else "stop"}
        if not t1hit and hi >= s * idea.targets[0]:
            t1hit, stop = True, entry_px
        if t1hit and hi >= s * idea.targets[1]:
            return {"r": 0.5 * r_of(idea.targets[0]) + 0.5 * r_of(idea.targets[1]), "bars": k - start, "how": "t2"}
        end = (ts + pd.Timedelta(minutes=5)).time()
        if end >= dtime(15, 15) or ((k - start) >= 12 and not t1hit and r_of(b["close"]) < 0.1):
            exit_r = r_of(b["close"])
            return {"r": (0.5 * r_of(idea.targets[0]) + 0.5 * exit_r) if t1hit else exit_r, "bars": k - start, "how": "time"}
    if entered:
        exit_r = s * (future["close"].iloc[-1] - entry_px) / risk
        return {"r": (0.5 * s * (idea.targets[0] - entry_px) / risk + 0.5 * exit_r) if t1hit else exit_r, "bars": len(future) - start, "how": "eod"}
    return None


def collect(symbol: str, days: int = 60) -> pd.DataFrame:
    df5 = data.fetch(symbol, "5m")
    daily = data.fetch(symbol, "1d")
    rows = []
    for d in sorted(set(df5.index.date))[-days:]:
        pos = np.flatnonzero(df5.index.date == d)
        if len(pos) < 60:
            continue
        bias = market.daily_bias(daily[daily.index.date < d])
        last_seen: dict[tuple, int] = {}
        for i in pos:
            end = (df5.index[i] + pd.Timedelta(minutes=5)).time()
            if not dtime(9, 30) <= end <= dtime(14, 45):
                continue
            hist = df5.iloc[max(0, i - 1500) : i + 1]
            ctx = build_context(hist, bias, None)
            for idea in generate_ideas(ctx, hist, min_conf=0, raw=True):
                key = (idea.family, idea.side)
                if i - last_seen.get(key, -99) < COOLDOWN_BARS:
                    continue
                last_seen[key] = i
                out = simulate(idea, df5.iloc[i + 1 : pos[-1] + 1])
                if out is None:
                    continue
                s = 1 if idea.side == "LONG" else -1
                rows.append({
                    "symbol": symbol, "date": d, "time": end.strftime("%H:%M"), "family": idea.family, "setup": idea.setup, "side": idea.side,
                    "mode": idea.mode, "conf": idea.confidence, "aligned": idea.aligned, "r": out["r"], "how": out["how"], "bars": out["bars"],
                    "with_trend5": (ctx.trend == ("up" if s == 1 else "down")), "with_daily": ctx.daily_bias == ("bullish" if s == 1 else "bearish"),
                    "vwap_side": s * (ctx.spot - ctx.vwap) > 0, "open_loc": ctx.open_loc,
                    "prof_shape": ctx.profile.shape if ctx.profile else "?", "eff": round(ctx.efficiency, 3),
                    "gap": ctx.gap_pct * s, "rsi": ctx.rsi, "risk_atr": s * (idea.entry - idea.stop) / ctx.atr,
                    "day_range_atr": (ctx.day_high - ctx.day_low) / ctx.atr,
                })
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, by: list[str] | str) -> pd.DataFrame:
    g = df.groupby(by)["r"]
    out = pd.DataFrame({"n": g.size(), "mean_r": g.mean(), "win": g.apply(lambda x: (x > 0).mean()), "t": g.mean() / (g.std() / np.sqrt(g.size()))})
    return out.round(3).sort_values("n", ascending=False)

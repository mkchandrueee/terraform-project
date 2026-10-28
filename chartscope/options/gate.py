"""Walk-forward confidence gate: trade a setup family/side only if it has been working recently.

For a trading day D it looks at raw ideas from the previous LOOKBACK sessions on the same instrument (simulated
with the live rules, see study.py) and allows a family/side when it has >= MIN_N samples and mean R > MIN_R.
Uses only data before D, so the same gate is valid in replay and live.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd

from . import contracts
from .study import collect

LOOKBACK, MIN_N, MIN_R = 20, 30, 0.05
_mem: dict[str, pd.DataFrame] = {}


def _cache_path(symbol: str, last: date) -> Path:
    base = Path(os.environ.get("CHARTSCOPE_STATE", ".chartscope/calls.json")).parent
    return base / "study" / f"{symbol.replace('^', '')}_{last}.pkl"


def history(symbol: str, last_session: date, compute: bool = True) -> pd.DataFrame | None:
    """Raw-idea outcomes for the instrument, computed once per data day and cached on disk."""
    key = f"{symbol}_{last_session}"
    if key in _mem:
        return _mem[key]
    path = _cache_path(symbol, last_session)
    try:
        df = pd.read_pickle(path)
    except Exception:
        if not compute:
            return None
        df = collect(symbol, days=LOOKBACK + 45)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.to_pickle(path)
        except OSError:
            pass
    _mem[key] = df
    return df


def allowed(hist: pd.DataFrame, day: date) -> dict[tuple[str, str], dict]:
    """{(family, side): {n, mean_r, ok}} from the LOOKBACK sessions strictly before `day`."""
    if hist is None or hist.empty:
        return {}
    days = sorted(d for d in hist["date"].unique() if d < day)[-LOOKBACK:]
    past = hist[hist["date"].isin(days)]
    out = {}
    for (fam, side), g in past.groupby(["family", "side"]):
        m = float(g["r"].mean())
        out[(fam, side)] = {"n": int(len(g)), "mean_r": round(m, 3), "ok": len(g) >= MIN_N and m > MIN_R}
    return out


def for_underlying(und: str, last_session: date, compute: bool = True) -> pd.DataFrame | None:
    return history(contracts.spec(und)["yf"], last_session, compute)

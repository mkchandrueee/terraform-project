"""Historical analog search: find past windows shaped like the current one, measure what followed."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from .indicators import atr
from .patterns import detect_patterns


@dataclass
class Analog:
    start_idx: int
    end_idx: int
    similarity: float  # 0-1
    fwd_return_pct: float
    fwd_atr: float  # forward close move in units of ATR at match end
    mfe_atr: float  # best excursion in trade direction "up" (ATR units)
    mae_atr: float  # worst excursion down (ATR units, negative)
    patterns: list[str] = field(default_factory=list)
    same_pattern: bool = False


@dataclass
class AnalogStats:
    n: int
    window: int
    horizon: int
    avg_similarity: float
    win_rate_up: float
    median_return_pct: float
    median_fwd_atr: float
    median_mfe_atr: float
    median_mae_atr: float
    n_same_pattern: int
    win_rate_up_same_pattern: float | None


def find_analogs(
    df: pd.DataFrame,
    window: int = 40,
    horizon: int = 20,
    top_k: int = 12,
    min_similarity: float = 0.6,
    current_patterns: list[str] | None = None,
) -> tuple[list[Analog], AnalogStats]:
    close = df["close"].to_numpy()
    n = len(close)
    empty = AnalogStats(0, window, horizon, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, None)
    if n < window * 3 + horizon:
        return [], empty

    logc = np.log(close)
    wins = sliding_window_view(logc, window)  # (n-window+1, window); row r ends at r+window-1
    cur = wins[-1]
    cz = (cur - cur.mean()) / (cur.std() or 1.0)
    mu = wins.mean(axis=1, keepdims=True)
    sd = wins.std(axis=1, keepdims=True)
    sd[sd == 0] = 1.0
    corr = ((wins - mu) / sd) @ cz / window

    # Penalise windows whose volatility differs a lot from the current one.
    rets = np.diff(logc)
    rv = sliding_window_view(rets, window - 1).std(axis=1)  # row r -> window starting r
    cv = rv[-1] or 1e-9
    vol_ratio = np.minimum(rv, cv) / np.maximum(rv, cv)
    sim = np.clip(corr, 0, 1) * (0.7 + 0.3 * vol_ratio)

    ends = np.arange(window - 1, n)
    valid = (ends <= n - 1 - window) & (ends + horizon <= n - 1) & (sim >= min_similarity)
    cand = np.flatnonzero(valid)
    cand = cand[np.argsort(-sim[cand])]

    atr_s = atr(df).to_numpy()
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    chosen: list[int] = []
    for r in cand:  # non-maximum suppression so one move isn't counted many times
        if all(abs(r - c) >= window // 2 for c in chosen):
            chosen.append(int(r))
        if len(chosen) >= top_k:
            break

    cur_names = set(current_patterns or [])
    analogs: list[Analog] = []
    for r in chosen:
        s, e = r, r + window - 1
        entry, a = close[e], max(atr_s[e], 1e-9)
        fwd = close[e + horizon]
        names = [p.name for p in detect_patterns(df.iloc[s : e + 1].reset_index(drop=True), None, lookback=window)]
        analogs.append(
            Analog(
                s, e, float(sim[r]), float((fwd / entry - 1) * 100), float((fwd - entry) / a),
                float((high[e + 1 : e + horizon + 1].max() - entry) / a),
                float((low[e + 1 : e + horizon + 1].min() - entry) / a),
                names, bool(cur_names & set(names)),
            )
        )
    if not analogs:
        return [], empty

    up = np.array([x.fwd_return_pct > 0 for x in analogs])
    same = [x for x in analogs if x.same_pattern]
    stats = AnalogStats(
        n=len(analogs), window=window, horizon=horizon,
        avg_similarity=float(np.mean([x.similarity for x in analogs])),
        win_rate_up=float(up.mean()),
        median_return_pct=float(np.median([x.fwd_return_pct for x in analogs])),
        median_fwd_atr=float(np.median([x.fwd_atr for x in analogs])),
        median_mfe_atr=float(np.median([x.mfe_atr for x in analogs])),
        median_mae_atr=float(np.median([x.mae_atr for x in analogs])),
        n_same_pattern=len(same),
        win_rate_up_same_pattern=float(np.mean([x.fwd_return_pct > 0 for x in same])) if same else None,
    )
    return analogs, stats

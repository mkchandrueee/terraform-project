"""Ties the pieces together: live refresh and historical replay share the same call-creation rules."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, time as dtime

import numpy as np
import pandas as pd

from . import chain as chainmod
from . import contracts, market
from . import gate
from . import intraday
from .intraday import build_context, generate_ideas, premarket_ideas
from .monitor import LiveCall, Store, new_live_call, update
from .pricing import make_option_call

MAX_CALLS_PER_DAY = 3
STOP_DAY_R = -2.0
ENTRY_FROM, ENTRY_UNTIL = dtime(9, 30), dtime(12, 0)  # morning reversals tested better than midday in both periods


def entries_allowed(ts: datetime) -> bool:
    return ENTRY_FROM <= ts.time() <= ENTRY_UNTIL and ts.weekday() < 5


def day_realized_r(calls: list[LiveCall]) -> float:
    return sum(c.r_multiple or 0.0 for c in calls if not c.open)


def maybe_create(calls, ideas, ctx, chain, capital, risk_pct, now, vix, preview=False, allow=None) -> list[LiveCall]:
    """Price new ideas into option calls, honouring the day-level risk rules and the walk-forward gate."""
    made: list[LiveCall] = []
    if allow is not None:
        ideas = [i for i in ideas if allow.get((i.family, i.side), {}).get("ok")]
    if not preview:
        if not entries_allowed(now) or len(calls) >= MAX_CALLS_PER_DAY or day_realized_r(calls) <= STOP_DAY_R:
            return made
    for idea in ideas:
        oc = make_option_call(idea, ctx, chain, capital, risk_pct, now, vix)
        if oc is None:
            continue
        if not preview:
            if any(c.call["id"] == oc.id for c in calls + made):
                continue  # one call per setup+side per day
            if any(c.open and c.call["side"] == oc.side for c in calls + made):
                continue  # don't stack the same direction
            if len(calls) + len(made) >= MAX_CALLS_PER_DAY:
                break
        made.append(new_live_call(oc, now, ctx.spot) if not preview else LiveCall(call=asdict(oc), status="PREVIEW", last_ts=str(now)))
    return made


def _gate_hist(und: str, df5: pd.DataFrame, compute: bool = False) -> pd.DataFrame | None:
    """Evidence history keyed on the previous session (so it is built once per day). Requests only read the cache;
    the server's startup thread builds it, so a page load never blocks for the ~90s computation."""
    prev = sorted(set(df5.index.date))[-2] if len(set(df5.index.date)) > 1 else df5.index[-1].date()
    try:
        return gate.for_underlying(und, prev, compute)
    except Exception:
        return None


def refresh(und: str, store: Store, capital: float = 300_000, risk_pct: float = 1.0, now: datetime | None = None) -> dict:
    """One live tick: update open calls with new 1m bars, look for new setups, return the dashboard payload."""
    und = und.upper()
    now = now or market.ist_now()
    df5 = market.index_bars(und, "5m")
    daily = market.index_bars(und, "1d")
    vix = market.get_vix()
    clock = market.session_clock(df5, now)
    live = clock["market_open"]
    last_day = str(df5.index[-1].date())
    bias = market.daily_bias(daily[daily.index.date < df5.index[-1].date()] if len(daily) > 60 else daily)
    ctx = build_context(df5, bias, vix)
    chain = chainmod.get_chain(und, ctx.spot, vix, ctx.ts)
    calls = store.day_calls(und, last_day)
    replayed: list[LiveCall] = []

    if live:
        try:
            b1 = market.index_bars(und, "1m")
        except Exception:
            b1 = df5
        for lc in calls:
            if lc.open:
                update(lc, b1[b1.index.to_series().dt.date == df5.index[-1].date()])
        ideas = generate_ideas(ctx, df5)
        allow = gate.allowed(_gate_hist(und, df5), df5.index[-1].date())
        for lc in maybe_create(calls, ideas, ctx, chain, capital, risk_pct, ctx.ts, vix, allow=allow):
            store.add(und, lc)
            calls.append(lc)
        store.save()
        preview = []
    else:  # closed: a conditional plan for the next session, plus a replay of what today's rules did
        nxt = market.next_session_open(now if now.date() > df5.index[-1].date() or now.time() > contracts.CLOSE else datetime.combine(now.date() - pd.Timedelta(days=1), dtime(15, 30)))
        pre_chain = chainmod.Chain(und, ctx.spot, contracts.next_expiry(und, nxt), "model")
        preview = maybe_create([], premarket_ideas(ctx), ctx, pre_chain, capital, risk_pct, nxt, vix, preview=True)
        hist = _gate_hist(und, df5)
        replayed = replay_day(df5, daily, und, df5.index[-1].date(), vix, capital, risk_pct, gate.allowed(hist, df5.index[-1].date()))
        calls = [c for c in replayed if c.entered_at] if not calls else calls

    events = sorted((dict(e, id=c.call["symbol"]) for c in calls for e in c.events), key=lambda e: e["ts"])[-40:]
    day = df5[df5.index.date == df5.index[-1].date()]
    typical = (day["high"] + day["low"] + day["close"]) / 3
    vwap_series = (typical.expanding().mean() if day["volume"].sum() == 0 else (typical * day["volume"]).cumsum() / day["volume"].cumsum())
    tail = df5.iloc[-190:]
    ts = lambda i: int(pd.Timestamp(i).tz_localize("UTC").timestamp())  # noqa: E731
    return {
        "underlying": und, "clock": clock, "vix": round(vix, 2), "lot_size": contracts.lot_size(und),
        "expiry": chain.expiry.isoformat(), "chain_source": chain.source,
        "chain": {"pcr": chain.pcr, "max_pain": chain.max_pain, "call_wall": chain.call_wall, "put_wall": chain.put_wall},
        "context": {
            "spot": round(ctx.spot, 2), "atr15": round(ctx.atr, 1), "vwap": round(ctx.vwap, 2), "vwap_volume_weighted": ctx.vwap_is_volume_weighted,
            "or_high": ctx.or_high, "or_low": ctx.or_low, "day_high": ctx.day_high, "day_low": ctx.day_low,
            "prev_high": ctx.prev_high, "prev_low": ctx.prev_low, "prev_close": ctx.prev_close, "gap_pct": ctx.gap_pct,
            "trend": ctx.trend, "rsi": round(ctx.rsi, 1), "daily_bias": ctx.daily_bias, "bias_score": round(ctx.bias_score, 2),
            "expected_move": None if ctx.expected_move is None else round(float(ctx.expected_move), 1),
            "patterns": [{"name": p.name, "bias": p.bias, "status": p.status, "confidence": p.confidence} for p in ctx.patterns[:4]],
            "levels": [{"price": round(x.price, 1), "kind": x.kind, "strength": x.strength} for x in ctx.levels],
        },
        "calls": [{**asdict(c), "open": c.open} for c in calls],
        "gate": [{"family": f, "side": s, **v} for (f, s), v in sorted((gate.allowed(_gate_hist(und, df5), df5.index[-1].date()) or {}).items())
                 if f in (intraday.ENABLED or ())],
        "preview": [asdict(c) for c in preview],
        "replayed": not live and bool(calls),
        "events": events,
        "day_r": round(day_realized_r(calls), 2),
        "candles": [{"time": ts(i), "open": round(o, 2), "high": round(h, 2), "low": round(l, 2), "close": round(c, 2)}
                    for i, o, h, l, c in tail[["open", "high", "low", "close"]].itertuples(index=True, name=None)],
        "vwap_series": [{"time": ts(i), "value": round(float(v), 2)} for i, v in vwap_series.items()],
        "rules": {"entries": "09:30-14:45 IST", "max_calls_per_day": MAX_CALLS_PER_DAY, "stop_for_day_at_r": STOP_DAY_R, "square_off": "15:15 IST"},
    }


# ── historical replay ───────────────────────────────────────────────────────────────────────────

def _vix_by_date() -> dict:
    try:
        import yfinance as yf

        h = yf.Ticker("^INDIAVIX").history(period="6mo", interval="1d")
        s = h["Close"]
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
        return {d.date(): float(v) for d, v in s.shift(1).dropna().items()}  # previous close: known at the open
    except Exception:
        return {}


def replay_day(df5: pd.DataFrame, daily: pd.DataFrame, und: str, day, vix: float, capital: float, risk_pct: float, allow=None) -> list[LiveCall]:
    pos = np.flatnonzero(df5.index.date == day)
    if len(pos) < 30:
        return []
    bias = market.daily_bias(daily[daily.index.date < day])
    calls: list[LiveCall] = []
    for i in pos:
        bar = df5.iloc[i : i + 1]
        for lc in calls:
            if lc.open:
                update(lc, bar)
        now = (bar.index[0] + pd.Timedelta(minutes=5)).to_pydatetime()
        if not entries_allowed(now) or len(calls) >= MAX_CALLS_PER_DAY or day_realized_r(calls) <= STOP_DAY_R:
            continue
        hist = df5.iloc[: i + 1]
        ctx = build_context(hist, bias, vix)
        ch = chainmod.Chain(und, ctx.spot, contracts.next_expiry(und, now), "model")
        calls += maybe_create(calls, generate_ideas(ctx, hist), ctx, ch, capital, risk_pct, now, vix, allow=allow)
    for lc in calls:  # anything still open at the end of the data is closed at the last price
        if lc.open and lc.entered_at:
            from .monitor import _close
            last = df5.iloc[pos[-1]]
            _close(lc, datetime.fromisoformat(lc.last_ts), float(last["close"]), "SQUAREOFF", "end of data")
        elif lc.open:
            lc.status = "EXPIRED"
    return calls


def backtest(und: str, days: int = 20, capital: float = 300_000, risk_pct: float = 1.0, use_gate: bool = True) -> dict:
    und = und.upper()
    df5, daily, vixes = market.index_bars(und, "5m"), market.index_bars(und, "1d"), _vix_by_date()
    all_days = sorted({d for d in df5.index.date})
    hist = gate.for_underlying(und, all_days[-1]) if use_gate else None
    # the gate needs LOOKBACK prior sessions, so the replay can only start after them
    dates = all_days[gate.LOOKBACK:][-days:] if use_gate else all_days[-days:]
    trades: list[dict] = []
    per_day = []
    for d in dates:
        calls = replay_day(df5, daily, und, d, vixes.get(d, market.DEFAULT_VIX), capital, risk_pct, gate.allowed(hist, d) if use_gate else None)
        done = [c for c in calls if c.entered_at]
        per_day.append({"date": str(d), "trades": len(done), "r": round(float(sum(c.r_multiple or 0 for c in done)), 2)})
        for c in done:
            trades.append({"date": str(d), "setup": c.call["setup"], "side": c.call["side"], "symbol": c.call["symbol"], "status": c.status,
                           "entered": c.entered_at, "r": c.r_multiple, "pnl": c.pnl, "gross_pnl": c.gross_pnl, "cost": c.cost, "confidence": c.call["confidence"]})
    return {"underlying": und, "days": len(dates), "from": str(dates[0]), "to": str(dates[-1]), "summary": summarize(trades), "by_setup": group(trades, "setup"),
            "by_side": group(trades, "side"), "per_day": per_day, "trades": trades,
            "caveat": "All P&L and R are net of estimated costs. Premiums are Black-Scholes estimates (India VIX) and fills are assumed at trigger levels with stop-first ordering inside a bar; real results will differ."}


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    r = np.array([t["r"] for t in trades], float)
    pnl = np.array([t["pnl"] for t in trades], float)
    wins, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    eq = np.cumsum(pnl)
    return {"n": len(trades), "win_rate": round(float((pnl > 0).mean()), 3), "avg_r": round(float(r.mean()), 3), "total_r": round(float(r.sum()), 2),
            "total_pnl": round(float(pnl.sum()), 0), "gross_pnl": round(float(sum(t["gross_pnl"] for t in trades)), 0), "costs": round(float(sum(t["cost"] for t in trades)), 0), "profit_factor": round(float(wins / losses), 2) if losses else None,
            "max_drawdown": round(float((np.maximum.accumulate(eq) - eq).max()), 0)}


def group(trades: list[dict], key: str) -> dict:
    out: dict = {}
    for k in sorted({t[key] for t in trades}):
        out[k] = summarize([t for t in trades if t[key] == k])
    return out

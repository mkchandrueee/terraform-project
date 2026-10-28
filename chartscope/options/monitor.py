"""Live call lifecycle: WAITING -> ACTIVE -> T1 -> TARGET / STOPPED / TIME_EXIT / SQUAREOFF."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

import pandas as pd

from .pricing import OptionCall, premium_at

SQUAREOFF = dtime(15, 15)
TIME_STOP_MIN = 60
OPEN_STATES = ("WAITING", "ACTIVE", "T1")


@dataclass
class LiveCall:
    call: dict
    status: str = "WAITING"
    last_ts: str = ""
    entered_at: str | None = None
    u_entry: float | None = None
    u_stop: float | None = None  # current (possibly trailed) stop
    t1_hit: bool = False
    exit_u: float | None = None
    exit_at: str | None = None
    exit_reason: str | None = None
    r_multiple: float | None = None
    pnl: float | None = None  # rupees, whole position, NET of costs
    gross_pnl: float | None = None
    cost: float | None = None
    mark_premium: float | None = None
    events: list[dict] = field(default_factory=list)

    @property
    def open(self) -> bool:
        return self.status in OPEN_STATES

    def _ev(self, ts: datetime, msg: str, kind: str = "info") -> None:
        self.events.append({"ts": str(ts), "kind": kind, "msg": msg})


def trade_cost(buy_value: float, sell_value: float, orders: int) -> float:
    """Approximate India index-option round-trip costs: brokerage, STT on sell, exchange fee, GST, stamp, slippage."""
    brokerage = 20.0 * orders
    exchange = 0.0003503 * (buy_value + sell_value)
    gst = 0.18 * (brokerage + exchange)
    stt = 0.001 * sell_value
    stamp = 0.00003 * buy_value
    slippage = 0.005 * (buy_value + sell_value)  # ~half a tick each way on a ~100-200 premium
    return brokerage + exchange + gst + stt + stamp + slippage


def new_live_call(call: OptionCall, now: datetime, spot: float) -> LiveCall:
    lc = LiveCall(call=asdict(call), last_ts=str(now), u_stop=call.u_stop)
    lc._ev(now, f"New call: {call.side} {call.symbol} ({call.setup}), conf {call.confidence}%")
    if call.mode == "market":
        _enter(lc, now, spot)
    else:
        lc._ev(now, f"Waiting for {call.underlying} to {'cross' if call.mode == 'stop' else 'pull back to'} {call.u_entry}")
    return lc


def _enter(lc: LiveCall, ts: datetime, u: float) -> None:
    lc.status, lc.entered_at, lc.u_entry = "ACTIVE", str(ts), u
    c = lc.call
    prem = premium_at(c, u, ts)
    lc._ev(ts, f"ENTRY: buy {c['symbol']} ≈ ₹{prem:.2f} (underlying {u:.1f}); stop {lc.u_stop}", "entry")


def _close(lc: LiveCall, ts: datetime, u: float, status: str, reason: str) -> None:
    c = lc.call
    entry_u = lc.u_entry
    p_in = premium_at(c, entry_u, datetime.fromisoformat(lc.entered_at))
    p_out = premium_at(c, u, ts)
    risk = c["entry_premium"] - c["stop_premium"]
    if lc.t1_hit:
        p_t1 = c["target_premiums"][0]
        per = 0.5 * (p_t1 - p_in) + 0.5 * (p_out - p_in)
    else:
        per = p_out - p_in
    qty = c["qty"]
    sell_px = (0.5 * c["target_premiums"][0] + 0.5 * p_out) if lc.t1_hit else p_out
    lc.cost = round(trade_cost(p_in * qty, sell_px * qty, 3 if lc.t1_hit else 2), 2)
    lc.status, lc.exit_u, lc.exit_at, lc.exit_reason = status, u, str(ts), reason
    lc.gross_pnl = round(per * qty, 2)
    lc.pnl = round(lc.gross_pnl - lc.cost, 2)
    lc.r_multiple = round(lc.pnl / (risk * qty), 2) if risk > 0 else 0.0
    lc._ev(ts, f"{status}: {reason}. Underlying {u:.1f}, net P&L ≈ ₹{lc.pnl:,.0f} after ₹{lc.cost:,.0f} costs ({lc.r_multiple:+.2f}R)", "exit")


def update(lc: LiveCall, bars: pd.DataFrame) -> None:
    """Advance the call through bars (index = bar START; each bar is processed at its END time)."""
    c = lc.call
    s = 1 if c["side"] == "LONG" else -1
    step = bars.index.to_series().diff().median() if len(bars) > 1 else pd.Timedelta(minutes=5)
    for start, b in bars.iterrows():
        if not lc.open:
            break
        end = (start + step).to_pydatetime()
        if str(end) <= lc.last_ts:
            continue
        lc.last_ts = str(end)
        o, h, l, cl = b["open"], b["high"], b["low"], b["close"]
        hi, lo = (h, l) if s == 1 else (-l, -h)  # work in "long" space
        stop = s * lc.u_stop
        if lc.status == "WAITING":
            if end > datetime.fromisoformat(c["valid_until"]):
                lc.status = "EXPIRED"
                lc._ev(end, "Expired before the entry level was reached", "exit")
                break
            ent = s * c["u_entry"]
            if (c["mode"] == "stop" and hi >= ent) or (c["mode"] == "limit" and lo <= ent):
                px = max(ent, s * o) if c["mode"] == "stop" else min(ent, s * o)
                _enter(lc, end, s * px)  # fall through: a bar that tags entry and stop is treated as entered, then stopped
            elif lo <= stop:
                lc.status = "CANCELLED"
                lc._ev(end, "Stop level hit before entry: setup cancelled", "exit")
                break
            else:
                continue
        # ACTIVE / T1: stop is checked before targets within a bar (conservative)
        t1, t2 = s * c["u_targets"][0], s * c["u_targets"][1]
        if lo <= s * lc.u_stop:
            px = min(s * lc.u_stop, s * o)
            if lc.t1_hit:
                _close(lc, end, s * px, "T1_EXIT", "stopped at cost after booking half at T1")
            else:
                _close(lc, end, s * px, "STOPPED", "stop hit")
            break
        if not lc.t1_hit and hi >= t1:
            lc.t1_hit, lc.status, lc.u_stop = True, "T1", lc.u_entry
            lc._ev(end, f"T1 {c['u_targets'][0]} reached: book half, stop moved to cost {lc.u_entry:.1f}", "target")
        if lc.t1_hit and hi >= t2:
            _close(lc, end, s * t2, "TARGET", "T2 reached")
            break
        if end.time() >= SQUAREOFF:
            _close(lc, end, cl, "SQUAREOFF", "end-of-day square-off")
            break
        mins = (end - datetime.fromisoformat(lc.entered_at)).total_seconds() / 60
        if mins >= TIME_STOP_MIN and not lc.t1_hit and premium_at(c, cl, end) < c["entry_premium"] * 1.05:
            _close(lc, end, cl, "TIME_EXIT", f"no progress after {int(mins)} min")
            break
    if lc.open and lc.entered_at and len(bars):
        lc.mark_premium = round(premium_at(c, float(bars["close"].iloc[-1]), datetime.fromisoformat(lc.last_ts)), 2)


class Store:
    """Calls per underlying for the current trading day; best-effort JSON persistence."""

    def __init__(self, path: str | None = None):
        self.path = Path(path or os.environ.get("CHARTSCOPE_STATE", ".chartscope/calls.json"))
        self.calls: dict[str, list[LiveCall]] = {}
        try:
            raw = json.loads(self.path.read_text())
            self.calls = {k: [LiveCall(**x) for x in v] for k, v in raw.items()}
        except Exception:
            self.calls = {}

    def day_calls(self, und: str, day: str) -> list[LiveCall]:
        lst = self.calls.setdefault(und, [])
        keep = [x for x in lst if x.call["created_at"][:10] == day]
        if len(keep) != len(lst):
            self.calls[und] = keep
        return keep

    def add(self, und: str, lc: LiveCall) -> None:
        self.calls.setdefault(und, []).append(lc)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({k: [asdict(x) for x in v] for k, v in self.calls.items()}))
        except OSError:
            pass

"""Turn an underlying-level Idea into an option call priced in premium terms."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import bs, contracts
from .chain import Chain
from .intraday import DayContext, Idea

# Minutes of theta assumed to have elapsed when each level is reached (conservative: later = cheaper).
STOP_MIN, T1_MIN, T2_MIN = 25, 25, 50
MAX_STOP_LOSS_PCT = 0.45
MAX_COST_TO_RISK = 0.15  # skip calls whose round-trip costs would eat >15% of the planned loss
ENTRY_WAIT_MIN = {"market": 0, "limit": 10, "stop": 10}


@dataclass
class OptionCall:
    id: str
    underlying: str
    setup: str
    side: str  # LONG | SHORT
    option_type: str  # CE | PE
    strike: int
    expiry: str
    symbol: str
    lot_size: int
    mode: str
    u_entry: float
    u_stop: float
    u_targets: list[float]
    entry_premium: float
    stop_premium: float
    target_premiums: list[float]
    rr: list[float]
    lots: int
    qty: int
    cost: float
    max_loss: float
    confidence: int
    aligned: bool
    sigma: float
    delta: float
    premium_source: str
    created_at: str
    valid_until: str
    rationale: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    exit_plan: list[str] = field(default_factory=list)


def premium_at(call: OptionCall | dict, u: float, ts: datetime) -> float:
    d = call if isinstance(call, dict) else call.__dict__
    exp = datetime.fromisoformat(d["expiry"]).date()
    return bs.price(u, d["strike"], contracts.minutes_to_expiry(exp, ts), d["sigma"], d["option_type"])


def make_option_call(idea: Idea, ctx: DayContext, chain: Chain, capital: float, risk_pct: float, now: datetime, vix: float = 16.0) -> OptionCall | None:
    und = chain.underlying
    s = 1 if idea.side == "LONG" else -1
    kind = "CE" if s == 1 else "PE"
    K = contracts.atm(und, idea.entry)
    mins_now = contracts.minutes_to_expiry(chain.expiry, now)
    q = chain.quote(K, kind)
    sigma = None
    if q and chain.source == "nse" and q.ltp > 0:
        sigma = bs.implied_vol(q.ltp, chain.spot, K, mins_now, kind)
    if sigma is None:
        sigma = q.iv if q and q.iv else vix / 100
    lot = contracts.lot_size(und)

    def prem(u: float, after_min: int) -> float:
        return bs.price(u, K, max(mins_now - after_min, 1.0), sigma, kind)

    entry = prem(idea.entry, ENTRY_WAIT_MIN[idea.mode])
    stop = prem(idea.stop, ENTRY_WAIT_MIN[idea.mode] + STOP_MIN)
    t1 = prem(idea.targets[0], ENTRY_WAIT_MIN[idea.mode] + T1_MIN)
    t2 = prem(idea.targets[1], ENTRY_WAIT_MIN[idea.mode] + T2_MIN)
    risk = entry - stop
    warns: list[str] = []
    if risk <= 0 or t1 <= entry or t2 <= t1:
        return None
    if risk / entry > MAX_STOP_LOSS_PCT:
        return None  # stop too wide for the premium; skip rather than size a bad trade
    rr = [round((t1 - entry) / risk, 2), round((t2 - entry) / risk, 2)]
    if rr[0] < 1.0:
        return None

    risk_amt = capital * risk_pct / 100
    lots = math.floor(risk_amt / (risk * lot))
    lots = min(lots, math.floor(capital / (entry * lot)))
    if lots < 1:
        warns.append(f"Risk budget {risk_amt:.0f} is below one lot's risk ({risk * lot:.0f}); sizing shown for 1 lot.")
        lots = 1 if capital >= entry * lot else 0
    if lots == 0:
        return None
    from .monitor import trade_cost

    est_cost = trade_cost(entry * lot * lots, t1 * lot * lots, 3)
    if est_cost > MAX_COST_TO_RISK * risk * lot * lots:
        return None
    d = bs.delta(idea.entry, K, mins_now, sigma, kind)
    if (chain.expiry - now.date()).days == 0:
        warns.append("Expiry day: premiums are very sensitive to small moves and decay fast.")
    if chain.source == "model":
        warns.append("Premiums are model estimates from India VIX, not live quotes: check the actual option price before trading.")
    if idea.mode in ("stop", "limit"):
        warns.append("Conditional entry: do nothing unless the underlying trades through the entry level.")
    r2 = lambda x: round(float(x), 2)  # noqa: E731
    valid_until = now + timedelta(minutes=idea.valid_minutes)
    exp_label = contracts.label(und, chain.expiry, K, kind)
    return OptionCall(
        id=f"{und}-{now:%Y%m%d}-{idea.setup.lower().replace(' ', '-')}-{idea.side.lower()}",
        underlying=und, setup=idea.setup, side=idea.side, option_type=kind, strike=K, expiry=chain.expiry.isoformat(),
        symbol=exp_label, lot_size=lot, mode=idea.mode, u_entry=r2(idea.entry), u_stop=r2(idea.stop),
        u_targets=[r2(x) for x in idea.targets], entry_premium=r2(entry), stop_premium=r2(stop),
        target_premiums=[r2(t1), r2(t2)], rr=rr, lots=int(lots), qty=int(lots * lot), cost=r2(lots * lot * entry),
        max_loss=r2(lots * lot * risk), confidence=idea.confidence, aligned=idea.aligned, sigma=round(sigma, 4),
        delta=round(abs(d), 2), premium_source=chain.source, created_at=str(now), valid_until=str(valid_until),
        rationale=idea.rationale, warnings=warns,
        exit_plan=[
            f"Stop: exit if {und} trades {'below' if s == 1 else 'above'} {r2(idea.stop)} (option ≈ {r2(stop)}).",
            f"T1 {r2(idea.targets[0])} (option ≈ {r2(t1)}): book half, move stop to cost.",
            f"T2 {r2(idea.targets[1])} (option ≈ {r2(t2)}): exit the rest.",
            "Time stop: exit if no progress (< +5% on the premium) 60 minutes after entry.",
            "Hard square-off at 15:15 IST.",
        ],
    )

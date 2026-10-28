"""Turn patterns + S/R + analog statistics into concrete trade inputs."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .levels import Level
from .patterns import Pattern
from .similarity import AnalogStats

MIN_ANALOGS = 5
ACTION_THRESHOLD = 0.2


@dataclass
class TradePlan:
    action: str  # LONG | SHORT | WAIT
    score: float  # -1 (bearish) .. +1 (bullish)
    conviction: str  # low | medium | high
    entry: float | None = None
    entry_type: str = ""
    stop: float | None = None
    targets: list[float] = field(default_factory=list)
    risk_per_share: float | None = None
    rr: list[float] = field(default_factory=list)
    qty: int | None = None
    position_value: float | None = None
    risk_amount: float | None = None
    analog_target: float | None = None
    components: dict[str, float] = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    invalidation: str = ""


def _clip(x: float, lim: float = 1.0) -> float:
    return max(-lim, min(lim, x))


def score_components(
    patterns: list[Pattern], stats: AnalogStats, trend: float, price: float, levels: list[Level], atr_v: float
) -> dict[str, float]:
    ps = 0.0
    for p in patterns:
        sign = {"bullish": 1, "bearish": -1}.get(p.bias, 0)
        ps += sign * p.confidence / 100 * (1.0 if p.status == "confirmed" else 0.6)
    pattern = _clip(ps / 1.5)

    analog = 0.0
    if stats.n >= MIN_ANALOGS:
        analog = _clip((stats.win_rate_up - 0.5) * 2) * min(1.0, stats.n / 10) * (0.6 + 0.4 * stats.avg_similarity)

    level = 0.0
    for lv in levels:
        d = abs(price - lv.price)
        if d <= 0.6 * atr_v:
            level += (0.5 if lv.kind == "support" else -0.5) * lv.strength / 100 * 2
    return {"pattern": pattern, "analog": analog, "trend": _clip(trend), "level": _clip(level)}


def build_plan(
    price: float,
    atr_v: float,
    patterns: list[Pattern],
    levels: list[Level],
    stats: AnalogStats,
    trend: float,
    capital: float = 100_000.0,
    risk_pct: float = 1.0,
) -> TradePlan:
    comp = score_components(patterns, stats, trend, price, levels, atr_v)
    w = {"pattern": 0.35, "analog": 0.35, "trend": 0.20, "level": 0.10}
    if stats.n < MIN_ANALOGS:  # no usable history: don't let a zero drag the score
        w = {"pattern": 0.55, "analog": 0.0, "trend": 0.30, "level": 0.15}
    score = sum(w[k] * comp[k] for k in w)
    conviction = "high" if abs(score) >= 0.5 else "medium" if abs(score) >= 0.3 else "low"
    action = "LONG" if score >= ACTION_THRESHOLD else "SHORT" if score <= -ACTION_THRESHOLD else "WAIT"
    plan = TradePlan(action=action, score=round(score, 3), conviction=conviction, components={k: round(v, 3) for k, v in comp.items()})

    for p in patterns[:3]:
        plan.rationale.append(f"{p.name} ({p.bias}, {p.status}, {p.confidence}%): {p.description}")
    if stats.n >= MIN_ANALOGS:
        plan.rationale.append(
            f"{stats.n} similar historical setups (avg similarity {stats.avg_similarity:.0%}): price was higher "
            f"{stats.horizon} bars later {stats.win_rate_up:.0%} of the time, median move {stats.median_return_pct:+.2f}%."
        )
        if stats.n_same_pattern >= 3 and stats.win_rate_up_same_pattern is not None:
            plan.rationale.append(
                f"{stats.n_same_pattern} of them showed the same chart pattern; up {stats.win_rate_up_same_pattern:.0%} of the time."
            )
    else:
        plan.warnings.append(f"Only {stats.n} comparable historical setups found; analog evidence is ignored.")

    if action == "WAIT":
        plan.rationale.append("Evidence is mixed or weak; no edge worth taking. Wait for a trigger or a level test.")
        return plan

    s = 1 if action == "LONG" else -1  # direction multiplier
    bias = "bullish" if s == 1 else "bearish"
    own = "support" if s == 1 else "resistance"  # level we trade off
    opp = "resistance" if s == 1 else "support"  # levels we aim at
    own_lv = [lv for lv in levels if lv.kind == own]
    own_lv.sort(key=lambda lv: s * (price - lv.price))  # nearest first
    own_lv = [lv for lv in own_lv if s * (price - lv.price) >= 0]
    opp_lv = sorted((lv for lv in levels if lv.kind == opp and s * (lv.price - price) > 0), key=lambda lv: s * (lv.price - price))

    # ── entry ──
    trig = [p for p in patterns if p.bias == bias and p.status == "forming" and p.trigger is not None and 0 < s * (p.trigger - price) <= 1.5 * atr_v]
    near_own = own_lv[0] if own_lv else None
    if trig:
        entry, plan.entry_type = trig[0].trigger + s * 0.1 * atr_v, f"stop order: enter on break of {trig[0].name} trigger"
    elif near_own and s * (price - near_own.price) <= 1.0 * atr_v:
        entry, plan.entry_type = price, f"market/at price: within 1 ATR of {own} {near_own.price:.2f}"
    elif near_own:
        entry, plan.entry_type = near_own.price + s * 0.1 * atr_v, f"limit order: wait for pullback to {own} {near_own.price:.2f}"
        plan.warnings.append("Price is extended from the nearest level; a limit entry may never fill.")
    else:
        entry, plan.entry_type = price, "market/at price: no nearby structure"

    # ── stop ──
    cands = []
    if near_own:
        cands.append(near_own.low - 0.25 * atr_v if s == 1 else near_own.high + 0.25 * atr_v)
    cands += [p.invalidation for p in patterns if p.bias == bias and p.invalidation is not None]
    cands = [c for c in cands if 0.75 * atr_v <= s * (entry - c) <= 3.0 * atr_v]
    stop = max(cands, key=lambda c: s * c) if cands else entry - s * 1.5 * atr_v  # tightest structural stop
    if not cands:
        plan.warnings.append("No structural stop within 0.75-3 ATR; used 1.5 ATR.")
    risk = s * (entry - stop)

    # ── targets ──
    t1 = next((lv.price for lv in opp_lv if s * (lv.price - entry) >= 1.0 * risk), None)
    if t1 is None:
        t1 = entry + s * 1.5 * risk
        plan.warnings.append("No opposing S/R level at >=1R; T1 is a 1.5R projection.")
    beyond = [lv.price for lv in opp_lv if s * (lv.price - t1) > 0.3 * atr_v]
    pat_t = [p.target for p in patterns if p.bias == bias and p.target is not None and s * (p.target - t1) > 0.3 * atr_v]
    t2 = (beyond[0] if beyond else (pat_t[0] if pat_t else entry + s * 2.5 * risk))
    if beyond and pat_t and s * (pat_t[0] - t2) < 0 and s * (pat_t[0] - t1) > 0.3 * atr_v:
        t2 = pat_t[0]
    targets = [t1, t2]
    if stats.n >= MIN_ANALOGS:
        mfe = stats.median_mfe_atr if s == 1 else -stats.median_mae_atr
        plan.analog_target = entry + s * max(mfe, 0) * atr_v
        if s * (plan.analog_target - entry) < risk:
            plan.warnings.append("Median historical follow-through is smaller than your risk; poor payoff in analogs.")

    plan.entry, plan.stop, plan.targets = _r(entry), _r(stop), [_r(t) for t in targets]
    plan.risk_per_share = _r(risk)
    plan.rr = [round(float(s * (t - entry) / risk), 2) for t in targets]
    if plan.rr[0] < 1.2:
        plan.warnings.append(f"Reward:risk to T1 is only {plan.rr[0]:.2f}; consider skipping.")

    plan.risk_amount = round(capital * risk_pct / 100, 2)
    qty = math.floor(plan.risk_amount / plan.risk_per_share) if plan.risk_per_share > 0 else 0
    qty = min(qty, math.floor(capital / entry))  # no leverage assumed
    plan.qty, plan.position_value = int(qty), round(qty * entry, 2)
    if qty < 1:
        plan.warnings.append("Risk budget is below one unit's risk: raise capital / risk %, or use a smaller lot or instrument.")
    plan.invalidation = (
        f"Setup is void on a close {'below' if s == 1 else 'above'} {plan.stop} or if price reaches T1 before the entry triggers."
    )
    return plan


def _r(x: float) -> float:
    return round(float(x), 2)

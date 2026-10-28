import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from chartscope import data
from chartscope.analyze import analyze
from chartscope.indicators import atr
from chartscope.levels import build_levels, zigzag
from chartscope.patterns import detect_patterns
from chartscope.similarity import find_analogs
from chartscope.trade import build_plan
from chartscope.web.app import app


def frame(close, spread=0.4, start="2024-01-01"):
    close = np.asarray(close, float)
    open_ = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    idx = pd.date_range(start, periods=len(close), freq="B")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": np.full(len(close), 1e5)}, index=idx)


def legs(points, per_leg=12):
    out = [points[0]]
    for a, b in zip(points, points[1:]):
        out += list(np.linspace(a, b, per_leg + 1)[1:])
    return np.array(out)


def test_resolve_symbol():
    assert data.resolve_symbol("reliance") == "RELIANCE.NS"
    assert data.resolve_symbol("NIFTY") == "^NSEI"
    assert data.resolve_symbol("TCS.BO") == "TCS.BO"
    assert data.resolve_symbol("AAPL.NS") == "AAPL.NS"


def test_zigzag_alternates_and_finds_swings():
    df = frame(legs([100, 120, 105, 125, 100]))
    p = zigzag(df, mult=2.0)
    kinds = [x.kind for x in p]
    assert all(a != b for a, b in zip(kinds, kinds[1:]))
    assert not p[-1].confirmed and all(x.confirmed for x in p[:-1])
    assert any(abs(x.price - 125) < 1.5 for x in p)


def test_levels_cluster_repeated_turns():
    # price bounces between ~100 and ~120 three times
    df = frame(legs([110, 120, 100, 120, 100, 120, 100, 112]))
    lv = build_levels(df)
    res = [x for x in lv if x.kind == "resistance"]
    sup = [x for x in lv if x.kind == "support"]
    assert res and sup
    assert any(abs(x.price - 120) < 2 and x.touches >= 2 for x in res + sup)
    assert max(x.touches for x in lv) >= 3


def test_double_top_detected_and_confirmed():
    df = frame(legs([100, 130, 112, 130.5, 106]))
    pats = {p.name: p for p in detect_patterns(df, build_levels(df))}
    dt = pats["Double Top (M)"]
    assert dt.bias == "bearish" and dt.status == "confirmed"
    assert dt.target < dt.trigger < 130


def test_double_bottom_forming():
    df = frame(legs([130, 100, 118, 100.3, 112]))
    pats = {p.name: p for p in detect_patterns(df, build_levels(df))}
    db = pats["Double Bottom (W)"]
    assert db.bias == "bullish" and db.status in ("forming", "confirmed")
    assert db.trigger > 110


def test_head_and_shoulders():
    df = frame(legs([100, 120, 108, 135, 108, 121, 100]))
    names = [p.name for p in detect_patterns(df, build_levels(df))]
    assert "Head & Shoulders" in names


def test_bullish_engulfing_candle():
    close = list(legs([120, 100], per_leg=20)) + [101, 104]
    df = frame(close, spread=0.1)
    df.iloc[-2, df.columns.get_loc("open")] = 101.2
    df.iloc[-2, df.columns.get_loc("close")] = 100.0
    df.iloc[-1, df.columns.get_loc("open")] = 99.9
    df.iloc[-1, df.columns.get_loc("close")] = 102.0
    df.iloc[-1, df.columns.get_loc("high")] = 102.1
    names = [p.name for p in detect_patterns(df, [])]
    assert "Bullish Engulfing" in names


def test_analogs_find_planted_setups_and_outcomes():
    rng = np.random.default_rng(1)
    n, w, h = 1500, 40, 20
    steps = rng.normal(0, 0.15, n)
    shape = np.concatenate([np.linspace(0, 6, 25), np.linspace(6, 3, 15)])  # distinctive ramp-then-pullback
    planted = [200, 500, 800, 1100]
    close = 100 + np.cumsum(steps)
    for s in planted:  # rebuild so the setup happens and is followed by a strong rally
        base = close[s - 1]
        close[s : s + w] = base + shape
        close[s + w : s + w + h] = close[s + w - 1] + np.linspace(0, 8, h)
        close[s + w + h :] += close[s + w + h - 1] - close[s + w + h]
    # current window repeats the setup at the very end
    base = close[-w - 1]
    close[-w:] = base + shape
    df = frame(close)
    analogs, stats = find_analogs(df, window=w, horizon=h, top_k=6)
    found_ends = sorted(a.end_idx for a in analogs)
    for s in planted:
        assert any(abs(e - (s + w - 1)) <= 3 for e in found_ends), (s, found_ends)
    assert stats.win_rate_up >= 0.6 and stats.median_return_pct > 0
    # never matches the current window or leaks into it
    assert all(a.end_idx <= len(df) - 1 - w for a in analogs)


def test_analogs_empty_on_short_history():
    df = frame(np.linspace(100, 110, 100))
    a, s = find_analogs(df, window=40, horizon=20)
    assert a == [] and s.n == 0


def _plan_for(df, **kw):
    r = analyze("DEMO", "15m", df=df, **kw)
    return r["plan"], r


def test_plan_invariants_long_and_short():
    seen = set()
    for seed in range(40):
        df = data.synthetic(n=1500, seed=seed)
        plan, r = _plan_for(df, capital=200_000, risk_pct=0.5)
        seen.add(plan["action"])
        if plan["action"] == "WAIT":
            assert plan["entry"] is None
            continue
        s = 1 if plan["action"] == "LONG" else -1
        assert s * (plan["entry"] - plan["stop"]) > 0
        assert all(s * (t - plan["entry"]) > 0 for t in plan["targets"])
        assert s * (plan["targets"][1] - plan["targets"][0]) > 0
        assert plan["qty"] * plan["risk_per_share"] <= plan["risk_amount"] + 1e-6
        assert plan["position_value"] <= 200_000
        assert plan["rr"][0] > 0
    assert {"LONG", "SHORT"} <= seen  # both directions occur across market conditions


def test_wait_when_no_evidence():
    from chartscope.similarity import AnalogStats

    stats = AnalogStats(0, 40, 20, 0, 0, 0, 0, 0, 0, 0, None)
    plan = build_plan(100.0, 1.0, [], [], stats, 0.0)
    assert plan.action == "WAIT"


def test_analyze_payload_is_json_serialisable():
    import json

    r = analyze("DEMO", "1d")
    json.dumps(r)
    assert r["candles"] and r["current_path"] and "plan" in r


def test_api():
    c = TestClient(app)
    ok = c.get("/api/analyze", params={"symbol": "DEMO", "interval": "15m"})
    assert ok.status_code == 200 and ok.json()["plan"]["action"] in ("LONG", "SHORT", "WAIT")
    assert c.get("/api/analyze", params={"symbol": "DEMO", "interval": "7m"}).status_code == 400
    assert c.get("/api/analyze", params={"symbol": "a b"}).status_code == 422
    assert c.get("/api/analyze", params={"symbol": "DEMO", "risk_pct": 50}).status_code == 422
    assert c.get("/").status_code == 200
    assert c.get("/static/app.js").status_code == 200


def test_early_w_gives_staged_delivery_calls():
    # W whose second low is still in progress: price has come back down toward the first low
    close = legs([130, 100, 124, 101, 108], per_leg=15)
    df = frame(close, spread=0.5)
    r = analyze("DEMO", "1d", df=df)
    w = [p for p in r["patterns"] if p["name"].startswith("Double Bottom")]
    assert w and w[0]["status"] == "forming"
    calls = r["calls"]["delivery"]
    assert {c["style"] for c in calls} >= {"starter", "confirmation"}
    starter = next(c for c in calls if c["style"] == "starter")
    confirm = next(c for c in calls if c["style"] == "confirmation")
    assert starter["entry"] < confirm["entry"]  # early entry precedes the neckline add
    for c in calls:
        assert c["stop"] < c["entry"] < c["targets"][0] < c["targets"][1]
        assert c["qty"] * (c["entry"] - c["stop"]) <= c["risk_amount"] + 1e-6


def test_intraday_calls_respect_bias_and_risk():
    r = analyze("DEMO", "15m")
    for c in r["calls"]["intraday"]:
        s = 1 if c["side"] == "BUY" else -1
        assert s * (c["entry"] - c["stop"]) > 0 and all(s * (t - c["entry"]) > 0 for t in c["targets"])
        assert c["rr"][0] >= 1.0
        assert c["qty"] * abs(c["entry"] - c["stop"]) <= c["risk_amount"] + 1e-6
    assert len(r["calls"]["intraday"]) <= 4

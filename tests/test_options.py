from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from chartscope.options import bs, chain as chainmod, contracts, engine, market
from chartscope.options.intraday import Idea, build_context
from chartscope.options.monitor import Store, new_live_call, trade_cost, update
from chartscope.options import pricing
from chartscope.options.pricing import make_option_call


def test_black_scholes_basics():
    m = 6 * 1440
    c, p = bs.price(22700, 22700, m, 0.16, "CE"), bs.price(22700, 22700, m, 0.16, "PE")
    assert 150 < c < 250 and p < c  # positive carry: call > put at the money
    assert bs.price(23000, 22700, m, 0.16, "CE") > c > bs.price(22400, 22700, m, 0.16, "CE")
    assert 0.45 < bs.delta(22700, 22700, m, 0.16, "CE") < 0.6
    assert bs.implied_vol(c, 22700, 22700, m, "CE") == pytest.approx(0.16, abs=1e-3)
    assert bs.implied_vol(1.0, 22000, 22000 - 500, m, "CE") is None  # below intrinsic


def test_expiry_calendar():
    wed = datetime(2026, 10, 28, 10, 0)
    assert contracts.next_expiry("NIFTY", wed) == date(2026, 11, 3)  # Tuesday weekly
    assert contracts.next_expiry("NIFTY", datetime(2026, 11, 3, 10, 0)) == date(2026, 11, 3)
    assert contracts.next_expiry("NIFTY", datetime(2026, 11, 3, 16, 0)) == date(2026, 11, 10)
    assert contracts.next_expiry("BANKNIFTY", wed) == date(2026, 11, 24)  # monthly, last Tuesday
    assert contracts.next_expiry("SENSEX", wed) == date(2026, 10, 29)  # Thursday
    assert contracts.atm("NIFTY", 22724) == 22700 and contracts.atm("BANKNIFTY", 54267) == 54300


def test_parse_nse_payload():
    def row(k, ce, pe):
        return {"strikePrice": k, "expiryDate": "03-Nov-2026",
                "CE": {"lastPrice": ce, "impliedVolatility": 16.0, "openInterest": 1000 * (k // 50 % 7 + 1), "changeinOpenInterest": 5},
                "PE": {"lastPrice": pe, "impliedVolatility": 17.0, "openInterest": 900 * (k // 50 % 5 + 1), "changeinOpenInterest": -5}}

    payload = {"records": {"underlyingValue": 22700.0, "data": [row(22600, 250, 120), row(22650, 215, 140), row(22700, 180, 165), row(22750, 150, 195)]}}
    ch = chainmod.parse_nse(payload, "NIFTY")
    assert ch.source == "nse" and ch.spot == 22700.0 and ch.quote(22700, "CE").ltp == 180
    assert ch.quote(22700, "PE").iv == pytest.approx(0.17)
    assert ch.pcr and ch.max_pain in (22600, 22650, 22700, 22750) and ch.call_wall and ch.put_wall
    assert chainmod.parse_nse({"records": {"data": []}}, "NIFTY") is None


def test_costs_are_positive_and_scale():
    small, big = trade_cost(10_000, 11_000, 2), trade_cost(100_000, 110_000, 2)
    assert 0 < small < big < small * 10 + 1  # fixed brokerage doesn't scale


def _day_bars(day: str, closes, spread=4.0):
    idx = pd.date_range(f"{day} 09:15", periods=len(closes), freq="5min")
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + spread / 2, "low": np.minimum(o, c) - spread / 2, "close": c, "volume": 0.0}, index=idx)


def _breakout_data():
    rng = np.random.default_rng(3)
    base = 22000.0
    d1 = _day_bars("2026-10-26", base + rng.normal(0, 6, 75).cumsum() * 0.3)
    d2 = _day_bars("2026-10-27", d1["close"].iloc[-1] + rng.normal(0, 6, 75).cumsum() * 0.3)
    start = d2["close"].iloc[-1]
    opening = start + np.array([4, -6, 8, 2, 6], float)  # tight opening range
    grind_ok = True
    grind = opening[-1] + np.arange(1, 9) * 1.5 + rng.normal(0, 1.0, 8)  # drifts up to the range high first
    rally = grind[-1] + np.arange(1, 63) * 5.0 + rng.normal(0, 2, 62)  # then trends up through the day
    d3 = _day_bars("2026-10-28", np.concatenate([opening, grind, rally]))
    df5 = pd.concat([d1, d2, d3])
    daily = pd.DataFrame({"open": 21000 + np.arange(80) * 12.0, "high": 21010 + np.arange(80) * 12.0, "low": 20990 + np.arange(80) * 12.0,
                          "close": 21000 + np.arange(80) * 12.0, "volume": 0.0}, index=pd.date_range(end="2026-10-27", periods=80, freq="B"))
    return df5, daily


def test_live_loop_simulation(monkeypatch, tmp_path):
    # exercises the live state machine end to end, so enable every family and bypass the evidence gate
    from chartscope.options import intraday

    monkeypatch.setattr(intraday, "ENABLED", None)
    monkeypatch.setattr(engine.gate, "allowed", lambda hist, day: None)
    monkeypatch.setattr(engine, "_gate_hist", lambda u, df5: None)
    monkeypatch.setattr(pricing, "MAX_COST_TO_RISK", 1.0)
    monkeypatch.setattr(engine, "ENTRY_UNTIL", __import__("datetime").time(14, 45))
    df5, daily = _breakout_data()
    state = {"df": df5}
    monkeypatch.setattr(market, "index_bars", lambda u, iv: daily if iv == "1d" else state["df"])
    monkeypatch.setattr(market, "get_vix", lambda: 15.0)
    monkeypatch.setattr(chainmod, "fetch_nse", lambda u: None)
    store = Store(str(tmp_path / "calls.json"))
    day = df5[df5.index.date == date(2026, 10, 28)]
    seen_status = set()
    for k in range(6, len(day) - 1):
        state["df"] = df5[df5.index <= day.index[k]]
        now = day.index[k].to_pydatetime() + pd.Timedelta(minutes=5, seconds=5)
        r = engine.refresh("NIFTY", store, 300_000, 1.0, now=now)
        assert r["clock"]["market_open"]
        seen_status |= {c["status"] for c in r["calls"]}
    calls = store.day_calls("NIFTY", "2026-10-28")
    assert 1 <= len(calls) <= engine.MAX_CALLS_PER_DAY
    assert all(c.call["side"] == "LONG" for c in calls)  # trend day up: no bearish calls
    assert seen_status & {"ACTIVE", "T1", "TARGET", "SQUAREOFF", "T1_EXIT"}
    assert any(c.t1_hit for c in calls)
    for c in calls:
        assert c.call["stop_premium"] < c.call["entry_premium"] < c.call["target_premiums"][0] < c.call["target_premiums"][1]
        assert c.call["qty"] == c.call["lots"] * c.call["lot_size"]
        assert all(e["ts"] for e in c.events)
    assert len({c.call["id"] for c in calls}) == len(calls)  # one call per setup+side
    store2 = Store(str(tmp_path / "calls.json"))  # persisted and reloadable
    assert len(store2.day_calls("NIFTY", "2026-10-28")) == len(calls)


@pytest.fixture(autouse=True)
def _no_cost_gate_for_state_tests(request, monkeypatch):
    # state-machine tests use small fixed trades; the cost policy has its own test
    if request.node.name.startswith(("test_monitor", "test_expiry_of")):
        monkeypatch.setattr(pricing, "MAX_COST_TO_RISK", 1.0)


def test_cost_gate_rejects_tiny_risk():
    df5, daily = _breakout_data()
    ctx = build_context(df5, "neutral", 15.0)
    ch = chainmod.model_chain("NIFTY", 22000.0, 15.0, datetime(2026, 10, 28, 10, 0))
    now = datetime(2026, 10, 28, 10, 0)
    tiny = make_option_call(_idea(22000, 21992, 22020, 22040, "market"), ctx, ch, 300_000, 1.0, now, 15.0)
    wide = make_option_call(_idea(22000, 21940, 22090, 22160, "market"), ctx, ch, 300_000, 1.0, now, 15.0)
    assert tiny is None and wide is not None


def _idea(entry, stop, t1, t2, mode="stop", side="LONG"):
    return Idea("Test setup", side, mode, entry, stop, [t1, t2], 70, True, ["test"], 30)


def _live_call(side="LONG", mode="stop"):
    df5, daily = _breakout_data()
    ctx = build_context(df5, "bullish", 15.0)
    spot = 22000.0
    s = 1 if side == "LONG" else -1
    ch = chainmod.model_chain("NIFTY", spot, 15.0, datetime(2026, 10, 28, 10, 0))
    oc = make_option_call(_idea(spot + s * 10, spot - s * 40, spot + s * 70, spot + s * 130, mode, side), ctx, ch, 300_000, 1.0, datetime(2026, 10, 28, 10, 0), 15.0)
    assert oc is not None and oc.strike == contracts.atm("NIFTY", spot + s * 10)
    return new_live_call(oc, datetime(2026, 10, 28, 10, 0), spot)


def bars(rows, start="2026-10-28 10:00"):
    idx = pd.date_range(start, periods=len(rows), freq="5min")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx).assign(volume=0.0)


def test_monitor_long_to_target():
    lc = _live_call("LONG")
    assert lc.status == "WAITING"
    update(lc, bars([(22000, 22005, 21995, 22002), (22002, 22015, 22001, 22012), (22012, 22075, 22010, 22070), (22070, 22135, 22065, 22130)]))
    assert lc.status == "TARGET" and lc.t1_hit and lc.pnl > 0 and lc.r_multiple > 1


def test_monitor_stop_first_inside_a_bar_and_cancel():
    lc = _live_call("LONG")
    # bar tags the trigger and the stop: stop-first -> loss
    update(lc, bars([(22000, 22015, 21955, 21960)]))
    assert lc.status == "STOPPED" and lc.pnl < 0 and lc.r_multiple < 0
    lc2 = _live_call("LONG")
    update(lc2, bars([(22000, 22005, 21950, 21955)]))  # stop level hit before any entry
    assert lc2.status == "CANCELLED" and lc2.pnl is None


def test_monitor_short_and_breakeven_after_t1_and_squareoff():
    lc = _live_call("SHORT")
    update(lc, bars([(22000, 22002, 21985, 21990), (21990, 21995, 21925, 21930), (21930, 21995, 21925, 21992)]))
    assert lc.t1_hit  # T1 hit at 21930 then stop at cost (21990)
    assert lc.status in ("T1_EXIT", "STOPPED") and lc.pnl is not None
    lc3 = _live_call("LONG", mode="market")
    assert lc3.status == "ACTIVE"
    lc3.entered_at = "2026-10-28 15:00:00"  # entered shortly before the close so the time-stop does not fire first
    update(lc3, bars([(22000, 22010, 21990, 22005)] * 3, start="2026-10-28 15:05"))
    assert lc3.status == "SQUAREOFF"


def test_expiry_of_unfilled_call():
    lc = _live_call("LONG")
    update(lc, bars([(22000, 22003, 21990, 21998)] * 8))  # 40 minutes of nothing, valid for 30
    assert lc.status == "EXPIRED"


def test_replay_runs_and_summarises(monkeypatch):
    df5, daily = _breakout_data()
    monkeypatch.setattr(market, "index_bars", lambda u, iv: daily if iv == "1d" else df5)
    monkeypatch.setattr(engine, "_vix_by_date", lambda: {})
    r = engine.backtest("NIFTY", days=1, use_gate=False)
    assert r["days"] == 1 and "summary" in r and "caveat" in r
    assert all("cost" in t for t in r["trades"])


def test_options_api(monkeypatch):
    monkeypatch.setattr(engine, "_gate_hist", lambda u, df5: None)
    from fastapi.testclient import TestClient

    from chartscope.web.app import app

    df5, daily = _breakout_data()
    monkeypatch.setattr(market, "index_bars", lambda u, iv: daily if iv == "1d" else df5)
    monkeypatch.setattr(market, "get_vix", lambda: 15.0)
    monkeypatch.setattr(chainmod, "fetch_nse", lambda u: None)
    c = TestClient(app)
    r = c.get("/api/options/live", params={"underlying": "NIFTY"})
    assert r.status_code == 200 and {"context", "calls", "preview", "events", "candles"} <= set(r.json())
    assert c.get("/api/options/live", params={"underlying": "FOO"}).status_code == 400
    assert c.get("/options").status_code == 200


def test_gate_uses_only_prior_sessions():
    from chartscope.options import gate

    rows = []
    for d, r in ((date(2026, 10, 1), 1.0), (date(2026, 10, 2), 1.0), (date(2026, 10, 3), -5.0)):
        rows += [{"date": d, "family": "sweep", "side": "SHORT", "r": r}] * 20
    hist = pd.DataFrame(rows)
    on_3rd = gate.allowed(hist, date(2026, 10, 3))  # sees Oct 1-2 only: 40 samples at +1R
    assert on_3rd[("sweep", "SHORT")]["ok"] and on_3rd[("sweep", "SHORT")]["n"] == 40
    on_4th = gate.allowed(hist, date(2026, 10, 4))  # now includes the -5R day
    assert not on_4th[("sweep", "SHORT")]["ok"]
    assert gate.allowed(pd.DataFrame(), date(2026, 10, 4)) == {}


def test_only_reversal_families_enabled_by_default():
    from chartscope.options import intraday

    assert intraday.ENABLED == intraday.REVERSAL
    assert not ({"orb", "ib", "vwap_pullback", "pattern_trigger", "pattern_retest", "flag"} & intraday.ENABLED)


def test_premarket_plan_fades_previous_day_extremes():
    df5, daily = _breakout_data()
    from chartscope.options.intraday import premarket_ideas

    ctx = build_context(df5, "neutral", 15.0)
    ideas = {i.side: i for i in premarket_ideas(ctx)}
    assert ideas["SHORT"].entry < ctx.prev_high < ideas["SHORT"].stop
    assert ideas["LONG"].stop < ctx.prev_low < ideas["LONG"].entry

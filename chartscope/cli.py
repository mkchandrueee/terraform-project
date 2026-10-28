"""Command line: `python -m chartscope RELIANCE -i 15m` or `python -m chartscope serve`."""

from __future__ import annotations

import argparse
import json
import sys

from . import data
from .analyze import analyze


def _print_report(r: dict) -> None:
    p, s = r["plan"], r["analog_stats"]
    print(f"\n{r['resolved']}  {r['interval']}  as of {r['asof']}   price {r['price']}  ATR {r['atr']}  RSI {r['rsi']}  trend {r['trend']}")
    print("\nSupport / resistance")
    for lv in sorted(r["levels"], key=lambda x: -x["price"]):
        tag = "R" if lv["kind"] == "resistance" else "S"
        print(f"  {tag} {lv['price']:>10.2f}  strength {lv['strength']:>3}  touches {lv['touches']}  {', '.join(lv['sources'])}")
    print("\nPatterns")
    for x in r["patterns"] or [{"name": "none detected", "bias": "", "status": "", "confidence": 0, "description": ""}]:
        print(f"  {x['name']:<26} {x['bias']:<8} {x['status']:<9} {x['confidence']:>3}%  {x['description']}")
    print(f"\nHistorical analogs ({s['n']} found, window {s['window']} bars, horizon {s['horizon']} bars)")
    for a in r["analogs"][:8]:
        flag = "*" if a["same_pattern"] else " "
        print(f"  {flag} {a['start'][:16]} -> {a['end'][:16]}  sim {a['similarity']:.0%}  next {s['horizon']} bars {a['fwd_return_pct']:+.2f}%  {', '.join(a['patterns'])}")
    if s["n"]:
        print(f"  up {s['win_rate_up']:.0%} | median {s['median_return_pct']:+.2f}% | same-pattern n={s['n_same_pattern']}  (* = same pattern as now)")
    print(f"\nTRADE INPUTS: {p['action']}  score {p['score']:+.2f}  conviction {p['conviction']}")
    if p["action"] != "WAIT":
        print(f"  entry  {p['entry']}  ({p['entry_type']})")
        print(f"  stop   {p['stop']}   risk/share {p['risk_per_share']}")
        print(f"  T1/T2  {p['targets'][0]} / {p['targets'][1]}   R:R {p['rr'][0]} / {p['rr'][1]}")
        print(f"  size   {p['qty']} units (~{p['position_value']}) risking {p['risk_amount']}")
        print(f"  {p['invalidation']}")
    for line in p["rationale"]:
        print(f"  - {line}")
    for w in p["warnings"]:
        print(f"  ! {w}")
    print("\nEducational analysis only, not investment advice.")


def _options_cli(argv: list[str]) -> int:
    import time

    from .options import engine, market
    from .options.monitor import Store

    ap = argparse.ArgumentParser(prog="chartscope options")
    ap.add_argument("underlying", choices=["NIFTY", "BANKNIFTY", "SENSEX"])
    ap.add_argument("--capital", type=float, default=300_000)
    ap.add_argument("--risk-pct", type=float, default=1.0)
    ap.add_argument("--watch", type=int, metavar="SECONDS", help="keep polling and print new alerts")
    ap.add_argument("--backtest", type=int, metavar="DAYS", help="replay the last N sessions instead")
    a = ap.parse_args(argv)
    if a.backtest:
        r = engine.backtest(a.underlying, a.backtest, a.capital, a.risk_pct)
        s = r["summary"]
        print(f"{a.underlying} replay {r['from']} → {r['to']}: {s.get('n', 0)} trades")
        if s.get("n"):
            print(f"  win {s['win_rate']:.0%}  avg {s['avg_r']:+.2f}R  PF {s['profit_factor']}  net ₹{s['total_pnl']:,.0f} (gross ₹{s['gross_pnl']:,.0f} - costs ₹{s['costs']:,.0f})  maxDD ₹{s['max_drawdown']:,.0f}")
            for k, v in sorted(r["by_setup"].items(), key=lambda kv: -kv[1]["n"]):
                print(f"  {k:32} n={v['n']:3}  win {v['win_rate']:.0%}  avg {v['avg_r']:+.2f}R")
        print("  " + r["caveat"])
        return 0
    store, seen = Store(), set()
    engine._gate_hist(a.underlying, market.index_bars(a.underlying, "5m"), compute=True)  # build evidence first (~90s once a day)
    while True:
        r = engine.refresh(a.underlying, store, a.capital, a.risk_pct)
        c = r["context"]
        print(f"\n[{r['clock']['now'][11:19]}] {a.underlying} {c['spot']}  {'LIVE' if r['clock']['market_open'] else 'CLOSED'}  VWAP {c['vwap']}  OR {c['or_low']}-{c['or_high']}  trend {c['trend']}/{c['daily_bias']}  src={r['chain_source']}")
        for x in (r["calls"] if r["clock"]["market_open"] else r["preview"]):
            k = x["call"]
            print(f"  {x['status']:<8} BUY {k['symbol']}  at ₹{k['entry_premium']}  SL ₹{k['stop_premium']}  T ₹{k['target_premiums'][0]} / ₹{k['target_premiums'][1]}  lots {k['lots']}  ({k['setup']}, {k['confidence']}%)")
        for e in r["events"]:
            key = e["ts"] + e["msg"] + e["id"]
            if key not in seen:
                seen.add(key)
                print(f"  >> {e['ts'][11:16]} {e['msg']}")
        if not a.watch:
            return 0
        time.sleep(a.watch)


def main(argv: list[str] | None = None) -> int:
    import sys as _s

    args = list(_s.argv[1:] if argv is None else argv)
    if args and args[0] == "options":
        return _options_cli(args[1:])
    ap = argparse.ArgumentParser(prog="chartscope")
    ap.add_argument("symbol", help="NSE ticker (RELIANCE), index (NIFTY, BANKNIFTY), Yahoo symbol, DEMO, or 'serve'")
    ap.add_argument("-i", "--interval", default="15m", choices=data.INTERVALS)
    ap.add_argument("--capital", type=float, default=100_000)
    ap.add_argument("--risk-pct", type=float, default=1.0)
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    if a.symbol == "serve":
        import uvicorn

        uvicorn.run("chartscope.web.app:app", host=a.host, port=a.port)
        return 0
    try:
        r = analyze(a.symbol, a.interval, a.capital, a.risk_pct)
    except LookupError as e:
        print(e, file=sys.stderr)
        return 1
    if a.json:
        r.pop("candles")
        print(json.dumps(r, indent=2))
    else:
        _print_report(r)
    return 0

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


def main(argv: list[str] | None = None) -> int:
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

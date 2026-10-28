#Terraform Multicloud project
In this project we use terraform to automate aws and azure colud resources.


---

# ChartScope

Live chart-pattern, support/resistance and historical-analog analysis for NSE/BSE stocks and indices
(any Yahoo Finance symbol works), with concrete **intraday** and **delivery** trade calls.
Inspired by [india-trade-cli](https://github.com/hopit-ai/india-trade-cli) but focused on the chart itself:
no LLM or broker needed.

## What it does

| Need | How |
|---|---|
| Live chart patterns | ATR zig-zag swings → double top/bottom (M/W), head & shoulders (+inverse), triangles, wedges, channels, ranges, S/R breakouts + retests, engulfing/hammer/shooting star/doji. Patterns are flagged **while still forming** (e.g. W with the second low in progress), with stage, trigger, measured target, invalidation and an RSI-divergence bonus. |
| Support & resistance | Swing prices clustered into zones scored by touches and recency; prior-session high/low/close on intraday charts. |
| Compare with history | Z-normalised shape correlation of the latest window vs every past window (non-overlapping, volatility-matched). Shows the closest matches, what happened over the next N bars, win rate, ATR-scaled follow-through, and how many matches showed the *same pattern*. |
| Trade inputs | Overall signal (patterns + analogs + trend + levels), plus multiple calls: **delivery** (starter at half size + neckline-confirmation add) and up to 4 **intraday** calls (pattern trigger, pullback, breakout, fade, breakdown). Each has entry, stop, T1/T2, R:R and risk-based quantity; counter-trend calls are half size. |

## Run

```bash
pip install -e '.[dev]'
python -m chartscope serve            # dashboard at http://127.0.0.1:8000 (auto-refreshes every 30s)
python -m chartscope NIFTY -i 1d      # text report
python -m chartscope RELIANCE -i 15m --capital 500000 --risk-pct 0.5
python -m chartscope DEMO             # offline synthetic data
pytest
```

Symbols: `RELIANCE` → `RELIANCE.NS`, `NIFTY`/`BANKNIFTY`/`SENSEX` map to the indices; `TCS.BO` or any Yahoo symbol passes through.
Timeframes: 5m, 15m, 30m, 1h, 1d, 1wk. History depth is whatever Yahoo provides (about 60 days for ≤30m, 2 years for 1h, 10 years daily),
so intraday analogs are drawn from recent weeks; daily analogs from years.

## Limits

- Data is public and may be delayed; there is no broker integration or order placement.
- Pattern detection and analog matching are heuristics. A "similar" past setup is evidence, not a forecast; sample sizes are small (shown in the UI).
- Index calls use notional units; trade them via futures/options or an ETF. Delivery calls are long-only (cash equity can't be shorted for delivery).
- Educational use only, not investment advice.

---

## Options intraday calls (NIFTY / BANKNIFTY / SENSEX)

```bash
python -m chartscope serve                          # then open http://127.0.0.1:8000/options
python -m chartscope options NIFTY --watch 15       # terminal monitor: prints new alerts every 15s
python -m chartscope options NIFTY --backtest 45    # replay the last 45 sessions with the same rules
```

**What you get:** option-buying calls (CE for bullish setups, PE for bearish; risk is limited to the premium) with the
strike, **buy premium, stop-loss premium, two target premiums**, lots sized to your risk %, and an exit plan. Setups: opening-range
breakout, VWAP trend pullback, support bounce / resistance rejection, 5m chart-pattern triggers and retests; counter-trend
calls against a strong daily/5m bias are suppressed. Rules: entries 09:30-14:45 IST, max 3 calls a day, no stacking the same
direction, stop for the day at -2R, 60-minute time stop, square-off 15:15.

**Live monitoring:** every poll (15s in the UI) walks each call through `WAITING → ACTIVE → T1 (half booked, stop to cost) →
TARGET / STOPPED / TIME_EXIT / SQUAREOFF` against 1-minute bars, with an alert log and optional browser notifications.
Inside one bar the stop is assumed to hit before the target. When the market is closed you get a pre-market plan (previous-day
high/low breaks priced at the next session) and a replay of what the rules did last session.

**Where the premiums come from:** the NSE public option chain is tried first (cookie-based, often blocked on cloud/VPN networks and
untested against the live site from the build sandbox); otherwise premiums are **Black-Scholes estimates from India VIX**, labelled
"Model (VIX)". Always check the real quote before placing an order. Lot sizes and expiry weekdays are defaults in
`chartscope/options/contracts.py` (override lots with `CHARTSCOPE_LOT_NIFTY=...`); verify them against the current exchange circular.

**Does it make money? Not demonstrated.** Replay of 45 sessions (Aug 24 - Oct 28 2026, 5m data, costs of ~₹140-270 per trade
included, 1% risk on ₹3L): NIFTY 72 trades, avg -0.13R, net ₹-16k; BANKNIFTY 69 trades, avg -0.03R, net ₹-4k; SENSEX 61 trades,
avg 0.00R, net +₹2k. Gross is slightly positive, costs consume it, the sample is small and from one falling market, and the
confidence score did not reliably separate winners from losers. Treat the calls as decision support to be paper-traded first,
not as a validated edge. The replay is in the app so you can check any change you make to the rules the same way.

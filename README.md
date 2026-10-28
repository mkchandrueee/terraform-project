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

**What you get:** option-buying calls (CE for bullish, PE for bearish; risk is limited to the premium) with the strike,
**buy premium, stop-loss premium, two target premiums**, lots sized to your risk %, and an exit plan.

**How the setups were chosen (signal study).** `chartscope/options/study.py` replays every raw idea on 13 NSE instruments
(3 indices + 10 large caps, ~26k ideas, Aug-Oct 2026) with the live trade-management rules and scores it in R, split into a
development half and a later holdout half. Ideas taken from the referenced projects were added and tested the same way: liquidity
sweeps, RSI divergence, value-area (market-profile) rejection/acceptance, flags with an R²-quality trendline fit, initial-balance breakouts.

- Reversal setups (RSI divergence, liquidity sweep, value-area rejection, support bounce / resistance rejection) beat other ideas on the
  same instrument and day by ~+0.08R in **both** halves (t ≈ 6-8); breakout/continuation setups (ORB, IB breakout, VWAP pullback,
  pattern triggers/retests, flags) lagged by ~-0.08R. Only reversal setups are enabled, ranked by their measured excess.
- Over 10 years of daily data, the daily trend did **not** predict the next session's intraday direction (NIFTY -0.035%/day in the trend
  direction, 48% hit rate), so trend alignment is shown but no longer filters or boosts calls.
- Walk-forward evidence gate: a setup/side is called only if it averaged > +0.05R over the previous 20 sessions on that index (≥ 30 signals).
  Uses only past data, so replay and live behave the same. The app shows the table.
- Entries 09:30-12:00 (afternoon signals were weaker in both halves); calls are skipped when estimated costs exceed 15% of the planned loss.

**Honest result.** In absolute terms, after costs, no setup family showed a positive drift-neutral edge: the best gross edges were
~0 to +0.07R, while buying ATM options costs ~0.10-0.18R per trade. Replay of the shipped rules on the last 40 sessions
(Aug 31-Oct 28, all three indices, 1% risk on ₹3L): 76 trades, -0.02R per trade, net -₹4.8k (gross +₹9.9k, costs ₹14.7k), versus
-₹18.1k over 202 trades for the first version. Nearly all trades were PE (shorts) because the gate followed a falling market; expect the
mix to change when the market does. This is decision support to paper-trade, not a validated edge. More history (5-minute data from
Yahoo only covers ~60 days) or richer data (live option-chain OI/IV, futures volume) is needed to go further.

**Live monitoring:** every poll (15s in the UI) walks each call through `WAITING → ACTIVE → T1 (half booked, stop to cost) →
TARGET / STOPPED / TIME_EXIT / SQUAREOFF` against 1-minute bars, with an alert log and optional browser notifications.
Inside one bar the stop is assumed to hit before the target. Max 3 calls a day, stop for the day at -2R, 60-minute time stop,
square-off 15:15. When the market is closed you get a pre-market plan (fade the previous day's high/low on rejection) and a
replay of the last session. The first request for an index builds its 20-session evidence (~90s), then it is cached per day.

**Where the premiums come from:** the NSE public option chain is tried first (cookie-based, often blocked on cloud/VPN networks and
untested against the live site from the build sandbox); otherwise premiums are **Black-Scholes estimates from India VIX**, labelled
"Model (VIX)". Always check the real quote before placing an order. Lot sizes and expiry weekdays are defaults in
`chartscope/options/contracts.py` (override lots with `CHARTSCOPE_LOT_NIFTY=...`); verify them against the current exchange circular.

Re-run the study yourself:

```python
from chartscope.options import study
df = study.collect("^NSEI", days=60)         # raw ideas + outcomes in R
print(study.summarize(df, ["family", "side"]))
```

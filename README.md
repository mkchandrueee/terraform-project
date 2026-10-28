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

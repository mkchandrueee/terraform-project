# NIFTY Option Strategy Suite

A single static web app that implements the three tools called for by the *NIFTY Option Trading Strategy
Execution Guide* — the Option Analyser, the T1 Decision Helper and the Stoploss Pullback Entry tool — as one
guided workflow instead of three disconnected pages.

No build step, no dependencies, no backend. Everything runs in the browser and nothing leaves it.

## The workflow

| Phase | Tool | In | Out |
|---|---|---|---|
| 1–2 (steps 1–5) | **Option Analyser** | NIFTY open price, then the 09:15–09:20 OHLC of the ATM call and put | ATM strike, and entry price / Target 1 / stop loss for each side, plus the confirmation close |
| 3 (steps 6–10) | **T1 Decision Helper** | Triggered side, the three mapped levels, and the OHLC of the candle that confirmed entry | Hold T2 vs partial book vs book now, a probability score, five condition checks and the condition-4 gate |
| 4 (steps 11–13) | **Stoploss Pullback Entry** | The original first-candle OHLC of both sides | Call buy or put buy, zone 1 (entry), zone 2, Target 1 — deliberately no stop loss |

The tools hand off to each other. *Send to T1 Helper* on an analyser result applies the guide's mapping
automatically — entry field ← stop loss, T1 field ← entry price, T2 field ← Target 1 — and *Copy from analyser*
in the pullback tool reuses the same first-candle data.

## About the formulas

The strategy guide specifies **which** values each tool produces, not the arithmetic behind them, and the
original tools were not available to inspect. The model below is therefore this implementation's own, chosen to
be the most natural reading of the guide's structure; every coefficient is exposed under **Formula settings**
so it can be re-tuned to match your own numbers. Settings persist in the browser and re-run any open result
immediately.

**Option Analyser** — the first candle's high is the breakout level and its low is the invalidation level, so
risk equals the candle range and Target 1 is a measured move of that same range:

```
range     = high − low
entry     = high            (+ optional buffer, default 0)
stop loss = low             (− optional buffer, default 0)
Target 1  = entry + 1.0 × range
confirm   = a 5-minute close ≥ entry + one tick (0.05)
```

`strength = 50% × close position + 30% × body ÷ range + 20% × (close > open)` flags which side to watch first.
It never substitutes for the confirmation close.

**T1 Decision Helper** — five weighted checks produce a 0–100 probability score:

| # | Check | Weight |
|---|---|---|
| 1 | Close above the T1 level (the entry actually triggered) | 25 |
| 2 | Bullish candle with body ÷ range ≥ 0.35 | 20 |
| 3 | Close position ≥ 0.60 of the candle range | 20 |
| 4 | **Candle range ÷ distance left to T2 ≥ 1.0** — decisive | 25 |
| 5 | Candle low held at or above the entry level | 10 |

Verdict: **HOLD T2** at a score ≥ 70 *with check 4 passed*; **PARTIAL BOOK** at ≥ 45; **BOOK NOW** below that.
A failed check 1 short-circuits to *avoid* — nothing confirmed, so there is no trade. Check 4 asks whether one
more candle of the same size would cover the distance still left to T2, and it is rendered as the standalone
pre-trade gate the guide requires: passed → proceed, not passed → skip regardless of the verdict.

**Stoploss Pullback Entry** — the side with the stronger first-candle liquidity structure is the tradable one,
and entries sit *inside* the range rather than above it, which is why the setup carries no stop loss:

```
liquidity score = 45% × close position + 30% × body ÷ range
                + 15% × (close > open) + 10% × share of combined range
side     = whichever of CE / PE scores higher
zone 1   = low + 0.382 × range
zone 2   = low + 0.236 × range
Target 1 = high + 1.0 × range
```

One deviation worth naming: the guide says to round the NIFTY open "to the nearest 100" but its own example
maps 23670 → 23600, so the app rounds **down** to the 100 strike to match the example.

## Running it

Any static server works, since the page is plain HTML/CSS/JS:

```sh
cd option-strategy-suite
python3 -m http.server 8787
# http://127.0.0.1:8787
```

Opening `index.html` straight from disk also works — scripts are classic, not modules.

### Deploying

`netlify.toml` in the repository root publishes this directory as-is, with a strict `Content-Security-Policy`
(the page loads no external resources at all). Point Netlify at the repository and no further configuration is
needed.

## Layout

```
option-strategy-suite/
├── index.html                 markup for all four tabs
└── assets/
    ├── css/styles.css
    └── js/
        ├── utils.js           parsing, formatting, candle validation and stats
        ├── config.js          tunable coefficients + localStorage persistence
        ├── analyser.js        tool 1
        ├── t1helper.js        tool 2
        ├── pullback.js        tool 3
        └── app.js             tabs, settings drawer, formula reference
```

Each tool exposes its pure calculation separately from its rendering — `APP.analyser.analyse()`,
`APP.t1helper.decide()`, `APP.pullback.analyse()` — so the model can be tested or reused without the DOM.

## Disclaimer

Educational tool only. Nothing here is investment advice or a recommendation to trade. Options carry
substantial risk of loss; every level is derived arithmetically from the values you type and carries no
predictive guarantee. Verify each number against your broker terminal before acting on it.

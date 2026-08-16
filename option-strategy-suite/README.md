# NIFTY Option Strategy Suite

A single static web app that implements the tools called for by the *NIFTY Option Trading Strategy Execution
Guide* — the Option Analyser, the T1 Decision Helper and the Stoploss Pullback Entry tool — as one guided
workflow instead of three disconnected pages, plus a Trade Signal stage that puts the standard market filters,
the expectancy maths and trade alerts on top of them.

No build step, no dependencies, no backend. Everything runs in the browser and nothing leaves it. The whole
interface switches between English and Tanglish (Tamil + English) from the header button, and the choice is
remembered.

## The workflow

| Phase | Tool | In | Out |
|---|---|---|---|
| 1–2 (steps 1–5) | **Option Analyser** | NIFTY open price, then the 09:15–09:20 OHLC of the ATM call and put | ATM strike, and entry price / Target 1 / stop loss for each side, plus the confirmation close |
| 3 (steps 6–10) | **T1 Decision Helper** | Trade side, the three mapped levels, and the OHLC of the candle that touched T1 | Hold → T2 vs partial book vs book now, a momentum score, the T1→T2 reward ratio, four condition checks, the condition-4 gate and an action plan |
| 4 (steps 11–13) | **Stoploss Pullback Entry** | The original first-candle OHLC of both sides | Call buy or put buy, zone 1 (entry), zone 2, Target 1 — deliberately no stop loss |
| 5 (steps 14–16) | **Trade Signal** | The levels, standard indicator readings off the NIFTY chart, lots and account size | Take / caution / skip, win estimate, expected profit, expected value, breakeven win rate, sizing, and browser notifications |

The tools hand off to each other. *Send to T1 Helper* on an analyser result applies the guide's mapping
automatically — entry field ← stop loss, T1 field ← entry price, T2 field ← Target 1 — and *Copy from analyser*
in the pullback tool reuses the same first-candle data.

## About the formulas

The strategy guide specifies **which** values each tool produces, not the arithmetic behind them. Where
screenshots of the original tools pinned a number down, this implementation matches it; everything else is the
most natural reading of the guide's structure. Every coefficient is exposed under **Formula settings** so it
can be re-tuned to match your own numbers — settings persist in the browser and re-run any open result
immediately.

Two things the reference examples confirm rather than assume: the analyser's ladders come out equally spaced
(their published examples are 102/152/202, 27/61/96 and 175/219/263 — gaps of 50/50, 34/35 and 44/44), which is
exactly what `stop loss = low`, `entry = high`, `Target 1 = high + range` produces; and the T1 helper's
momentum weights below reproduce its published scores exactly.

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

**T1 Decision Helper** — three weighted checks on the T1-touch candle produce a 0–100 momentum score, and a
fourth check sits outside the score as the gate:

| # | Check | Weight | Passes when |
|---|---|---|---|
| 1 | Direction | 40 | The candle closed up — the premium gained |
| 2 | Body strength | 15 strong / 7.5 moderate | Body ÷ range ≥ 0.65 scores full, 0.45–0.65 scores half, below that nothing |
| 3 | Close position | 40 | Close in the top half of the candle range |
| 4 | **T1 breakout strength** | *gate* | Close above the T1 level — the breakout actually happened |

`momentum = floor(sum of the weights earned)`. Those weights are not invented: they are the combination that
reproduces the reference tool's own published scores exactly — 0%, 15% and 87% across the three worked examples
in its screenshots, including the three-way PASS / WEAK / FAIL grading on body strength.

Verdict: **WAIT** if check 4 failed (nothing is confirmed, so there is nothing to hold or book); otherwise
**HOLD → T2** at momentum ≥ 70, **PARTIAL BOOK** at ≥ 40, **BOOK NOW** below that. Check 4 is also rendered as
the standalone pre-trade gate the guide requires at step 10: passed → proceed, not passed → skip, whatever the
verdict says. Alongside the score the tool shows `T1→T2 reward ratio = (T2 − T1) ÷ (T1 − entry)`, which is
1.00× for any ladder produced by the analyser above, and a five-step action plan that changes with the verdict.

### One deliberate difference on the put side

The original helper treats a *bullish* candle as wrong for a put trade, and wants the close in the lower half
of the range. That holds if the candle is the index, but this workflow feeds it the **option's own premium
candle** — and you are long the option on either leg, so a rising premium is a gain whether you hold a call or
a put. The guide's own confirmation rule makes this concrete: the candle must *close above* the entry price, so
a valid confirmation candle is nearly always green. Under the inverted reading, that same valid candle fails
both the direction and close-position checks and every put trade lands on *book now*.

So the default here is the premium reading — up is good on both sides. **Formula settings → Direction
convention → Side-inverted** restores the original behaviour exactly if you want parity; with it enabled the
app reproduces the reference tool's output number for number (entry 175 / T1 219 / T2 263, candle
217/221/210/220 → put: 0% momentum, book now; entry 127 / T1 158 / T2 189, candle 144/169/144/167 → put: 15%,
book now; entry 152 / T1 175 / T2 198, candle 172/181/165/180 → call: 87%, hold to T2).

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

**Trade Signal** — nine market-standard filters produce a confluence score, which becomes a win estimate,
which combines with the money side into an actual expectancy:

| Filter | Weight | Passes when |
|---|---|---|
| Price vs VWAP | 20 | Spot on the trade's side of VWAP |
| Moving-average alignment | 15 | Spot the right side of EMA 20, with EMA 20/50 stacked to match |
| RSI regime | 15 | RSI 55–78 for a call, mirrored to 22–45 for a put — momentum without exhaustion |
| Volume confirmation | 10 | Breakout volume ≥ 1.2× the average |
| Volatility regime | 10 | India VIX ≤ 25 |
| Target reachable | 15 | T2 within 2× the reference range |
| Risk : reward | 15 | At least 1 : 1.5 to T2 |
| Time of day | 10 | Inside 09:20–11:30 or 13:00–14:45 |
| T1 Helper momentum | 20 | The helper's momentum cleared its hold threshold |

```
confluence     = passed weights ÷ available weights × 100
win estimate   = clamp(base win rate + (confluence − 50) × 0.6, 15, 85)
breakeven win  = risk ÷ (risk + reward)
expected value = win × profit at T2 − (1 − win) × max loss

TAKE TRADE  when EV > 0, win estimate > breakeven, and confluence ≥ 65
CAUTION     when EV > 0 and win > breakeven but confluence falls short
SKIP        otherwise
```

A filter you leave blank is **skipped** — dropped from both sides of the ratio, so a partial reading scores
fairly instead of being punished for missing data. Alongside the verdict the tool reports quantity, capital
deployed, maximum loss, profit at T1 and T2, brokerage, expected value per rupee risked, risk as a percentage
of the account, the lot count your risk budget allows, and a quarter-Kelly size.

### What the win percentage is, and is not

The app has no market data feed and no trade history, so it cannot measure a real win rate. The win estimate is
**your own base win rate** — from your journal, set under Formula settings — moved up or down by how much
confluence lined up, floored at 15% and capped at 85%. It is a planning figure, not a backtested probability,
and the UI says so where it is displayed.

The **breakeven win rate** shown beside it is not a judgement call at all: `risk ÷ (risk + reward)` is exact
arithmetic, and it is the number that decides whether a setup can pay. The verdict leans on that comparison —
a trade is only *take* when the estimate clears breakeven **and** expected value is positive — so an
optimistic base rate cannot on its own turn a losing structure into a green badge.

## Notifications

The signal can fire a browser notification carrying the verdict, entry, stop, target, win estimate, expected
profit, expected value and risk-reward. A separate reminder fires on every 5-minute candle close, aligned to
the real clock (09:20, 09:25, …) with a settable stop-after count.

Two limits, stated in the UI as well: **the page must stay open** for reminders to fire, and system
notifications need browser permission. When permission is denied or unsupported, nothing breaks — every alert
still lands in the in-page alert log.

## Running it locally

```sh
cd option-strategy-suite
./serve.sh              # http://127.0.0.1:8787
./serve.sh 3000         # pick another port
HOST=0.0.0.0 ./serve.sh # also reachable from your phone on the same wifi
```

The script uses whichever of `python3`, `npx serve` or `php` it finds — there is nothing to install and nothing
to build. Any other static server works just as well:

```sh
python3 -m http.server 8787     # or
npx --yes serve .               # or
php -S 127.0.0.1:8787
```

Opening `index.html` straight from disk mostly works — the scripts are classic, not modules — but serve it if
you can: browsers restrict `localStorage` on `file://`, so your settings and language will not persist, and
notifications are disabled outside a secure context.

Each tab is deep-linkable: `#analyser`, `#t1`, `#pullback`, `#signal`, `#guide`.

### Single-file build

```sh
python3 build.py     # -> dist/nifty-option-suite.html
```

Inlines the stylesheet and all nine scripts into one ~185 KB file with no external references at all. Open it
by double-clicking — no server, no install, works offline, and it is easy to carry on a laptop or drop onto a
phone. The served version is still the better daily driver: some browsers block `localStorage` on `file://`,
and notifications need a secure context, so settings and language may not persist from a bare file.

### Deploying

`netlify.toml` in the repository root publishes this directory as-is, with a strict `Content-Security-Policy`
(the page loads no external resources at all). Point Netlify at the repository and no further configuration is
needed.

## Layout

```
option-strategy-suite/
├── index.html                 markup for all five tabs
├── serve.sh                   one-command local server
└── assets/
    ├── css/styles.css
    └── js/
        ├── utils.js           parsing, formatting, candle validation and stats
        ├── i18n.js            English + Tanglish strings and the language switch
        ├── config.js          tunable coefficients + localStorage persistence
        ├── analyser.js        tool 1
        ├── t1helper.js        tool 2
        ├── pullback.js        tool 3
        ├── signal.js          tool 4 — confluence, win estimate, metrics
        ├── alerts.js          notifications + candle-close scheduler
        └── app.js             tabs, settings drawer, formula reference
```

Each tool exposes its pure calculation separately from its rendering — `APP.analyser.analyse()`,
`APP.t1helper.decide()`, `APP.pullback.analyse()`, `APP.signal.evaluate()` — so the model can be tested or
reused without the DOM.

## Disclaimer

Educational tool only. Nothing here is investment advice or a recommendation to trade. Options carry
substantial risk of loss; every level is derived arithmetically from the values you type and carries no
predictive guarantee. Verify each number against your broker terminal before acting on it.

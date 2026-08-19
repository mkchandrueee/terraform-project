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
| 3 (steps 6–10) | **T1 Decision Helper** | Trade side, the three mapped levels, and the OHLC of the candle that confirmed the entry | Hold → T2 vs partial book vs book now, a momentum score, the T1→T2 reward ratio, four condition checks, the condition-4 gate and an action plan |
| 4 (steps 11–13) | **Stoploss Pullback Entry** | The original first-candle OHLC of both sides | Call buy / put buy / **wait**, three entry zones, a stop and three targets |
| 5 (steps 14–16) | **Trade Signal** | The levels, standard indicator readings off the NIFTY chart, lots and account size | Take / caution / skip, win estimate, expected profit, expected value, breakeven win rate, sizing, and browser notifications |
| 6 (steps 17–18) | **Scan — intraday** | An underlying (index or NIFTY 50 stock), timeframes, strikes either side of ATM, how many expiries | Every combination through the analyser model, timeframe agreement per strike, and the best qualifying row |
| 6 (steps 17–18) | **Scan — swing** | The same underlying, and which of 1h / 1d / 1w / 1M to read | The last completed candle at each timeframe through the same model, long or short, and whether the timeframes agree |

The tools hand off to each other:

| Button | Fills |
|---|---|
| *Send CALL / PUT to T1 Helper* | entry ← **stop loss**, T1 ← **entry price**, T2 ← **Target 1** — steps 6–7 of the guide, verbatim |
| *Copy from analyser* (pullback) | the two original first-candle OHLC sets |
| *Levels from call / put* (signal) | entry ← entry price, stop ← stop loss, T1 ← Target 1, T2 ← Target 1 + range |

The T1 hand-off follows the strategy guide's steps 6–7 exactly — entry field ← stop loss, T1 field ← entry
price, T2 field ← Target 1 — and the T1 Decision Helper's rules are the guide's throughout: the decide
outcomes are *hold T2* versus *book now / partial book*, and condition check 4 is the step-10 gate that
decides whether the trade is taken at all. A line under the three fields names what each one holds, since the
mapping reads oddly at a glance.

Because the ladder is deliberately shifted, its three levels are **not** equally spaced under the analyser
model above, so the T1→T2 reward ratio reads whatever the two gaps give rather than a constant 1.00×.

## About the formulas

The strategy guide specifies **which** values each tool produces, not the arithmetic behind them. Where
screenshots of the original tools pinned a number down, this implementation matches it; everything else is the
most natural reading of the guide's structure. Every coefficient is exposed under **Formula settings** so it
can be re-tuned to match your own numbers — settings persist in the browser and re-run any open result
immediately.

**Options Analyser** — this is the original tool's model, recovered exactly from screenshots of four legs
(24300 CE/PE and 24400 CE/PE). All twenty values — entry, three targets and the stop on each leg — reproduce
to the paisa:

```
range    = high − low
entry    = close × 1.005                 ← the close drives it, hence "CLOSE ★ (FIXED)"
step     = max(0.8 × range, 16)
Target 1 = entry + step                  book 40%
Target 2 = entry + 2.0 × step            book 40%
Target 3 = entry + 3.5 × step            hold 20%
stop     = low − 0.3 × range             exit all
```

Which leg to buy, and how confidently:

```
confidence = 20 × (close > open) + 40 × body ÷ range + 40 × close position
side       = whichever of CE / PE scores higher
verdict    = YES at confidence ≥ 60
PCR        = put close ÷ call close      ≥1.2 bearish, ≤0.8 bullish, else neutral
```

On the 24400 legs that gives the put 20 + 40×0.75 + 40×0.75 = **80%** and a **BUY PUT** verdict with PCR
**1.10 Neutral** — the same numbers the original prints. Below the verdict sit the eight entry conditions and
six numbered rules, both filled in with the chosen side's own levels.

**T1 Decision Helper** — three weighted checks on the T1-touch candle produce a 0–100 momentum score, and a
fourth check sits outside the score as the gate:

| # | Check | Weight | Passes when |
|---|---|---|---|
| 1 | Direction | 40 | Candle direction matches the trade side |
| 2 | Body strength | 15 strong / 2 moderate | Body ÷ range ≥ 0.65 scores full, 0.45–0.65 scores 2, below that nothing |
| 3 | Close position | 45 | Close in the favourable half of the candle range |
| 4 | **T1 breakout strength** | *gate* | Close above the T1 level — the breakout actually happened |

`momentum = floor(sum of the weights earned)`. Those weights are not invented: they reproduce **every**
momentum score the original has published — 0%, 2%, 15% and 87%. The body tiers are pinned exactly at
15 / 2 / 0 by those four cases; direction and close must total 85 and no published case separates them, so
they are split 40 / 45.

Verdict: **WAIT** if check 4 failed (nothing is confirmed, so there is nothing to hold or book); otherwise
**HOLD → T2** at momentum ≥ 70, **PARTIAL BOOK** at ≥ 40, **BOOK NOW** below that. Check 4 is also rendered as
the standalone pre-trade gate the guide requires at step 10: passed → proceed, not passed → skip, whatever the
verdict says. Alongside the score the tool shows `T1→T2 reward ratio = (T2 − T1) ÷ (T1 − entry)` and an action plan that
changes with the verdict.

### The put side is graded side-inverted, matching the original

The original treats a *bullish* candle as wrong for a put trade and wants the close in the lower half of the
range, which is how it reaches 15% on entry 14.40 / T1 26.13 / T2 51.73 with candle 14/27/14/27. That is the
default here, so the app agrees with it out of the box.

It is worth knowing why the reading is arguable: this workflow feeds the helper the **option's own premium
candle**, and you are long the option on either leg, so a rising premium is a gain whether you hold a call or a
put. **Formula settings → Direction convention → Option premium** switches to that reading if you prefer it.

**Stoploss Pullback Entry** — the side with the stronger first-candle liquidity structure is the tradable one,
and the entries sit *inside* the range, because the setup buys the pullback rather than the breakout:

```
liquidity score = 45% × close position + 30% × body ÷ range
                + 15% × (close > open) + 10% × share of combined range
side   = whichever of CE / PE scores higher

zone 1 = low + 0.25 × range        aggressive — earliest fill, worst price
zone 2 = low + 0.38 × range        best (average) — stop and targets measure from here
zone 3 = low + 0.50 × range        last chance — above this, skip

stop     = low less 5%, to the nearest rupee
Target 1 = zone 2 + round-to-10(0.8 × range)     book 40%
Target 2 = zone 2 + round-to-10(1.4 × range)     book 40%
Target 3 = zone 2 + round-to-10(2.2 × range)     hold 20%
```

On the reference leg (O61 H97 L61 C86) that gives zones **₹70 / ₹74.7 / ₹79**, stop **₹58** at −16.7 points,
and targets **₹104.7 / ₹124.7 / ₹154.7** at +30 / +50 / +80 — the original's numbers exactly. The original's
own concept note confirms the bounds independently: *"entry = 25–50% of candle range from LOW, SL = below LOW
only"*. The stop rule and target multipliers still rest on a single sample.

Before any of that, each leg has to qualify on three things — direction, a decisive body, and a close above
the midpoint:

| Leg verdict | When |
|---|---|
| **GOOD** | all three pass — this side is tradable |
| **DOJI** | body under 10% of range — no momentum, refused outright |
| **NO TRADE** | some checks failed |

If neither leg is GOOD the tool answers **⏸ WAIT — No Signal** and shows no levels at all, rather than picking
the least bad side. On CE 125/135/84/124 with PE 50/56/24/26 that is exactly what the original does: call
DOJI, put NO TRADE, no trade today.

**The guide and the tool disagree about the stop.** Your strategy guide states this tool takes *no stop loss*;
the original app prints one. Both are shown — the level is there, with a note that the guide forbids acting on
it — so the choice is yours rather than mine.

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

## Scan — the same maths across timeframes, strikes and expiries

The Scan tab answers one question the single 5-minute candle cannot: **does the setup still hold when you look
at a longer opening candle?** Each timeframe is the first candle of the day at that length:

| Timeframe | Window |
|---|---|
| 5 min | 09:15–09:20 |
| 15 min | 09:15–09:30 |
| 30 min | 09:15–09:45 |
| 60 min | 09:15–10:15 |

Pick the underlying, the timeframes, how many strikes either side of ATM, and how many expiries; the helper
fetches one tick series per contract and re-aggregates it per timeframe, so 24 combinations cost 6 fetches
rather than 24.

### Indices and NIFTY 50 stocks

The **Underlying** field takes any NSE F&O symbol. The five indices (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY,
NIFTYNXT50) and all fifty NIFTY 50 stocks are offered as suggestions, but the field stays free text — an index
reconstitution makes that list stale, never wrong, and the same field appears on the Analyser tab's auto-fetch
card. Both fields share one remembered value.

Stocks are not indices, and three things differ. The helper handles all three from the live chain rather than
from a table that goes stale:

| | Index | NIFTY 50 stock |
|---|---|---|
| Chain endpoint | `option-chain-indices`, v3 `type=Indices` | `option-chain-equities`, v3 `type=Equity` |
| Strike spacing | 50 or 100 | varies per stock — RELIANCE 20, BAJFINANCE 100 |
| Expiries | weekly | monthly |
| Lot size | 75 for NIFTY | per stock, from `quote-derivative` |

**Strike spacing is read off the chain itself** — the most common gap between adjacent strikes — so nothing
needs setting when you switch symbols, and NSE revising a stock's spacing cannot silently misplace the ATM.
`--strike-step` still overrides it. For the same reason, *strikes either side of ATM* counts **strikes, not
rupees**: ±1 is the neighbouring contract whether that is 20 points away or 100.

**Lot size follows the symbol.** It is a property of the contract, not a preference, so a fetch or scan writes
the live value into the settings and says so — a RELIANCE trade costed against NIFTY's 75 would be wrong in
every figure on the Trade Signal tab.

If NSE lists no options on what you typed, the scan says exactly that rather than "no rows".

**There is no new arithmetic.** Every row goes through the same `APP.analyser.analyse()` the Option Analyser
tab uses, so a scan row and the analyser agree by construction — the tests assert that on the best row's entry,
targets and stop. *Send best row to Analyser* loads its candles into the normal workflow.

The part worth reading is **timeframe agreement**, shown per strike: whether every selected timeframe picks the
same side. All four agreeing is the confirmation worth having; a side that appears only on the 5-minute candle
is noise, and the card says *split* rather than pretending otherwise.

## Swing scan — hourly, daily, weekly, monthly

The Scan tab has two modes. **Intraday** is everything above: the 09:15 candle, widened, across option
strikes and expiries. **Swing** asks a different question — *what did the last completed candle at this
timeframe do?* — which is what a short-term or positional read is built on.

| Timeframe | Built from | Reads as |
|---|---|---|
| 1 hour | today's tick series, folded into clock hours | intraday momentum |
| 1 day | NSE's historical endpoint | short-term swing |
| 1 week | the dailies, grouped Monday to Friday | positional |
| 1 month | the dailies, grouped by calendar month | positional, slowest |

Three things are worth understanding, because they are where this differs from the intraday scan.

**These are the underlying's own candles.** NSE publishes no daily history worth reading for an individual
option contract — each one is young, thin, and ceases to exist at expiry. So a stock's or index's price bars
drive the read, and **the levels come out in share prices, not option premiums**. To trade them as options you
still pick a strike and read that contract's own premium; *Take best to Analyser* carries the price into the
ATM selector to start that off, which is the only hand-off that is honest here.

**A candle still forming is excluded.** Half a month wearing a month's label would produce levels that move
under you every session. The running bar is dropped unless you tick *also show the one still open*, and it is
labelled and can never be the best row. Nor can a stale one: with several candles per timeframe requested, the
older ones are shown for context, but *BEST* is chosen only among each timeframe's newest closed candle —
last Tuesday's setup is not on offer today.

**The maths is unchanged.** The long reading is `APP.analyser.analyseSide` called verbatim; a test asserts the
two are identical to the last decimal. The short reading is that reflected — entry `close × 0.995` instead of
`× 1.005`, targets below instead of above, stop `high + 0.3 × range` instead of `low − 0.3 × range`, and the
same 20 / 40 / 40 confidence weights read for a down candle. The side is whichever scores higher, exactly as
CE versus PE is decided upstairs.

The one substitution is the target-step floor. `max(0.8 × range, 16)` has a floor of **16 rupees of option
premium**, which means nothing on a share price — it would demand a ₹16 step on a ₹100 stock and never bind at
all on a ₹3,000 one. Here the floor is a percentage of price instead, `swingMinStepPct`, default 0.25%. At
that value the range term dominates in almost every real case, which is the intent: a floor, not a driver.

Timeframe agreement is per symbol rather than per strike: the latest closed candle on each, and whether they
point the same way. An hourly signal fighting the weekly and monthly is the one worth being careful about.

## Auto-fetching the first candle from NSE

The Analyser tab can fill the CE/PE OHLC fields itself instead of you typing them at 09:21. Two things make
this need a helper process rather than a `fetch()` in the page:

- **NSE sends no CORS headers.** A browser blocks the response before your code sees it, whatever you do.
- **NSE gates its APIs behind session cookies** set by a browser-like visit to the site, with a matching
  `User-Agent` and `Referer`.

So `tools/nse-fetch.js` does the handshake on your machine and re-serves the result on localhost with CORS
enabled. Node 18+, no dependencies:

```sh
node tools/nse-fetch.js --check       # will this work on my machine? answers stage by stage
node tools/nse-fetch.js               # http://127.0.0.1:8123
node tools/nse-fetch.js --mock        # fixture data, no network — good for a dry run
node tools/nse-fetch.js --dump chain  # which chain endpoint answered, and its shape
node tools/nse-fetch.js --dump CE     # the raw tick payload it reads

node tools/nse-fetch.js --symbol RELIANCE --check   # same checks against a stock
```

One helper serves every symbol — the app passes `?symbol=` per request, so there is no need to restart it when
you switch:

```
GET /first-candle?symbol=RELIANCE
GET /scan?symbol=BAJFINANCE&tfs=5,15,30,60&offsets=-1,0,1&expiries=2
```

`--symbol` only sets the default for requests that omit it, and for `--check` and `--dump`. Both payloads
carry back `kind` (index or equity), `strikeStep` and `lotSize` alongside the candles.

### NSE keeps moving the option-chain endpoint

`/api/option-chain-indices` now returns **404** for many users; the replacement is `/api/option-chain-v3`,
which needs an explicit expiry, and the expiry list comes from its own endpoint. Rather than pick one and
hope, the helper tries them in order and tells you which answered:

1. `/api/option-chain-contract-info` for the expiry list, then `/api/option-chain-v3` for each expiry
2. `/api/option-chain-indices` — or `/api/option-chain-equities` for a stock (legacy, whole chain in one call)

**v3 without a valid expiry answers `200 {}`, not an error**, so an empty object is treated as "wrong
expiry, keep trying" rather than success. If no endpoint publishes the expiry list, the helper falls back to
the calendar: the next six weekly expiries for an index, the next three monthlies for a stock. Expiry day is
Tuesday, and `--expiry-day` covers the next time NSE moves them.

`--check` prints the winner. If both are dead it lists every URL tried with its status, and you can force one:

```sh
node tools/nse-fetch.js --dump expiries              # what it will try, and where from
node tools/nse-fetch.js --expiry 30-Oct-2025         # skip discovery entirely
node tools/nse-fetch.js --expiry-day 4               # if weeklies move back to Thursday
node tools/nse-fetch.js --chain-url "https://www.nseindia.com/api/whatever-works"
```

The payload readers accept `records.data`, a flat `data`, or `filtered.data`, and find the spot from
`underlyingValue` at any of those levels or from a contract row — so a reshuffled response shape does not
break it either.

Run `--check` first, during market hours. It walks the whole live pipeline — Node version, reaching NSE and
getting session cookies, the option chain, ATM strike and nearest expiry, the tick series, and whether the
timestamps actually land inside 09:15–09:20 IST — printing a tick or cross per stage with what to do about a
failure. It exits non-zero if anything failed, so it also works as a pre-market smoke test.

Then on the Analyser tab: **Check helper** confirms it is up, **Fetch now** pulls immediately, and
**Auto-fetch at 09:21** arms it to fire at 09:21:05 — just after the 09:20 candle closes — retrying every 15
seconds until 09:22:30 if the feed lags. It fills both option candles and the NIFTY open, then runs the
analysis. If the helper is not running you get the exact command to start it and everything still works typed
in by hand.

What the helper does: reads the option chain for the nearest expiry, takes the ATM strike (rounded **down**, as
the guide does), pulls each leg's tick series and folds the ticks between 09:15 and 09:20 IST into one OHLC
candle. The window is anchored to IST regardless of your machine's timezone, and the closed candle is cached
for the day.

### Two things that decide whether it works on your machine

**Your IP.** NSE refuses datacenter, cloud and many VPN addresses while serving the same request fine from a
home connection. A block shows up as no session cookies, and `--check` says so in those words.

**Node 18.14+.** `getSetCookie()` arrived in that release; older 18.x hands back every cookie joined into one
string, which the helper parses itself — but check it rather than assume.

### Tick timestamps and which session you actually got

Two things the chart endpoint does that will bite you if unhandled, both now handled automatically:

**Its timestamps are IST wall-clock already, not true epoch.** Adding the IST offset a second time lands every
tick 5h30m late, so a 09:15 open reads as 14:45 and nothing falls inside the window. The helper tests both
readings and keeps whichever puts the first tick nearest the 09:15 open, reporting which it chose — so if NSE
ever switches convention it corrects itself rather than silently returning nothing.

**Before the open, and on holidays, it serves the last completed session.** Running at 09:05 on a Monday
returns Friday's ticks. That is legitimate data but it is *not today's candle*, and trading it as if it were
would be the worst failure this tool could have. The payload carries `session` and `stale`, `--check` prints
the session date against today's, and the app shows a warning banner rather than a success line:

> ⚠ This is the 2026-08-14 session — the last completed one, NOT today. Do not trade it as if it were live.

### Verify this against your own feed before trusting it

NSE's chart endpoint is undocumented and its tick timestamps are the one part of this that could differ from
what the helper assumes. **This has not been tested against live NSE** — the environment it was written in
blocks nseindia.com, so it was verified end to end against a fixture instead. Run `--dump CE` once during
market hours: it prints the raw ticks alongside how the helper reads them, so a mismatch is obvious in one
glance. If the timestamps are offset, `--from`/`--to` let you correct the window without touching the code.

Whatever the helper fills in, the values land in ordinary editable fields — check them against your broker
terminal before you trade, exactly as you would if you had typed them.

## Notifications

The signal can fire a browser notification carrying the verdict, entry, stop, target, win estimate, expected
profit, expected value and risk-reward. A separate reminder fires on every 5-minute candle close, aligned to
the real clock (09:20, 09:25, …) with a settable stop-after count.

Two limits, stated in the UI as well: **the page must stay open** for reminders to fire, and system
notifications need browser permission. When permission is denied or unsupported, nothing breaks — every alert
still lands in the in-page alert log.

On **iOS** the bar is higher still — 16.4+, installed to the Home Screen, and served over HTTPS — so over a
plain wifi address there are no system notifications at all. The in-page log is the fallback and it works
unchanged. See [IOS.md](IOS.md).

## On an iPhone or iPad

The helper must run on a machine with a **home** internet connection — not because of iOS, but because NSE
refuses datacenter and cloud IP ranges, so a hosted copy gets blocked at the source. iOS has no Node runtime
either. So the helper stays on your PC and the only question is how the phone reaches it:

| | Reaches the helper | On mobile data | Auto-fetch + Scan | Notifications |
|---|---|---|---|---|
| **Tunnel** — `start-tunnel.cmd` | over the internet, https | **yes** | yes | **yes** |
| **Same wifi** — `start-lan.cmd` | over your LAN, http | no | yes | no |
| **Phone alone** — the single-file build | not at all | yes | no, type the values | no |

The tunnel is the one to use if you do not want to depend on being on the same wifi. `--serve` puts the app
and the API on **one port and one origin**, so a single `cloudflared` quick tunnel covers everything, and
`--token` gates every route because that URL is public. Being https, it is also the only setup where iOS
delivers notifications. Tailscale does the same privately.

```sh
node tools/nse-fetch.js --serve --token SECRET     # app + API on one origin, gated
cloudflared tunnel --url http://127.0.0.1:8123     # → https://….trycloudflare.com
```

The app resolves the helper by itself in all three cases: served by the helper it uses its own origin (no
`:8123` to append behind a tunnel), loaded from a LAN address it uses that host on 8123, and only a bare
localhost page falls back to `127.0.0.1`.

[IOS.md](IOS.md) has the full walkthrough for each, plus the iOS-specific limits.

## Running it locally

**Windows:** see [WINDOWS.md](WINDOWS.md) for a step-by-step setup — install Node, extract, double-click
`start.cmd`. That launches the NSE helper and the app together and opens the browser.

**macOS / Linux:**

```sh
cd option-strategy-suite
./serve.sh              # http://127.0.0.1:8787
./serve.sh 3000         # pick another port
HOST=0.0.0.0 ./serve.sh # also reachable from your phone on the same wifi
```

It prefers `node tools/serve.js` — a zero-dependency static server, the same one the Windows launchers use —
and falls back to `python3` or `php`. Nothing to install, nothing to build. Any other static server works too:

```sh
node tools/serve.js 8787        # or
node tools/serve.js 8787 lan    # also reachable over wifi
python3 -m http.server 8787
```

Opening `index.html` straight from disk mostly works — the scripts are classic, not modules — but serve it if
you can: browsers restrict `localStorage` on `file://`, so your settings and language will not persist, and
notifications are disabled outside a secure context.

Each tab is deep-linkable: `#analyser`, `#t1`, `#pullback`, `#signal`, `#guide`.

### Single-file build

```sh
python3 build.py     # -> dist/nifty-option-suite.html
```

Inlines the stylesheet and all twelve scripts into one ~275 KB file with no external references at all. Open it
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
├── manifest.webmanifest       Home Screen install metadata
├── serve.sh                   one-command local server
├── start-lan.cmd              Windows: both servers on the wifi, for a phone
├── start-tunnel.cmd           Windows: one https address, phone from anywhere
├── build.py                   single-file bundler
├── IOS.md                     running it on an iPhone or iPad
├── tools/
│   └── nse-fetch.js           local NSE helper (session, ticks → 09:15–09:20 candle)
└── assets/
    ├── css/styles.css
    ├── icons/                 Home Screen icons (iOS ignores data: URIs here)
    └── js/
        ├── utils.js           parsing, formatting, candle validation and stats
        ├── i18n.js            English + Tanglish strings and the language switch
        ├── config.js          tunable coefficients + localStorage persistence
        ├── symbols.js         index + NIFTY 50 symbol list for the pickers
        ├── analyser.js        tool 1
        ├── t1helper.js        tool 2
        ├── pullback.js        tool 3
        ├── autofetch.js       talks to the local NSE helper
        ├── signal.js          tool 4 — confluence, win estimate, metrics
        ├── scan.js            tool 5 — multi-timeframe / strike / expiry scan
        ├── swing.js           tool 5b — 1h / 1d / 1w / 1M on the underlying
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

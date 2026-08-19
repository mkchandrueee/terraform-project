# Running on Windows — `D:\Claude\niftyoptionsuite`

Everything below assumes the project sits at `D:\Claude\niftyoptionsuite`, so
`D:\Claude\niftyoptionsuite\index.html` exists. Adjust the path if you put it elsewhere.

---

## Step 1 — Install Node.js (once)

Download the **LTS** build from <https://nodejs.org> and install it with the defaults. Node is the only thing
you need: it runs both the app's web server and the NSE helper.

Check it worked — open **Command Prompt** (press `Win`, type `cmd`, Enter):

```bat
node --version
```

You want `v18.14.0` or higher. If you see `'node' is not recognized`, close every Command Prompt window and
open a fresh one — the installer adds Node to `PATH` and only new windows pick that up.

---

## Step 2 — Put the files in place

Extract the zip so the folder looks like this:

```
D:\Claude\niftyoptionsuite\
├── index.html
├── start.cmd            ← double-click this to run everything
├── start-lan.cmd        ← the same, but reachable from your phone on wifi
├── start-tunnel.cmd     ← one https link, phone from anywhere
├── serve.cmd            ← app only, no NSE helper
├── check-nse.cmd        ← "will the NSE fetch work on my machine?"
├── build.py
├── serve.sh
├── assets\
│   ├── css\styles.css
│   └── js\...
└── tools\
    ├── serve.js
    └── nse-fetch.js
```

---

## Step 3 — Start it

**Double-click `start.cmd`.**

That opens two Command Prompt windows and your browser:

| Window | What it is | Port |
|---|---|---|
| *NSE helper* | Fetches the 09:15–09:20 candle from NSE | 8123 |
| *Option Suite* | Serves the app | 8787 |

The browser lands on <http://127.0.0.1:8787>. **Leave both windows open** while you trade — closing one stops
that piece. Close them when you are done, or press `Ctrl+C` in each.

Just want the app without the NSE fetch? Double-click **`serve.cmd`** instead.

### If Windows SmartScreen or a firewall prompt appears

The first run may show a Windows Defender Firewall prompt for Node. Allow it on **Private networks** — the
servers only listen on `127.0.0.1` (your own machine) unless you deliberately switch on LAN mode below.

---

## Step 4 — Check the NSE fetch works (do this during market hours)

**Double-click `check-nse.cmd`**, or run:

```bat
cd /d D:\Claude\niftyoptionsuite
node tools\nse-fetch.js --check
```

It walks the whole pipeline and prints a tick or cross per stage:

```
  ✓ Node version — Node 22.11.0
  ✓ Reach nseindia.com + session cookies — 4 cookies
  ✓ Option chain API — 142 strike rows
  ✓ ATM strike + nearest expiry — spot 23712.4 → ATM 23700, expiry 21-Aug-2026
  ✓ Tick series for the ATM call — 318 ticks
  ✓ Timestamps land in the 09:15–09:20 IST window — 61 ticks → O 148.5 H 162.75 L 141.2 C 159.9
```

All ticks → you are ready. Any cross → see **Troubleshooting** below; the suite still works with the four
values typed in by hand, which is exactly how you would have used it anyway.

---

## Step 5 — Use it on a trading morning

1. Open <http://127.0.0.1:8787> before 09:15.
2. On the **Option Analyser** tab, in the *Auto-fetch* card, click **Check helper** — it should say the helper
   is up.
3. Click **Auto-fetch at 09:21**. It arms and fires at 09:21:05, retrying until 09:22:30 if the feed lags.
4. At 09:21 the CE and PE candles fill themselves and the analysis runs — entry, Target 1 and stop loss for
   both sides.
5. Carry on through the tabs as usual: T1 Decision Helper → Pullback Entry → Trade Signal.

Prefer to do it by hand? Type the four values into each side and press **Analyse**. Nothing about the rest of
the app depends on the helper.

---

## Optional — use it from your iPhone ANYWHERE (mobile data included)

`start-lan.cmd` below only works when the phone is on your wifi. To use it from anywhere, publish the
PC through a tunnel instead. The PC still does the NSE talking — it has to, NSE blocks cloud IPs — the
tunnel just gives it an https address your phone can open from mobile data.

Install cloudflared once:

```bat
winget install --id Cloudflare.cloudflared
```

Then double-click **`start-tunnel.cmd`**. It generates a one-time secret, starts the suite with the app
and the API on a **single port** (so one tunnel covers both), and starts cloudflared, which prints
something like `https://calm-river-fox-12.trycloudflare.com`. On the phone open:

```
https://calm-river-fox-12.trycloudflare.com/?token=YOUR-SECRET
```

Both strings are in the window. No firewall rule, no IP addresses, no wifi requirement. Because the
link is https, notifications also work once you Add to Home Screen — the LAN option cannot do that.

The secret matters: a quick tunnel URL is public, and `--token` is what stops anyone holding it from
driving your helper. A new one is generated per run, so old links die. See [IOS.md](IOS.md).

---

## Optional — use it from your iPhone on the same wifi

**Double-click `start-lan.cmd`** instead of `start.cmd`. It runs the same two servers, but bound to the whole
network rather than only to this PC, and prints the address to type on the phone:

```
  On this PC      http://127.0.0.1:8787
  On your iPhone  http://192.168.1.24:8787
```

Open that second address in Safari. Both devices must be on the same wifi, and Windows will ask once whether
to allow Node on **Private networks** — say yes. If you missed the prompt, run this once from an
**Administrator** Command Prompt:

```bat
netsh advfirewall firewall add rule name="Option Suite" dir=in action=allow protocol=TCP localport=8787,8123
```

**Auto-fetch works from the phone.** The helper is bound to the network too, and the app points itself at it —
loaded from `192.168.1.24:8787`, it defaults the *Local helper address* to `192.168.1.24:8123` rather than to
`127.0.0.1`, which on a phone would mean the phone itself. Tap **Check helper** to confirm.

In Safari, **Share → Add to Home Screen** gives it an icon that opens full-screen. See [IOS.md](IOS.md) for the
iOS-specific details, including why system notifications do not fire over a plain wifi address.

---

## Optional — one file, no server at all

```bat
cd /d D:\Claude\niftyoptionsuite
python build.py
```

Produces `dist\nifty-option-suite.html`, which you can double-click straight from Explorer or copy to a phone.
Needs Python only for the build step; the output itself needs nothing.

This is the least capable way to run it: browsers restrict `localStorage` on `file://`, so your settings and
language may not persist, notifications are disabled, and auto-fetch cannot reach the helper. Handy as a
portable backup, not as the daily setup.

---

## Troubleshooting

**`'node' is not recognized`**
Node is not installed, or this Command Prompt predates the install. Open a fresh window; reinstall if it
persists.

**`Port 8787 is already in use`**
Something else has the port. Use another: `node tools\serve.js 8788`, then browse to
<http://127.0.0.1:8788>. Same for the helper: `node tools\nse-fetch.js --port 8124` — and update the
*Local helper address* box in the app to match.

**The app says "No helper at http://127.0.0.1:8123"**
The helper window is not running or has exited. Look at that window for an error, or start it with
`node tools\nse-fetch.js`.

**`--check` fails at "Reach nseindia.com + session cookies"**
Almost always your IP. NSE refuses datacenter, cloud and many VPN addresses while serving a home connection
fine. Turn the VPN off and retry. A corporate network may also block it.

**`--check` fails at "Timestamps land in the 09:15–09:20 IST window"**
The chart endpoint is undocumented and its timestamps are the one thing that could differ on your feed. Look
at the raw values:

```bat
node tools\nse-fetch.js --dump CE
```

It prints the first ticks with how the helper reads them in IST. If they are offset, point the window at what
your feed actually sends:

```bat
node tools\nse-fetch.js --from 09:15 --to 09:20
```

**Numbers look wrong**
Check them against your broker terminal before trading — the auto-fetch fills ordinary editable fields, and
overtyping them is always fine.

**"NSE returned no option chain for …"**
The symbol has no options listed. Use the NSE *trading* symbol, not the company name — `BAJFINANCE` not
"Bajaj Finance", `M&M` not "Mahindra". The picker suggests all fifty NIFTY 50 symbols; typing one is only
needed for something outside that list.

**"Swing scan failed — NSE 503 for .../api/historical/..."**
NSE refuses historical requests spanning more than about a quarter, and throttles bursts. The helper now asks
in 80-day windows and retries transient failures, so this should not recur — if it does, the endpoint is down
rather than saying no. Check with:

```bat
curl "http://127.0.0.1:8123/history?symbol=WIPRO&tfs=1d&bars=1"
```

Asking for fewer candles per timeframe, or dropping the monthly box, shortens the history needed and so the
number of requests.

**Swing scan fails with 503 — find out why**
A 503 can be NSE's bot protection, an application error, or a real outage, and the status code alone cannot
tell them apart. This prints what NSE actually sends back for each variation:

```bat
node tools\nse-fetch.js --symbol BAJAJFINSV --probe
```

It fetches a known-working endpoint as a control, then the historical one with the range, Referer, cookies and
headers varied one at a time, showing the status, which server answered, and the response body. That output
identifies the cause; nothing else has.

**Swing scan fails with 503 on every historical endpoint**
Not an outage. NSE's bot protection checks the `Referer` against the API and wants a session that has browsed
the matching page; the helper now visits the quote page first and sends the right Referer, which is what this
was. If it comes back, open

```
https://www.nseindia.com/get-quotes/equity?symbol=BAJAJFINSV
```

in a normal browser on the same machine, then retry — that re-establishes the protection cookies for your IP.

**"Swing scan failed — no historical endpoint returned rows for ..."**
NSE moves these paths and a retired one answers `200` with an empty list rather than a 404, so it looks
identical to "this symbol has no data". The helper tries the current path, the older one, and two series
variants before giving up, and the error now names each and what it answered. To see it directly:

```bat
node tools\nse-fetch.js --symbol ASIANPAINT --dump history
```

That prints every candidate, how many usable rows it returned, and the field names in the response — enough to
tell a moved endpoint from a wrong symbol. Use the NSE *trading* symbol; this works even for a stock with no
listed options, since price history and option chains are separate.

**A stock's strikes or lot size look wrong**
Both are read live from that symbol's own chain, so they follow NSE rather than a table in the app. Confirm
what it found:

```bat
node tools\nse-fetch.js --symbol RELIANCE --dump chain
```

It prints the strike step it derived and the lot size. `--strike-step 20` overrides the step if you need to.

---

## Command reference

Run these from `D:\Claude\niftyoptionsuite` in Command Prompt.

| Command | What it does |
|---|---|
| `start.cmd` | Helper + app + browser, all at once |
| `start-lan.cmd` | The same, but reachable from your iPhone on the same wifi |
| `start-tunnel.cmd` | One https link, usable from the phone anywhere |
| `serve.cmd` | App only |
| `check-nse.cmd` | Self-check of the NSE pipeline |
| `node tools\serve.js 8787` | App on a chosen port |
| `node tools\serve.js 8787 lan` | Also reachable over wifi |
| `node tools\nse-fetch.js` | NSE helper on port 8123 |
| `node tools\nse-fetch.js --check` | Stage-by-stage diagnosis |
| `node tools\nse-fetch.js --symbol RELIANCE --check` | The same checks against a stock |
| `node tools\nse-fetch.js --mock` | Fixture data, no network — dry run |
| `node tools\nse-fetch.js --dump CE` | Raw NSE payload |
| `node tools\nse-fetch.js --dump history` | Which history endpoint answers, and its shape |
| `node tools\nse-fetch.js --probe` | Why one refuses: status, server and body, variable by variable |
| `node tools\nse-fetch.js --serve --token X` | App + API on one port, gated by a secret |
| `curl "http://127.0.0.1:8123/history?symbol=RELIANCE&tfs=1d,1w,1M"` | Swing candles the Scan tab reads |
| `python build.py` | Single-file bundle in `dist\` |

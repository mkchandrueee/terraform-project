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

## Optional — use it from your phone on the same wifi

```bat
cd /d D:\Claude\niftyoptionsuite
node tools\serve.js 8787 lan
```

It prints a second address like `http://192.168.1.7:8787` — open that on your phone. Both devices must be on
the same wifi, and you may need to allow Node through the firewall on **Private networks**.

The NSE helper stays on `127.0.0.1`, so auto-fetch will not work from the phone. Read the values on the phone,
fetch on the PC.

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

---

## Command reference

Run these from `D:\Claude\niftyoptionsuite` in Command Prompt.

| Command | What it does |
|---|---|
| `start.cmd` | Helper + app + browser, all at once |
| `serve.cmd` | App only |
| `check-nse.cmd` | Self-check of the NSE pipeline |
| `node tools\serve.js 8787` | App on a chosen port |
| `node tools\serve.js 8787 lan` | Also reachable over wifi |
| `node tools\nse-fetch.js` | NSE helper on port 8123 |
| `node tools\nse-fetch.js --check` | Stage-by-stage diagnosis |
| `node tools\nse-fetch.js --mock` | Fixture data, no network — dry run |
| `node tools\nse-fetch.js --dump CE` | Raw NSE payload |
| `python build.py` | Single-file bundle in `dist\` |

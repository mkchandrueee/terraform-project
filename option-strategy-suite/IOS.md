# Running the suite on an iPhone

Tested against an iPhone 15 Pro Max (430 × 932 points); the same steps work on any iPhone or iPad on
iOS 16.4 or newer.

## The one constraint everything follows from

**The helper has to run on a machine with a home internet connection.** Not because of iOS — because
of NSE. Their APIs refuse datacenter and cloud IP ranges, so a copy of the helper on a VPS, on
Render, on Fly, on a Lambda, or on any hosting you could point at from the phone gets blocked at the
source. Nothing in this app can work around that; it is NSE's rule about where the request comes
from.

The helper is also a Node process, and iOS has no Node runtime and no way to keep a background server
alive. So the helper stays on your PC, and the only real question is **how the phone reaches it**.

| | Reaches the helper | Works on mobile data | Auto-fetch + Scan | Notifications |
|---|---|---|---|---|
| **A. Tunnel** (`start-tunnel.cmd`) | over the internet, https | **yes** | yes | **yes** |
| **B. Same wifi** (`start-lan.cmd`) | over your LAN, http | no | yes | no |
| **C. Phone alone** | not at all | yes | no — type the values | no |

**A is the one to use if you do not want to depend on being on the same wifi.** It is barely more
setup than B and strictly better: it works from anywhere, and because the link is https it is the
only option where iOS will deliver notifications.

---

## Option A — tunnel: the phone reaches the PC from anywhere

The PC still does the NSE talking, from your home connection, exactly as NSE requires. A tunnel just
gives that PC a temporary https address the phone can open from mobile data, another city, anywhere.

### One-time install on the PC

```bat
winget install --id Cloudflare.cloudflared
```

Free, no Cloudflare account needed for the quick tunnels this uses.

### Every time you want it

Double-click **`start-tunnel.cmd`**. It:

1. generates a fresh one-time secret for this run,
2. starts the suite on port 8123 — **one process serving both the app and the API**, so a single
   tunnel covers everything,
3. starts cloudflared, which prints a line like
   `https://calm-river-fox-12.trycloudflare.com`.

On the iPhone, open that address with the secret on the end:

```
https://calm-river-fox-12.trycloudflare.com/?token=YOUR-SECRET
```

Both are printed in the window. That is the whole setup — no firewall rule, no IP addresses, no wifi
requirement.

Then **Share → Add to Home Screen**. Safari keeps the secret in a cookie after the first load, so the
icon works without the query string.

### Why the token

A quick tunnel URL is public. Anyone who had it could otherwise drive your helper and read your NSE
session. `--token` gates **everything** — the app, every API route, static files — accepting the
secret from the query string, an `X-Helper-Token` header, or the cookie set on first use. Without it
every request gets a 401. `start-tunnel.cmd` makes a new secret on each run, so yesterday's link is
already dead.

Never run `--serve` on a public address without `--token`. The helper prints a warning if you do.

### The nice side effect

The tunnel is **https**, which is the condition iOS puts on web notifications. Add it to the Home
Screen, open it from that icon, and the Trade Signal tab can raise real system notifications — the
one setup here where that works.

### If you would rather not use a public URL

[Tailscale](https://tailscale.com) does the same job on a private network: install it on the PC and
the iPhone, sign both into the same account, and open `http://<pc-name>:8123/` from the phone. No
public address at all, works on mobile data, free for personal use. Run the suite with
`node tools\nse-fetch.js --serve` — the token is optional on Tailscale since only your own devices
can reach it. You do not get https, so no notifications.

---

## Option B — same wifi

Simpler, no extra install, but only at home.

1. Double-click **`start-lan.cmd`** on the PC. It prints `http://192.168.x.x:8787`.
2. Allow Node through the firewall on **Private networks**. If you missed the prompt, once from an
   **Administrator** Command Prompt:
   ```bat
   netsh advfirewall firewall add rule name="Option Suite" dir=in action=allow protocol=TCP localport=8787,8123
   ```
3. Open that address in Safari on the phone.

You should not need to touch the helper address — loaded from a network address, the app points the
*Local helper address* box at that same PC automatically rather than at `127.0.0.1`, which on a phone
would mean the phone itself.

---

## Option C — phone alone, no PC

For when you want the tools in your pocket and are happy typing the four OHLC values from your broker
app, which is how the original tools work anyway.

1. Copy **`dist/nifty-option-suite.html`** to the phone — AirDrop, iCloud Drive, or email.
2. Open it from the **Files** app.

Every tool works: all five tabs, both languages, the whole guide, one self-contained file with no
network access. What you lose is auto-fetch and the Scan tab, both of which need the helper.

iOS restricts `localStorage` for files opened this way, so formula settings and language may not
survive closing it.

Hosting that file (drag the folder onto [app.netlify.com/drop](https://app.netlify.com/drop);
`netlify.toml` is already in the repo) gets you a permanent https URL and persistent settings — but
**not** auto-fetch: Safari blocks an https page from calling your PC over http, and a cloud host
cannot call NSE. Hosted means typed values. If you want auto-fetch, use option A.

### The only genuine no-PC alternative

A broker API — Zerodha Kite, Upstox, Dhan — is designed to be called from anywhere with a token and
is not IP-restricted the way NSE's public endpoints are. That would need your broker credentials and
an API subscription, and is a different piece of software from this one. Worth knowing it exists;
this app does not do it.

---

## Notifications on iOS

iOS requires **all three**:

- iOS 16.4 or newer, **and**
- opened from a Home Screen icon, not a Safari tab, **and**
- served over **https**

Option A satisfies all three. Options B and C do not — over plain http `Notification` does not exist,
and the Trade Signal tab says so. **Nothing breaks either way:** every alert still lands in the
in-page log on that tab, and the candle-close reminders still fire while the app is on screen.

iOS suspends timers in backgrounded web apps regardless. If you rely on the 09:21 auto-fetch, leave
the app on screen with the phone unlocked, or arm it on the PC.

---

## What was changed to make this work

Nothing about the strategy maths. Five things about the app:

- **One process can serve everything.** `--serve` puts the app and the API on a single port and
  origin, so one tunnel covers the whole thing instead of needing two.
- **`--token`** gates every route, because a tunnel URL is reachable by anyone holding it.
- **The helper address resolves itself.** Served by the helper, the page is told so and uses its own
  origin — behind a tunnel there is no `:8123` to append. Loaded from a LAN address instead, it
  defaults to that host on 8123. Only a bare localhost page falls back to `127.0.0.1`.
- **Home Screen install metadata** — touch icon, the web-app metas, a status-bar style, a manifest —
  and `viewport-fit=cover` with safe-area padding so nothing sits under the Dynamic Island or the
  home indicator.
- **16px inputs on touch devices.** Safari zooms the page in whenever you focus an input whose text
  is under 16px and never zooms back out. Every OHLC field did it.

---

## Troubleshooting

**The tunnel link gives 401**
The secret is missing or stale. `start-tunnel.cmd` makes a new one each run — use the link from the
window that is open now, including `?token=…`.

**The tunnel link stopped working entirely**
Quick tunnels last only as long as `cloudflared` is running, and the address changes every run. That
is the trade for needing no account. A named Cloudflare tunnel gives a fixed address if you want one.

**`--check` fails at "Reach nseindia.com"**
Your IP, not your setup. NSE refuses datacenter, cloud and many VPN addresses. Turn the VPN off. If
you are running the helper anywhere other than a home connection, this is the constraint described at
the top and it cannot be worked around.

**Safari cannot connect (option B)**
The firewall, nine times out of ten — run the `netsh` command above. Otherwise check both devices are
on the same wifi; a phone on guest wifi and a PC on ethernet are often on subnets that cannot see
each other.

**"No helper at http://…"**
Check the *Local helper address* box. On the tunnel it should be the tunnel URL with no port; on the
LAN it should be your PC's IP with port **8123**. Tap **Check helper** to test it alone.

**iOS asks for "Local Network" permission**
Allow it (option B only). Settings → Privacy & Security → Local Network → Safari.

**The page zooms when I tap a field**
An older cached copy. Pull to refresh, or remove the Home Screen icon and re-add it.

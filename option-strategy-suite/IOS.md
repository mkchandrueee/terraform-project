# Running the suite on an iPhone

Tested against an iPhone 15 Pro Max (430 × 932 points), and the same steps work on any iPhone or iPad
running iOS 16.4 or newer.

There is one thing to understand before the steps, because it decides which of them you need.

**The app runs on the phone. The NSE helper cannot.** The helper is a Node process that performs a
cookie handshake with nseindia.com; iOS has no Node runtime and no way to keep a background server
alive. So there are two ways to use the suite on a phone, and they differ only in whether auto-fetch
works:

| | Phone alone | Phone + your Windows PC on the same wifi |
|---|---|---|
| All five tools, both languages | yes | yes |
| Saved settings, saved language | yes | yes |
| Auto-fetch the 09:15–09:20 candle | **no — type the values** | **yes** |
| Multi-timeframe Scan tab | **no** | **yes** |
| Needs the PC switched on | no | yes, while you fetch |

Set up the second one if you want auto-fetch. It is the same PC install you already have.

---

## Option A — phone plus PC on the same wifi (full functionality)

### 1. On the PC, start both servers bound to the network

Double-click **`start-lan.cmd`**.

It is the same as `start.cmd` except both servers listen on every network interface rather than only
on the PC itself, and it prints the address to type on the phone:

```
================================================================
  On this PC      http://127.0.0.1:8787
  On your iPhone  http://192.168.1.24:8787
================================================================
```

That `192.168.x.x` is your PC's address on your wifi. It is different on every network — read it from
the window, do not copy the one above.

### 2. Let Windows Firewall through, once

The first time, Windows will pop up a dialog asking whether to allow Node.js on the network. Tick
**Private networks** and allow it.

If you dismissed that dialog, or nothing loads on the phone, open Command Prompt **as Administrator**
and run this once:

```bat
netsh advfirewall firewall add rule name="Option Suite" dir=in action=allow protocol=TCP localport=8787,8123
```

### 3. On the iPhone, open that address in Safari

Type `http://192.168.1.24:8787` (your own address) into Safari's address bar. The app loads.

**You should not need to change the helper address.** The app notices it was loaded from a network
address rather than from localhost, and points the *Local helper address* box at the same PC
automatically. Check it reads `http://192.168.1.24:8123` — same IP, port 8123 — then tap **Check
helper**. It should say *Helper is up*.

### 4. Add it to the Home Screen

In Safari: **Share** → **Add to Home Screen** → **Add**.

You now have an icon that opens full-screen with no Safari address bar, like an app. This is worth
doing even beyond the looks — see the notifications note below.

---

## Option B — phone alone (no PC)

Use this when you want the tools in your pocket and are happy typing the four OHLC values from your
broker app, which is how the original tools work anyway.

1. Copy **`dist/nifty-option-suite.html`** to the phone — AirDrop, iCloud Drive, or email it to
   yourself.
2. Open it from the **Files** app. It opens in a browser view and everything works: all five tools,
   both languages, the whole guide. It is one self-contained file with no network access at all.

The catch: **iOS restricts `localStorage` on files opened this way**, so your formula settings and
language choice may not survive closing it. Everything still works within a session.

If you want it to persist and to have a Home Screen icon, host it instead. `netlify.toml` is in the
repo, so dragging the project folder onto [app.netlify.com/drop](https://app.netlify.com/drop) gives
you an HTTPS URL you can open and install from anywhere — but note that a page served over HTTPS
**cannot** call your PC's `http://192.168.x.x:8123` helper (Safari blocks mixed content), so
auto-fetch will not work from a hosted copy. Hosted means typed values.

---

## Notifications on iOS

iOS is stricter than every other platform here. Web notifications require **all** of:

- iOS 16.4 or newer, **and**
- the app added to the Home Screen and opened from that icon — not from a Safari tab, **and**
- the page served over **HTTPS**

Over plain `http://192.168.x.x` on your wifi, the third condition fails, so `Notification` does not
exist and the Trade Signal tab will say so. **Nothing breaks** — every alert still lands in the
in-page log on that tab, which is where you read them. The scheduled candle-close reminders also
still fire, as long as the app stays open in the foreground.

iOS also suspends timers in backgrounded web apps. If you rely on the 09:21 auto-fetch or the
5-minute reminders, leave the app on screen with the phone unlocked, or run those on the PC.

---

## What was changed to make this work

Nothing about the strategy maths. Four things about the app:

- **The helper address auto-detects.** Loaded from `192.168.1.24:8787`, the app defaults the helper
  to `192.168.1.24:8123` instead of `127.0.0.1:8123`, which on a phone would mean the phone itself.
  This was the single most confusing failure available, and it no longer happens.
- **Home Screen install metadata** — `apple-touch-icon`, `apple-mobile-web-app-capable`, a status-bar
  style, a title, and a web manifest.
- **Safe-area padding.** `viewport-fit=cover` lets the page paint behind the Dynamic Island and the
  home indicator; the CSS pads content back out of both so nothing sits under them.
- **16px inputs on touch devices.** Safari zooms the page in whenever you focus an input whose text is
  under 16px, and never zooms back out. Every OHLC field did this. The desktop keeps its tighter 15px
  fields.

---

## Troubleshooting

**Safari says it cannot connect**
The firewall, nine times out of ten. Run the `netsh` command above from an Administrator prompt. If it
still fails, confirm both are on the same wifi — a phone on 5 GHz guest wifi and a PC on ethernet are
often on different subnets that cannot see each other.

**The page loads but "No helper at http://…"**
Check the address in the box has your PC's IP with port **8123**, not 8787, and that the *NSE helper*
window is still open on the PC. Tap **Check helper** to test it on its own.

**iOS asks for "Local Network" permission**
Allow it. Settings → Privacy & Security → Local Network → Safari, if you need to change it later.

**Numbers are tiny, or the page zooms when I tap a field**
You are on an older cached copy. Pull down to refresh, or remove the Home Screen icon and re-add it.

**Landscape looks cramped**
Expected — the tool is built portrait-first. The Scan tab's table scrolls sideways on its own; the
page never does.

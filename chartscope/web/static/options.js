"use strict";
const $ = (id) => document.getElementById(id);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  for (const k of kids) if (k != null && k !== false) n.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return n;
}
const fmt = (x, d = 2) => (x == null ? "–" : Number(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }));
const money = (x) => (x == null ? "–" : (x < 0 ? "-₹" : "₹") + Math.abs(Math.round(x)).toLocaleString("en-IN"));

const chart = LightweightCharts.createChart($("chart"), {
  layout: { background: { color: css("--card") }, textColor: css("--muted") },
  grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
  rightPriceScale: { borderColor: css("--line") }, timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false },
});
const candles = chart.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"), borderVisible: false, wickUpColor: css("--up"), wickDownColor: css("--down") });
const vwap = chart.addLineSeries({ color: css("--accent"), lineWidth: 2, lastValueVisible: false, priceLineVisible: false, title: "VWAP" });
let lines = [], first = true, timer = null, seq = 0, seen = new Set(), loaded = false;
new ResizeObserver(() => chart.applyOptions({ width: $("chart").clientWidth, height: $("chart").clientHeight })).observe(document.body);

function pl(price, color, title, style = 2, width = 1) {
  if (price == null) return;
  lines.push(candles.createPriceLine({ price, color, lineWidth: width, lineStyle: style, axisLabelVisible: true, title }));
}

const STATUS_CLASS = { WAITING: "WAIT", ACTIVE: "LONG", T1: "LONG", TARGET: "LONG", T1_EXIT: "LONG", STOPPED: "SHORT", TIME_EXIT: "WAIT", SQUAREOFF: "WAIT", EXPIRED: "WAIT", CANCELLED: "WAIT", PREVIEW: "WAIT" };

function drawChart(r) {
  const range = first ? null : chart.timeScale().getVisibleLogicalRange();
  candles.setData(r.candles); vwap.setData(r.vwap_series.filter((p) => p.time >= r.candles[0].time));
  lines.forEach((l) => candles.removePriceLine(l)); lines = [];
  const c = r.context;
  pl(c.or_high, css("--muted"), "OR high", 3); pl(c.or_low, css("--muted"), "OR low", 3);
  pl(c.prev_high, css("--down"), "PDH", 2); pl(c.prev_low, css("--up"), "PDL", 2);
  pl(c.day_high, css("--muted"), "Day H", 1); pl(c.day_low, css("--muted"), "Day L", 1);
  const shown = r.calls.filter((x) => x.open).concat(r.calls.length ? [] : r.preview.map((p) => ({ call: p.call })));
  shown.forEach((x) => {
    const k = x.call;
    pl(k.u_entry, css("--accent"), `${k.option_type} ENTRY`, 0, 2);
    pl(x.u_stop ?? k.u_stop, css("--down"), "STOP", 0, 2);
    k.u_targets.forEach((t, i) => pl(t, css("--up"), `T${i + 1}`, 0, 2));
  });
  if (range) chart.timeScale().setVisibleLogicalRange(range); else chart.timeScale().fitContent();
}

function drawMarket(r) {
  const c = r.context, box = $("market"); box.replaceChildren();
  box.append(el("h2", {}, `${r.underlying}  ${fmt(c.spot)}`));
  const rows = [["Session", r.clock.market_open ? "LIVE" : "Closed (last bar " + r.clock.last_bar.slice(5, 16) + ")"], ["Expiry", `${r.expiry}  ·  lot ${r.lot_size}`], ["India VIX", fmt(r.vix)],
    ["Expected day move (1σ)", c.expected_move ? "± " + fmt(c.expected_move, 0) + " pts" : "–"], ["15m ATR", fmt(c.atr15, 1)],
    ["VWAP" + (c.vwap_volume_weighted ? "" : " (equal-weight)"), fmt(c.vwap)], ["Opening range", c.or_high ? `${fmt(c.or_low, 0)} – ${fmt(c.or_high, 0)}` : "forming"],
    ["Prev day H / L", `${fmt(c.prev_high, 0)} / ${fmt(c.prev_low, 0)}`], ["Gap", c.gap_pct + "%"], ["Trend (5m)", c.trend], ["Daily bias", c.daily_bias],
    ["Bias score", (c.bias_score >= 0 ? "+" : "") + c.bias_score], ["RSI", c.rsi], ["Today's result", (r.day_r >= 0 ? "+" : "") + r.day_r + "R"], ["Premium source", r.chain_source === "nse" ? "NSE live chain" : "Model (VIX)"]];
  if (r.chain.pcr != null) rows.push(["PCR", r.chain.pcr], ["Max pain", r.chain.max_pain], ["OI walls (put / call)", `${r.chain.put_wall} / ${r.chain.call_wall}`]);
  const dl = el("dl", { class: "kv" }); rows.forEach(([k, v]) => dl.append(el("dt", {}, k), el("dd", {}, v))); box.append(dl);
  if (c.patterns.length) box.append(el("p", { class: "muted" }, "5m patterns: " + c.patterns.map((p) => `${p.name} (${p.status})`).join(", ")));
  $("banner").className = r.clock.market_open ? "" : "closed";
  $("banner").textContent = r.clock.market_open ? "" : "Market closed: showing a plan for the next session built from the last session. Live tracking starts when the market opens.";
}

function callCard(x, preview) {
  const k = x.call, long = k.side === "LONG";
  const status = x.status || "PREVIEW";
  const card = el("div", { class: "call" + (x.open ? " live" : "") },
    el("div", {}, el("span", { class: "badge sm " + (long ? "LONG" : "SHORT") }, `BUY ${k.option_type}`), el("b", {}, "  " + k.symbol), "  ", el("span", { class: "badge sm " + (STATUS_CLASS[status] || "WAIT") }, status.replace("_", " "))),
    el("div", { class: "muted" }, `${k.setup} · confidence ${k.confidence}%${k.aligned ? "" : " · counter-bias"}`),
    el("div", { class: "grid4" }, ...[["Buy at", `₹${fmt(k.entry_premium)}`], ["Stop-loss", `₹${fmt(k.stop_premium)}`], ["Target 1", `₹${fmt(k.target_premiums[0])} (${k.rr[0]}R)`], ["Target 2", `₹${fmt(k.target_premiums[1])} (${k.rr[1]}R)`]].map(([a, b]) => el("span", {}, el("small", {}, a), b))),
    el("small", { class: "muted" }, `${k.mode === "market" ? "Enter now" : k.mode === "stop" ? "Enter when " + r_und + " crosses " + fmt(k.u_entry, 1) : "Enter on pullback to " + fmt(k.u_entry, 1)} · ${r_und} stop ${fmt(x.u_stop ?? k.u_stop, 1)} · targets ${k.u_targets.map((t) => fmt(t, 1)).join(" / ")}`),
    el("small", { class: "muted" }, `${k.lots} lot × ${k.lot_size} = ${k.qty} qty · cost ${money(k.cost)} · max loss ${money(k.max_loss)} · Δ ${k.delta}`));
  if (x.open && x.mark_premium != null) card.append(el("small", {}, `Live mark ≈ ₹${fmt(x.mark_premium)} (${money((x.mark_premium - k.entry_premium) * k.qty)} vs model entry)`));
  if (!x.open && x.pnl != null) card.append(el("small", { class: x.pnl >= 0 ? "up" : "down" }, `Closed: ${x.exit_reason} · net ${money(x.pnl)} (${x.r_multiple >= 0 ? "+" : ""}${x.r_multiple}R)`));
  k.rationale.forEach((t) => card.append(el("small", { class: "muted" }, "• " + t)));
  k.warnings.forEach((t) => card.append(el("small", { class: "warnl" }, "! " + t)));
  const det = el("details", {}, el("summary", {}, "Exit plan")); k.exit_plan.forEach((t) => det.append(el("small", { class: "muted" }, "• " + t))); card.append(det);
  return card;
}
let r_und = "";

function drawCalls(r) {
  r_und = r.underlying;
  const box = $("calls"); box.replaceChildren();
  const open = r.calls.filter((x) => x.open), done = r.calls.filter((x) => !x.open);
  box.append(el("h2", {}, r.clock.market_open ? "Trade calls (live)" : "Plan for next session"));
  if (r.clock.market_open) {
    box.append(el("p", { class: "muted" }, `Entries ${r.rules.entries}, max ${r.rules.max_calls_per_day} calls/day, stop for the day at ${r.rules.stop_for_day_at_r}R, square-off ${r.rules.square_off}.`));
    if (!open.length) box.append(el("p", {}, r.day_r <= r.rules.stop_for_day_at_r ? "Daily loss limit reached: no new calls today." : "No active call. Watching for setups…"));
    open.forEach((x) => box.append(callCard(x)));
    if (done.length) { box.append(el("h3", {}, "Closed today")); done.forEach((x) => box.append(callCard(x))); }
  } else {
    if (!r.preview.length) box.append(el("p", { class: "muted" }, "No clean setup from the last session. Wait for the opening range after 09:30."));
    r.preview.forEach((x) => box.append(callCard(x, true)));
    box.append(el("p", { class: "muted" }, "Conditional levels only: re-check at the open, since gaps change everything."));
    if (r.calls.length) { box.append(el("h3", {}, "Last session: what these rules would have done (replay)")); r.calls.forEach((x) => box.append(callCard(x))); }
  }
}

function drawEvents(r) {
  const box = $("events"); box.replaceChildren();
  if (!r.events.length) box.append(el("p", { class: "muted" }, "No events yet."));
  [...r.events].reverse().forEach((e) => box.append(el("div", { class: "item" }, el("b", { class: e.kind === "exit" ? "down" : e.kind === "target" || e.kind === "entry" ? "up" : "" }, e.ts.slice(11, 16)), "  ", e.msg)));
  const fresh = r.events.filter((e) => !seen.has(e.ts + e.msg + e.id));
  r.events.forEach((e) => seen.add(e.ts + e.msg + e.id));
  if (loaded && fresh.length && $("notify").checked) {
    fresh.forEach((e) => { try { new Notification("ChartScope " + r.underlying, { body: e.msg }); } catch (_) {} });
    document.title = "● " + fresh[fresh.length - 1].msg.slice(0, 40);
  }
}

async function run() {
  const my = ++seq;
  const q = new URLSearchParams({ underlying: $("und").value, capital: $("capital").value, risk_pct: $("risk").value });
  $("status").className = ""; $("status").textContent = "Loading…";
  try {
    const res = await fetch("/api/options/live?" + q); const body = await res.json();
    if (my !== seq) return;
    if (!res.ok) throw new Error(Array.isArray(body.detail) ? body.detail.map((d) => d.msg).join("; ") : body.detail || res.statusText);
    drawChart(body); drawMarket(body); drawCalls(body); drawEvents(body); first = false; loaded = true;
    $("status").textContent = `${body.underlying} · ${body.clock.market_open ? "LIVE" : "closed"} · updated ${new Date().toLocaleTimeString()}`;
  } catch (e) { if (my === seq) { $("status").className = "err"; $("status").textContent = String(e.message || e); } }
}

function drawBt(b) {
  const box = $("bt"); box.replaceChildren();
  const s = b.summary;
  if (!s.n) { box.append(el("p", { class: "muted" }, "No trades in this period.")); return; }
  box.append(el("p", {}, `${b.underlying}, ${b.days} sessions (${b.from} → ${b.to}): ${s.n} trades, win rate ${(s.win_rate * 100).toFixed(0)}%, average ${s.avg_r >= 0 ? "+" : ""}${s.avg_r}R, profit factor ${s.profit_factor ?? "–"}, net ${money(s.total_pnl)} (gross ${money(s.gross_pnl)} − costs ${money(s.costs)}), max drawdown ${money(s.max_drawdown)}.`));
  const t = el("table", {}, el("thead", {}, el("tr", {}, ...["Setup", "Trades", "Win", "Avg R", "Net"].map((h) => el("th", {}, h)))), el("tbody", {}));
  Object.entries(b.by_setup).sort((a, c) => c[1].n - a[1].n).forEach(([k, v]) => t.tBodies[0].append(el("tr", {}, el("td", {}, k), el("td", {}, v.n), el("td", {}, (v.win_rate * 100).toFixed(0) + "%"), el("td", { class: v.avg_r >= 0 ? "up" : "down" }, (v.avg_r >= 0 ? "+" : "") + v.avg_r), el("td", {}, money(v.total_pnl)))));
  box.append(el("div", { class: "table-wrap" }, t), el("p", { class: "muted" }, b.caveat));
}

$("runbt").addEventListener("click", async () => {
  $("bt").replaceChildren(el("p", { class: "muted" }, "Replaying sessions… (about 30 seconds)"));
  try {
    const q = new URLSearchParams({ underlying: $("und").value, capital: $("capital").value, risk_pct: $("risk").value });
    const res = await fetch("/api/options/backtest?" + q); const b = await res.json();
    if (!res.ok) throw new Error(b.detail || res.statusText);
    drawBt(b);
  } catch (e) { $("bt").replaceChildren(el("p", { class: "down" }, String(e.message || e))); }
});
function schedule() { clearInterval(timer); if ($("live").checked) timer = setInterval(run, 15000); }
$("controls").addEventListener("submit", (e) => { e.preventDefault(); first = true; seen.clear(); loaded = false; run(); schedule(); });
$("und").addEventListener("change", () => $("controls").requestSubmit());
$("live").addEventListener("change", schedule);
$("notify").addEventListener("change", () => { if ($("notify").checked && "Notification" in window) Notification.requestPermission(); });
run(); schedule();

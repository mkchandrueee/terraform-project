"use strict";
const $ = (id) => document.getElementById(id);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v; else n.setAttribute(k, v);
  }
  for (const k of kids) n.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return n;
}

const chartOpts = () => ({
  layout: { background: { color: css("--card") }, textColor: css("--muted") },
  grid: { vertLines: { color: css("--line") }, horzLines: { color: css("--line") } },
  rightPriceScale: { borderColor: css("--line") },
  timeScale: { borderColor: css("--line"), timeVisible: true, secondsVisible: false },
  crosshair: { mode: 0 },
});

const chart = LightweightCharts.createChart($("chart"), chartOpts());
const candles = chart.addCandlestickSeries({ upColor: css("--up"), downColor: css("--down"), borderVisible: false, wickUpColor: css("--up"), wickDownColor: css("--down") });
let priceLines = [], callLines = [], overlaySeries = [], first = true, timer = null, seq = 0;

const aChart = LightweightCharts.createChart($("analog-chart"), { ...chartOpts(), timeScale: { visible: false } });
let aSeries = [];

new ResizeObserver(() => {
  chart.applyOptions({ width: $("chart").clientWidth, height: $("chart").clientHeight });
  aChart.applyOptions({ width: $("analog-chart").clientWidth, height: $("analog-chart").clientHeight });
}).observe(document.body);

const fmt = (x, d = 2) => (x == null ? "–" : Number(x).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }));
const pct = (x) => (x * 100).toFixed(0) + "%";
const cls = (b) => (b === "bullish" ? "up" : b === "bearish" ? "down" : "muted");

function line(price, color, title, style = 2, width = 1) {
  priceLines.push(candles.createPriceLine({ price, color, lineWidth: width, lineStyle: style, axisLabelVisible: true, title }));
}

function showCall(c) {
  callLines.forEach((l) => candles.removePriceLine(l)); callLines = [];
  if (!c) return;
  const add = (price, color, title) => callLines.push(candles.createPriceLine({ price, color, lineWidth: 2, lineStyle: 0, axisLabelVisible: true, title }));
  add(c.entry, css("--accent"), "C-ENTRY"); add(c.stop, css("--down"), "C-STOP");
  c.targets.forEach((t, i) => add(t, css("--up"), `C-T${i + 1}`));
}

function drawCalls(r) {
  const box = $("calls"); box.replaceChildren(); showCall(null);
  const c = r.calls;
  box.append(el("h2", {}, "Trade calls"));
  box.append(el("p", { class: "muted" }, `Daily bias: ${c.daily_bias}. ${c.delivery_view}`));
  const section = (title, list, empty) => {
    box.append(el("h3", {}, title));
    if (!list.length) box.append(el("p", { class: "muted" }, empty));
    list.forEach((x) => {
      const d = el("div", { class: "call", tabindex: "0" },
        el("div", {}, el("span", { class: "badge sm " + (x.side === "BUY" ? "LONG" : "SHORT") }, x.side), el("b", {}, "  " + x.name), x.with_trend ? "" : el("span", { class: "muted" }, "  · counter-trend")),
        el("div", { class: "grid4" }, ...[["Entry", fmt(x.entry)], ["Stop", fmt(x.stop)], ["T1", `${fmt(x.targets[0])} (${x.rr[0]}R)`], ["T2", `${fmt(x.targets[1])} (${x.rr[1]}R)`]].map(([k, v]) => el("span", {}, el("small", {}, k), v))),
        el("small", { class: "muted" }, `${x.entry_type} · qty ${x.qty} (≈ ${fmt(x.position_value, 0)}) · risk ${fmt(x.risk_amount, 0)}`),
        el("small", {}, x.when), ...x.notes.map((n) => el("small", { class: "muted" }, "• " + n)));
      d.addEventListener("click", () => { const on = d.classList.toggle("sel"); box.querySelectorAll(".call").forEach((o) => o !== d && o.classList.remove("sel")); showCall(on ? x : null); });
      box.append(d);
    });
  };
  section("Delivery (positional)", c.delivery, "No delivery entry right now.");
  section(`Intraday (${c.intraday_interval || "n/a"} chart)`, c.intraday, "No intraday setup with acceptable reward:risk.");
  c.notes.forEach((n) => box.append(el("p", { class: "muted" }, n)));
  box.append(el("p", { class: "muted" }, "Click a call to plot it on the chart."));
}

function drawChart(r) {
  const range = first ? null : chart.timeScale().getVisibleLogicalRange();
  candles.setData(r.candles);
  priceLines.forEach((l) => candles.removePriceLine(l)); priceLines = [];
  overlaySeries.forEach((s) => chart.removeSeries(s)); overlaySeries = [];

  for (const lv of r.levels) {
    line(lv.price, lv.kind === "support" ? css("--up") : css("--down"), `${lv.kind === "support" ? "S" : "R"} ${lv.strength}`, 2, lv.strength >= 60 ? 2 : 1);
  }
  const p = r.plan;
  if (p.action !== "WAIT") {
    line(p.entry, css("--accent"), "ENTRY", 0, 2);
    line(p.stop, css("--down"), "STOP", 0, 2);
    p.targets.forEach((t, i) => line(t, css("--up"), `T${i + 1}`, 0, 2));
  }

  const markers = [];
  for (const pat of r.patterns) {
    for (const ln of pat.lines) {
      if (ln.length < 2 || ln[0].time >= ln[1].time) continue;
      const s = chart.addLineSeries({ color: css(pat.bias === "bullish" ? "--up" : pat.bias === "bearish" ? "--down" : "--accent"), lineWidth: 2, lineStyle: 0, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
      s.setData(ln); overlaySeries.push(s);
    }
    pat.points.filter((q) => q.visible).forEach((q, n) => markers.push({ time: q.time, position: pat.bias === "bullish" ? "belowBar" : "aboveBar", color: css(pat.bias === "bullish" ? "--up" : pat.bias === "bearish" ? "--down" : "--accent"), shape: pat.bias === "bullish" ? "arrowUp" : pat.bias === "bearish" ? "arrowDown" : "circle", text: n === 0 ? pat.name : "" }));
  }
  const seen = new Set();
  candles.setMarkers(markers.sort((a, b) => a.time - b.time).filter((m) => { const k = m.time + m.shape; return seen.has(k) ? false : (seen.add(k), true); }).slice(-30));
  if (range) chart.timeScale().setVisibleLogicalRange(range); else chart.timeScale().fitContent();
}

function drawLegend() {
  const items = [["--up", "Support / target"], ["--down", "Resistance / stop"], ["--accent", "Entry / neutral pattern"]];
  const box = $("legend"); box.replaceChildren();
  for (const [c, t] of items) box.append(el("span", {}, el("i", { class: "sw", style: `border-color:${css(c)}` }), t));
  box.append(el("span", {}, "Dashed = S/R zones (number = strength). Full-width solid = trade levels. Short bold lines = pattern necklines / trendlines."));
}

function drawPlan(r) {
  const p = r.plan, box = $("plan"); box.replaceChildren();
  box.append(el("h2", {}, "Overall signal (this timeframe)"));
  box.append(el("div", {}, el("span", { class: "badge " + p.action }, p.action), el("span", { class: "muted" }, `  ${r.resolved} @ ${fmt(r.price)}  ·  score ${p.score >= 0 ? "+" : ""}${p.score.toFixed(2)}  ·  ${p.conviction} conviction`)));
  if (p.action !== "WAIT") {
    const rows = [["Entry", fmt(p.entry)], ["Order", p.entry_type], ["Stop-loss", fmt(p.stop)], ["Target 1", `${fmt(p.targets[0])}  (${p.rr[0]}R)`], ["Target 2", `${fmt(p.targets[1])}  (${p.rr[1]}R)`], ["Risk / share", fmt(p.risk_per_share)], ["Quantity", `${p.qty} (≈ ${fmt(p.position_value, 0)})`], ["Capital at risk", fmt(p.risk_amount, 0)], ["History-implied move", p.analog_target ? fmt(p.analog_target) : "–"]];
    const dl = el("dl", { class: "kv" });
    rows.forEach(([k, v]) => dl.append(el("dt", {}, k), el("dd", {}, v)));
    box.append(dl, el("p", { class: "muted" }, p.invalidation));
  }
  const comp = el("div", {});
  for (const [k, v] of Object.entries(p.components)) {
    comp.append(el("div", { class: "muted" }, `${k} ${v >= 0 ? "+" : ""}${v.toFixed(2)}`),
      el("div", { class: "bar" }, el("i", { style: `width:${Math.round((v + 1) * 50)}%;background:${v >= 0 ? css("--up") : css("--down")}` })));
  }
  box.append(comp);
  const ul = el("ul", { class: "tight" }); p.rationale.forEach((t) => ul.append(el("li", {}, t))); box.append(ul);
  if (p.warnings.length) { const w = el("ul", { class: "tight warn" }); p.warnings.forEach((t) => w.append(el("li", {}, t))); box.append(w); }
}

function drawLists(r) {
  const pb = $("patterns"); pb.replaceChildren();
  if (!r.patterns.length) pb.append(el("p", { class: "muted" }, "No clear pattern on the latest bars."));
  r.patterns.forEach((x) => pb.append(el("div", { class: "item" }, el("b", { class: cls(x.bias) }, x.name), `  ${x.status} · ${x.confidence}%`, el("small", {}, x.description + (x.trigger ? ` Trigger ${fmt(x.trigger)}.` : "") + (x.target ? ` Target ${fmt(x.target)}.` : "")))));
  const lb = $("levels"); lb.replaceChildren();
  [...r.levels].sort((a, b) => b.price - a.price).forEach((x) => lb.append(el("div", { class: "item" }, el("b", { class: x.kind === "support" ? "up" : "down" }, `${x.kind === "support" ? "S" : "R"} ${fmt(x.price)}`), `  strength ${x.strength} · ${x.touches} touch${x.touches > 1 ? "es" : ""}`, el("small", {}, `${fmt(Math.abs(x.price - r.price) / r.atr, 1)} ATR away${x.sources.some((s) => s !== "swing") ? " · " + x.sources.filter((s) => s !== "swing").join(", ") : ""}`))));
}

function drawAnalogs(r) {
  const s = r.analog_stats, sum = $("analog-summary"); sum.replaceChildren();
  if (!s.n) { sum.append(el("p", { class: "muted" }, "Not enough history for a reliable comparison on this timeframe.")); }
  else {
    sum.append(el("span", {}, `${s.n} closest matches in ${r.bars_total.toLocaleString()} bars of history (from ${r.history_start.slice(0, 10)}): `),
      el("b", { class: s.win_rate_up >= 0.5 ? "up" : "down" }, `${pct(s.win_rate_up)} were higher after ${s.horizon} bars`),
      el("span", {}, `, median ${s.median_return_pct >= 0 ? "+" : ""}${s.median_return_pct.toFixed(2)}%, typical best/worst swing ${s.median_mfe_atr.toFixed(1)} / ${s.median_mae_atr.toFixed(1)} ATR.`));
    if (s.n_same_pattern) sum.append(el("span", {}, ` ★ ${s.n_same_pattern} showed the same chart pattern as now` + (s.win_rate_up_same_pattern != null ? ` (${pct(s.win_rate_up_same_pattern)} higher).` : ".")));
  }
  aSeries.forEach((x) => aChart.removeSeries(x)); aSeries = [];
  const mk = (path, color, width) => { const ser = aChart.addLineSeries({ color, lineWidth: width, lastValueVisible: false, priceLineVisible: false }); ser.setData(path.map((v, i) => ({ time: 1_000_000_000 + i * 60, value: v }))); aSeries.push(ser); return ser; };
  r.analogs.slice(0, 6).forEach((a) => mk(a.path, (a.fwd_return_pct >= 0 ? css("--up") : css("--down")) + "99", 1));
  const cur = mk(r.current_path, css("--text"), 3);
  const w = r.current_path.length - 1;
  cur.createPriceLine({ price: 0, color: css("--muted"), lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
  aChart.timeScale().fitContent();
  const tb = document.querySelector("#analog-table tbody"); tb.replaceChildren();
  r.analogs.forEach((a) => {
    const tr = el("tr", a.same_pattern ? { class: "same" } : {}, el("td", {}, `${a.start.slice(0, 16)} → ${a.end.slice(5, 16)}`), el("td", {}, pct(a.similarity)),
      el("td", { class: a.fwd_return_pct >= 0 ? "up" : "down" }, `${a.fwd_return_pct >= 0 ? "+" : ""}${a.fwd_return_pct.toFixed(2)}%`), el("td", {}, a.patterns.join(", ") || "–"));
    tb.append(tr);
  });
}

async function run() {
  const my = ++seq;
  const q = new URLSearchParams({ symbol: $("symbol").value.trim(), interval: $("interval").value, capital: $("capital").value, risk_pct: $("risk").value });
  $("status").className = ""; $("status").textContent = "Loading…";
  try {
    const res = await fetch("/api/analyze?" + q);
    const body = await res.json();
    if (my !== seq) return; // a newer request superseded this one
    if (!res.ok) throw new Error(Array.isArray(body.detail) ? "Invalid input: " + body.detail.map((d) => d.msg).join("; ") : body.detail || res.statusText);
    drawChart(body); drawPlan(body); drawCalls(body); drawLists(body); drawAnalogs(body); first = false;
    $("status").textContent = `${body.resolved} · last bar ${body.asof} · updated ${new Date().toLocaleTimeString()}`;
  } catch (e) {
    if (my !== seq) return;
    $("status").className = "err"; $("status").textContent = String(e.message || e);
  }
}

function schedule() { clearInterval(timer); if ($("live").checked) timer = setInterval(run, 30000); }
$("controls").addEventListener("submit", (e) => { e.preventDefault(); first = true; run(); schedule(); });
$("live").addEventListener("change", schedule);
drawLegend(); run(); schedule();

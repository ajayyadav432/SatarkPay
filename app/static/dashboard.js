// The analyst's and the stage's screen. One live connection feeds everything.
(function () {
  const { h, s, rupees, count, percent, LIKELY, KINDS, actionPill, shortVpa, tooltip, tipRow, getJSON, sendJSON } = SP;
  const $ = (id) => document.getElementById(id);
  const FEED_ROWS = 13;
  const MAX_ALERTS = 40;
  const BUCKET_MS = 2000;
  const BUCKETS = 30;
  const SERIES = [["BLOCK", "Blocked", "f-block", "bg-block"], ["HOLD", "Held", "f-hold", "bg-hold"], ["WARN", "Warned", "f-warn", "bg-warn"]];
  const NICE = { amount_unusual: "Amount unusual", drains_balance: "Drains balance", new_payee: "New payee", burst: "Many payments", odd_hour: "Unusual hour", new_device: "New phone",
    shared_device: "Shared phone", jump: "Jump in place", forwarding: "Forwarding money", young_payee: "Young account", unverified: "Unverified", fan_in: "Many payers", pass_through: "Money passes through",
    collect_blast: "Request blast", reports: "Reports", note: "The note", link: "The link", fake_vpa: "UPI ID name", sms: "Recent SMS", kind: "How it started", history: "Account history", rest: "Everything else" };

  let rows = [];
  let alerts = [];
  let selected = null;
  let following = true;
  let hindi = false;
  let attackDefs = {};
  let lastKpis = null;
  let focusVpa = null;
  let graphPinned = false;      // after launching an attack, the network stays on it until someone clicks an alert
  const buckets = Array.from({ length: BUCKETS }, () => ({ BLOCK: 0, HOLD: 0, WARN: 0 }));
  let bucketStart = Date.now();

  // --- numbers ----------------------------------------------------------------------------------

  function tile(label, value, sub) {
    return h("div", { class: "tile" }, h("div", { class: "tile-label", text: label }), h("div", { class: "tile-value", text: value }), sub ? h("div", { class: "tile-sub", text: sub }) : null);
  }

  function renderKpis(k) {
    lastKpis = k;
    $("hero-figure").textContent = rupees(k.rupees.stopped);
    $("tiles").replaceChildren(
      tile("Payments scored", count(k.scored), `${k.tps} per second`),
      tile("Time to score", k.latency_ms.p95 !== null ? `${k.latency_ms.p95} ms` : "...", "p95, on this server"),
      tile("Alerts raised", count(k.alerts), `${count(k.stopped)} stopped`),
      tile("Still recoverable", rupees(k.rupees.recoverable), "held at the mule's next hop"),
      tile("Lost anyway", rupees(k.rupees.lost), "scams that went through"));
    $("live-dot").classList.toggle("on", k.running);
    $("live-label").textContent = `${k.running ? "Live" : "Paused"} · ${k.clock_label}`;
    $("btn-run").textContent = k.running ? "Pause" : "Start";
    if ($("speed").value !== String(k.tps_target)) $("speed").value = String(k.tps_target);
    renderAttacks(k.attacks);
    renderTruth(k.truth);
    renderTypes(k.by_likely);
  }

  function renderTruth(t) {
    const line = (label, value, share, cls, note) => h("div", { class: "truth-row" },
      h("div", { class: "truth-line" }, h("span", { text: label }), h("strong", { text: value })),
      (() => { const bar = h("span"); bar.style.width = Math.min(100, share * 100) + "%"; return h("div", { class: "meter " + (cls || "") }, bar); })(),
      note ? h("div", { class: "small muted", text: note }) : null);
    const scams = t.scams || 0;
    const genuine = t.genuine || 0;
    $("truth").replaceChildren(
      line("Scam payments flagged", scams ? percent(t.flagged / scams) : "n/a", scams ? t.flagged / scams : 0, "", `${count(t.flagged)} of ${count(scams)}. Missed ${count(t.missed)}.`),
      line("Scam payments stopped before money moved", scams ? percent(t.stopped / scams) : "n/a", scams ? t.stopped / scams : 0, "", `${count(t.stopped)} of ${count(scams)}`),
      line("Genuine payments flagged by mistake", genuine ? percent(t.false_alarms / genuine, 2) : "n/a", genuine ? t.false_alarms / genuine : 0, "hold", `${count(t.false_alarms)} of ${count(genuine)}. Stopped by mistake: ${count(t.genuine_stopped)}.`));
  }

  function renderTypes(byLikely) {
    const items = Object.entries(byLikely || {}).sort((a, b) => b[1] - a[1]);
    if (!items.length) return;
    const top = items[0][1];
    $("type-bars").replaceChildren(...items.map(([key, n]) => {
      const fill = h("div", { class: "bar-fill" });
      fill.style.width = Math.max(1, (n / top) * 82) + "%";
      const row = h("div", { class: "bar-row", tabindex: "0" }, h("div", { class: "bar-label", text: LIKELY[key] || key }), h("div", { class: "bar-track" }, fill, h("span", { class: "bar-value", text: count(n) })));
      tooltip(row, () => [tipRow(count(n) + " alerts", LIKELY[key] || key)]);
      return row;
    }));
  }

  // --- attacks ----------------------------------------------------------------------------------

  function renderAttacks(list) {
    const latest = {};
    for (const a of list || []) latest[a.name] = a;
    for (const [name, def] of Object.entries(attackDefs)) {
      const slot = $("attack-result-" + name);
      if (!slot) continue;
      const a = latest[name];
      if (!a) { slot.textContent = ""; continue; }
      const first = a.first_caught_after ? `first caught at payment ${a.first_caught_after}` : "watching...";
      slot.textContent = `${a.events} payment${a.events === 1 ? "" : "s"} · ${a.flagged} flagged · ${a.stopped} stopped · ${first}`;
      def.last = a;
    }
  }

  async function launch(name, btn) {
    btn.disabled = true;
    try {
      const a = await sendJSON("/api/v1/sim/attack/" + name);
      if (a.entry) { focusVpa = a.entry; graphPinned = true; loadGraph(); }
    } catch (e) {
      $("attack-result-" + name).textContent = e.message;
    }
    setTimeout(() => { btn.disabled = false; }, 800);
  }

  function renderAttackCards() {
    $("attacks").replaceChildren(...Object.entries(attackDefs).map(([name, def]) => {
      const btn = h("button", { class: "btn btn-danger btn-small", type: "button", text: "Launch", "data-attack": name });
      btn.addEventListener("click", () => launch(name, btn));
      return h("div", { class: "attack" }, h("div", { class: "attack-title", text: def.title }), h("div", { class: "attack-detail", text: def.detail }),
        h("div", {}, btn), h("div", { class: "attack-result", id: "attack-result-" + name, "aria-live": "polite" }));
    }));
  }

  // --- the feed ---------------------------------------------------------------------------------

  function renderFeed() {
    $("feed").replaceChildren(...rows.slice(-FEED_ROWS).reverse().map((r) => {
      const cls = r.action === "BLOCK" || r.action === "HOLD" ? "row-alert" : r.action === "WARN" ? "row-warn" : (r.source !== "stream" ? "row-phone" : null);
      return h("tr", { class: cls }, h("td", { class: "small muted", text: r.time.split(", ")[1] }), h("td", { class: "vpa", text: shortVpa(r.payer) }), h("td", { class: "vpa", text: shortVpa(r.payee) }),
        h("td", { class: "right", text: rupees(r.amount) }), h("td", { class: "small", text: KINDS[r.kind] || r.kind }), h("td", { class: "right", text: r.score }), h("td", {}, actionPill(r.action)));
    }));
  }

  // --- alerts ---------------------------------------------------------------------------------------

  function renderAlertList() {
    if (!alerts.length) return;
    $("alert-list").replaceChildren(...alerts.slice(0, MAX_ALERTS).map((a) => {
      const btn = h("button", { class: "alert-item" + (selected && selected.id === a.id ? " selected" : ""), type: "button" },
        h("div", { class: "alert-line" }, actionPill(a.action), h("span", { text: `${a.score} · ${rupees(a.amount)}` }), h("span", { class: "tag", text: LIKELY[a.likely] || "" })),
        h("div", { class: "alert-meta", text: `${shortVpa(a.payer)} → ${shortVpa(a.payee)}` }));
      btn.addEventListener("click", () => { following = false; graphPinned = false; $("btn-follow").classList.remove("hidden"); select(a); });
      return btn;
    }));
  }

  function select(a) {
    selected = a;
    if (!graphPinned) focusVpa = a.likely === "forward" ? a.payer : a.payee;
    renderDetail();
    renderAlertList();
    loadGraph();
  }

  function shapChart(shap) {
    if (!shap) return null;
    const items = [...shap.items];
    if (Math.abs(shap.rest) > 0.01) items.push({ group: "rest", shap: shap.rest });
    const top = Math.max(0.5, ...items.map((i) => Math.abs(i.shap)));
    return h("div", {},
      h("div", { class: "legend" }, h("span", { class: "legend-item" }, h("span", { class: "swatch bg-up" }), "Raises the risk (+)"), h("span", { class: "legend-item" }, h("span", { class: "swatch bg-down" }), "Lowers the risk (−)")),
      items.map((i) => {
        const width = (Math.abs(i.shap) / top) * 34;
        const bar = h("div", { class: "shap-bar " + (i.shap >= 0 ? "up" : "down") });
        bar.style.width = width + "%";
        bar.style.left = i.shap >= 0 ? "50%" : 50 - width + "%";
        const label = (i.shap >= 0 ? "+" : "−") + Math.abs(i.shap).toFixed(2);
        const num = h("span", { class: "shap-num", text: label });
        if (i.shap >= 0) num.style.left = 50 + width + 1 + "%"; else num.style.right = 50 + width + 1 + "%";
        const row = h("div", { class: "shap-row", tabindex: "0" }, h("div", { class: "bar-label", text: NICE[i.group] || i.group }), h("div", { class: "shap-axis" }, h("div", { class: "shap-zero" }), bar, num));
        tooltip(row, () => [tipRow(label, (NICE[i.group] || i.group) + " (log-odds)")]);
        return row;
      }),
      h("p", { class: "small muted", text: `Base ${shap.base} + these contributions = ${shap.output}, exactly the model's output (TreeSHAP).` }));
  }

  function renderDetail() {
    const a = selected;
    const box = $("detail");
    if (!a) { box.classList.add("hidden"); return; }
    box.classList.remove("hidden");
    const langBtn = (label, on) => h("button", { type: "button", "aria-pressed": hindi === on ? "true" : "false", text: label, onclick: () => { hindi = on; renderDetail(); } });
    const mark = (status) => async () => {
      try {
        const out = await sendJSON("/api/v1/alerts/" + a.id, { status }, "PATCH");
        a.status = out.status;
        a.reports = out.reports;
        renderDetail();
      } catch (e) { box.append(h("p", { class: "error", text: e.message })); }
    };
    const m = a.model || {};
    box.replaceChildren(
      h("div", { class: "card-head" }, h("h2", { text: "Why this alert" }), h("div", { class: "lang-switch" }, langBtn("English", false), langBtn("हिंदी", true))),
      h("div", { class: "detail-head" }, h("div", { class: "score-big", text: a.score }), h("div", {}, actionPill(a.action, hindi), h("div", { class: "small muted", text: `${a.level} · ${rupees(a.amount)} · ${KINDS[a.kind] || a.kind}` })),
        h("div", { class: "vpa small", text: `${a.payer} → ${a.payee}` })),
      h("p", { class: "alert-line", text: hindi ? a.headline_hi : a.headline_en }),
      h("p", { class: a.note ? "small muted" : "hidden" }, "Note on the payment: ", h("span", { text: a.note })),
      h("ul", { class: "reasons" }, (a.reasons || []).map((r) => h("li", {}, h("span", { text: hindi ? r.text_hi : r.text_en })))),
      h("div", { class: "small muted", text: `XGBoost ${percent(m.xgb_probability, 1)} · unusual at the ${(100 * (m.anomaly_percentile || 0)).toFixed(1)}th percentile · hard rules ${percent(m.rule_weight)} · layers agreeing ${m.layers_agreeing}` }),
      h("details", { class: "table-view", open: true }, h("summary", { text: "The model's exact reasoning (SHAP)" }), shapChart(a.shap)),
      h("div", { class: "controls" },
        h("button", { class: "btn btn-small" + (a.status === "confirmed_fraud" ? " btn-danger" : ""), type: "button", text: a.status === "confirmed_fraud" ? "Confirmed scam" : "Confirm scam", onclick: mark("confirmed_fraud") }),
        h("button", { class: "btn btn-small", type: "button", text: a.status === "false_alarm" ? "Marked false alarm" : "False alarm", onclick: mark("false_alarm") }),
        a.reports ? h("span", { class: "small muted", text: `${a.reports} report${a.reports === 1 ? "" : "s"} on this account` }) : null,
        h("span", { class: "small muted", text: "Your decision becomes a label for the next training." })));
  }

  // --- flagged payments over time -----------------------------------------------------------------------

  function roll() {
    const now = Date.now();
    while (now - bucketStart >= BUCKET_MS) {
      buckets.shift();
      buckets.push({ BLOCK: 0, HOLD: 0, WARN: 0 });
      bucketStart += BUCKET_MS;
    }
  }

  function renderTimeChart() {
    roll();
    const W = 560, H = 170, L = 34, B = 18, T = 6;
    const plotW = W - L - 4, plotH = H - B - T;
    const totals = buckets.map((b) => b.BLOCK + b.HOLD + b.WARN);
    const peak = Math.max(4, ...totals);
    const step = peak <= 5 ? 1 : peak <= 12 ? 2 : peak <= 30 ? 5 : peak <= 60 ? 10 : 25;
    const top = Math.ceil(peak / step) * step;
    const y = (v) => T + plotH - (v / top) * plotH;
    const svg = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Flagged payments per 2 seconds over the last minute. Latest: ${totals[totals.length - 1]}.` });
    for (let v = 0; v <= top; v += step) {
      svg.append(s("line", { class: v === 0 ? "axis-line" : "grid-line", x1: L, x2: W - 4, y1: y(v), y2: y(v) }), s("text", { class: "axis-text", x: L - 6, y: y(v) + 3.5, "text-anchor": "end", text: v }));
    }
    const band = plotW / BUCKETS;
    const barW = Math.min(14, band - 3);
    buckets.forEach((b, i) => {
      const x = L + i * band + (band - barW) / 2;
      const group = s("g", { class: "col-group" });
      let base = 0;
      const present = SERIES.filter(([key]) => b[key] > 0);
      present.forEach(([key, , cls], idx) => {
        const top1 = y(base + b[key]);
        const bottom = y(base);
        const gap = idx > 0 ? 2 : 0;       // 2px surface gap between stacked segments
        const height = Math.max(1, bottom - top1 - gap);
        const isTop = idx === present.length - 1;
        const r = isTop ? Math.min(4, barW / 2, height) : 0;
        const yy = top1;
        const d = `M${x},${yy + height}V${yy + r}${r ? `Q${x},${yy} ${x + r},${yy}` : ""}H${x + barW - r}${r ? `Q${x + barW},${yy} ${x + barW},${yy + r}` : ""}V${yy + height}Z`;
        group.append(s("path", { class: cls, d }));
        base += b[key];
      });
      svg.append(group);
      if (totals[i] > 0) {
        const hit = s("rect", { class: "hit", x: L + i * band, y: T, width: band, height: plotH, tabindex: "0" });
        tooltip(hit, () => [tipRow(String(totals[i]), `flagged, ${(BUCKETS - 1 - i) * 2} s ago`), ...SERIES.map(([key, label]) => tipRow(String(b[key]), label))]);
        svg.append(hit);
      }
    });
    svg.append(s("text", { class: "axis-text", x: W - 4, y: H - 4, "text-anchor": "end", text: "now" }), s("text", { class: "axis-text", x: L, y: H - 4, text: "60 s ago" }));
    $("time-chart").replaceChildren(svg);
    const recent = buckets.map((b, i) => ({ b, i })).filter((x) => totals[x.i] > 0).slice(-8).reverse();
    $("time-table").replaceChildren(h("table", {}, h("thead", {}, h("tr", {}, h("th", { text: "Seconds ago" }), ...SERIES.map(([, label]) => h("th", { class: "right", text: label })))),
      h("tbody", {}, recent.map(({ b, i }) => h("tr", {}, h("td", { text: (BUCKETS - 1 - i) * 2 }), ...SERIES.map(([key]) => h("td", { class: "right", text: b[key] }))))) ));
  }

  // --- the money network --------------------------------------------------------------------------------

  async function loadGraph() {
    if (!focusVpa) return;
    try {
      renderGraph(await getJSON("/api/v1/graph?vpa=" + encodeURIComponent(focusVpa)));
    } catch (e) { /* the next refresh tries again; the old picture stays */ }
  }

  function renderGraph(g) {
    if (!g.nodes.length || !g.edges.length) {
      $("graph").replaceChildren(h("p", { class: "graph-empty", text: `Watching ${focusVpa}. Waiting for money to move.` }));
      return;
    }
    const columns = [...new Set(g.nodes.map((n) => n.column))].sort((a, b) => a - b);
    const by = {};
    for (const n of g.nodes) (by[n.column] = by[n.column] || []).push(n);
    const W = 760, top = 26, rowH = 22;
    const tallest = Math.max(...Object.values(by).map((c) => c.length));
    const H = top + Math.max(4, tallest) * rowH + 8;
    // Payers carry their labels on the left, everyone else on the right, so that edges never cross a label.
    const hasPayers = columns[0] < 0;
    const left = hasPayers ? 172 : 16;
    const right = W - 186;
    const colX = (c) => left + (columns.indexOf(c) / Math.max(1, columns.length - 1)) * (right - left);
    const pos = {};
    for (const c of columns) {
      const list = by[c];
      list.forEach((n, i) => { pos[n.id] = { x: colX(c), y: top + ((H - top - 8) * (i + 0.5)) / list.length }; });
    }
    const scale = Math.max(20000, ...g.edges.map((e) => e.amount + e.held));
    const svg = s("svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `Money network around ${g.focus}: ${rupees(g.total_in)} paid in, ${rupees(g.total_out)} moved on, ${rupees(g.total_held)} held.` });
    const names = { "-1": "Paid in by", 0: "This account", 1: "Next hop", 2: "Next hop", 3: "Cash-out", 4: "Cash-out" };
    for (const c of columns) svg.append(s("text", { class: "col-label", x: colX(c), y: 13, "text-anchor": c < 0 ? "end" : "start", text: names[c] || "" }));
    const heldEdges = g.edges.filter((e) => e.held > 0);
    for (const e of g.edges) {
      const a = pos[e.from], b = pos[e.to];
      if (!a || !b) continue;
      const held = e.held > 0;
      const total = e.amount + e.held;
      const mid = (a.x + b.x) / 2;
      const path = s("path", { class: "edge" + (held ? " held" : ""), d: `M${a.x},${a.y}C${mid},${a.y} ${mid},${b.y} ${b.x},${b.y}`, "stroke-width": 1 + 3 * Math.sqrt(total / scale), tabindex: "0" });
      tooltip(path, () => [tipRow(rupees(e.amount), "moved"), tipRow(rupees(e.held), "held"), tipRow(String(e.n), `payment${e.n === 1 ? "" : "s"}: ${shortVpa(e.from)} to ${shortVpa(e.to)}`)]);
      svg.append(path);
      if (held && heldEdges.length <= 3) svg.append(s("text", { class: "node-label strong", x: mid, y: Math.min(a.y, b.y) - 5, "text-anchor": "middle", text: "HELD " + rupees(e.held) }));
    }
    for (const n of g.nodes) {
      const p = pos[n.id];
      const cls = n.id === g.focus ? "node focus" : n.column > 0 ? "node suspect" : "node";
      const dot = s("circle", { class: cls, cx: p.x, cy: p.y, r: n.id === g.focus ? 8 : 6, tabindex: "0" });
      tooltip(dot, () => [tipRow(n.id, ""), tipRow(String(n.reports), "reports"), tipRow(n.merchant ? (n.verified ? "verified merchant" : "unverified merchant") : "person", "")]);
      // Labels go where no edge runs: left of a payer, above an account that pays on, and right of the last one.
      const onLeft = n.column < 0;
      const paysOn = g.edges.some((e) => e.from === n.id);
      const label = onLeft ? { x: p.x - 11, y: p.y + 3.5, anchor: "end" } : paysOn ? { x: p.x, y: p.y - 13, anchor: "middle" } : { x: p.x + 11, y: p.y + 3.5, anchor: "start" };
      svg.append(dot, s("text", { class: "node-label" + (n.id === g.focus ? " strong" : ""), x: label.x, y: label.y, "text-anchor": label.anchor, text: shortVpa(n.id) }));
    }
    const summary = `${rupees(g.total_in)} paid in · ${rupees(g.total_out)} moved on · ${rupees(g.total_held)} held` + (g.hidden_payers ? ` · ${g.hidden_payers} more payers not shown` : "");
    $("graph").replaceChildren(svg, h("p", { class: "small muted", text: summary }));
  }

  // --- the live connection -----------------------------------------------------------------------------

  function addRow(row) {
    rows.push(row);
    if (rows.length > FEED_ROWS * 3) rows = rows.slice(-FEED_ROWS * 2);
    roll();
    if (row.action !== "ALLOW") buckets[BUCKETS - 1][row.action] += 1;
  }

  function addAlert(alert) {
    alerts.unshift(alert);
    if (alerts.length > MAX_ALERTS) alerts.length = MAX_ALERTS;
    if (following && alert.action !== "WARN") select(alert);
    else if (following && !selected) select(alert);
  }

  function connect() {
    const es = new EventSource("/api/v1/stream");
    es.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.kpis) renderKpis(msg.kpis);
      if (msg.items && msg.items.length) {
        for (const item of msg.items) {
          if (item.type !== "txn") continue;
          addRow(item.row);
          if (item.alert) addAlert(item.alert);
        }
        renderFeed();
        renderAlertList();
      }
    };
    es.onerror = () => { $("live-label").textContent = "Reconnecting..."; $("live-dot").classList.remove("on"); };
  }

  // --- start ---------------------------------------------------------------------------------------------

  async function init() {
    $("top").replaceWith(SP.topbar("/"));
    SERIES.forEach(([, label, , bg]) => $("time-legend").append(h("span", { class: "legend-item" }, h("span", { class: "swatch " + bg }), label)));
    [5, 10, 25, 50, 100, 250, 500].forEach((v) => $("speed").append(h("option", { value: v, text: v + " per second" })));
    $("speed").addEventListener("change", () => sendJSON("/api/v1/sim/speed", { tps: Number($("speed").value) }).catch(() => {}));
    $("btn-run").addEventListener("click", () => sendJSON(lastKpis && lastKpis.running ? "/api/v1/sim/stop" : "/api/v1/sim/start").catch((e) => { $("live-label").textContent = e.message; }));
    $("btn-follow").addEventListener("click", () => { following = true; $("btn-follow").classList.add("hidden"); if (alerts[0]) select(alerts[0]); });
    const demo = await getJSON("/api/v1/demo");
    attackDefs = demo.attacks;
    renderAttackCards();
    const join = await getJSON("/api/v1/join");
    $("join").replaceChildren(...(join.pay_url
      ? [h("img", { src: "/api/v1/join.svg", alt: "QR code that opens the phone screen" }), h("div", {}, h("p", { text: "Scan this with your phone on the same Wi-Fi. Play the scammer: write the note, pick the UPI ID, choose the amount. See if it gets through." }), h("p", { class: "mono small", text: join.pay_url }))]
      : [h("div", {}, h("p", { text: "Play the scammer: write the note, pick the UPI ID, choose the amount. See if it gets through." }), h("a", { class: "btn btn-primary", href: "/pay", text: "Open the phone screen" }), h("p", { class: "small muted", text: "Start with ./run.sh wifi and a QR code appears here, so phones on the same Wi-Fi can join." }))]));
    const feed = await getJSON("/api/v1/feed?limit=" + FEED_ROWS);
    rows = feed.rows;
    renderFeed();
    const old = await getJSON("/api/v1/alerts?limit=" + MAX_ALERTS);
    alerts = old.alerts;
    renderAlertList();
    if (alerts[0]) select(alerts[0]);
    renderTimeChart();
    setInterval(renderTimeChart, 1000);
    setInterval(loadGraph, 2000);
    document.addEventListener("themechange", renderTimeChart);
    connect();
  }

  init();
})();

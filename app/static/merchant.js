// The small merchant's screen: what really arrived, and a warning when it did not.
(function () {
  const { h, rupees, percent, getJSON, sendJSON, actionPill } = SP;
  const $ = (id) => document.getElementById(id);
  let shop = null;
  const rows = [];

  function mask(vpa) {
    const [name, handle] = (vpa || "").split("@");
    return (name || "").slice(0, 3) + "***@" + (handle || "");
  }

  // Only money that really moved counts. A payment that was flagged, stopped, declined or cancelled has not arrived.
  function status(row) {
    if (row.status === "moved") return row.action === "ALLOW" ? "Received" : "Received, but it was flagged: this customer may be a victim";
    if (row.status === "pending") return "Waiting: the customer has not approved it yet. Do not hand over goods";
    if (row.status === "stopped") return "Not received: this payment was stopped";
    return "Not received: the customer did not pay";
  }

  function paint() {
    const arrived = rows.filter((r) => r.status === "moved");
    $("total").textContent = rupees(arrived.reduce((sum, r) => sum + r.amount, 0));
    $("n").textContent = arrived.length;
    $("stopped").textContent = rows.filter((r) => r.status === "stopped" || r.status === "cancelled").length;
    $("empty").classList.toggle("hidden", rows.length > 0);
    $("rows").replaceChildren(...rows.slice(0, 20).map((r) => h("tr", {}, h("td", { class: "small muted", text: r.time.split(", ")[1] }), h("td", { class: "vpa", text: mask(r.payer) }), h("td", { class: "right", text: rupees(r.amount) }),
      h("td", {}, actionPill(r.action), h("span", { class: "small", text: " " + status(r) })))));
  }

  function add(item) {
    if (item.type === "txn" && item.row.payee === shop) {
      rows.unshift(item.row);
      paint();
    } else if (item.type === "settled") {
      const row = rows.find((r) => r.txn_id === item.txn_id);
      if (row) { row.status = item.status; paint(); }
    }
  }

  async function customerPays() {
    const amount = 40 + Math.round(Math.random() * 460);
    const demo = await getJSON("/api/v1/demo?persona=rahul");
    await sendJSON("/api/v1/score", { payer: demo.me.vpa, payee: shop, amount, kind: "QR", device: demo.me.device, city: demo.me.city, record: true });
  }

  async function init() {
    $("top").replaceWith(SP.topbar("/merchant"));
    const demo = await getJSON("/api/v1/demo");
    shop = demo.shop;
    $("vpa").textContent = shop;
    $("btn-customer").addEventListener("click", () => customerPays().catch(() => {}));
    try {
      const m = await getJSON("/api/v1/metrics");
      const g = m.false_alarms_by_group.small_unverified_merchants;
      $("fa-note").textContent = `Your customers are not treated as suspects: in testing, ${percent(g.flagged, 2)} of payments to small unverified shops were flagged, and ${percent(g.stopped, 2)} were stopped. Simulated data.`;
    } catch (e) { /* the note is optional */ }
    paint();
    const es = new EventSource("/api/v1/stream/user/" + encodeURIComponent(shop));
    es.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      for (const item of msg.items || []) add(item);
    };
  }

  init();
})();

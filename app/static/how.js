// The model card. Every number comes from models/metrics.json, which the evaluation scripts write. None is typed here.
(function () {
  const { h, rupees, count, percent, tooltip, tipRow, getJSON } = SP;
  const TYPE = { fake_collect: "Fake collect request", phishing_link: "Phishing link", qr_scam: "\"Scan to receive\" QR", mule_inflow: "Payment to a mule", mule_layering: "Mule moving money on", account_takeover: "Account takeover", coached_transfer: "\"Digital arrest\" transfer" };

  function table(headers, body, rightFrom) {
    return h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, headers.map((x, i) => h("th", { class: i >= rightFrom ? "right" : null, text: x })))),
      h("tbody", {}, body.map((row) => h("tr", {}, row.map((x, i) => h("td", { class: i >= rightFrom ? "right" : null, text: x })))))));
  }

  function bar(share, cls, label, tip) {
    const fill = h("div", { class: "bar-fill " + (cls || "") });
    fill.style.width = Math.max(0.5, share * 78) + "%";
    const track = h("div", { class: "bar-track", tabindex: "0" }, fill, h("span", { class: "bar-value", text: label }));
    if (tip) tooltip(track, () => [tipRow(label, tip)]);
    return track;
  }

  function tile(label, value, sub) {
    return h("div", { class: "stat" }, h("div", { class: "stat-value", text: value }), h("div", { class: "stat-label", text: label }), sub ? h("div", { class: "small muted", text: sub }) : null);
  }

  function card(title, ...children) {
    return h("section", { class: "card" }, h("h2", { text: title }), ...children);
  }

  function render(m) {
    const d = m.data, sys = m.systems, act = m.policy.test, g = act.genuine, f = act.all_fraud;
    const at = (name, key) => sys[name].at_false_alarm_rate[key];
    const rw = m.real_world_correction;
    const parts = [];

    parts.push(h("h1", { text: "How it works, and how well" }));
    parts.push(h("div", { class: "callout" }, h("strong", { text: "Everything here is synthetic. " }), "These numbers come from a simulated UPI world that the team wrote, because real transaction data is not public. They show the system works as designed. ",
      h("strong", { text: "How it would do on real payments is unknown." })));

    parts.push(card("The result, on data nothing was tuned on",
      h("p", { text: `${count(d.test_payments)} test payments, ${count(d.test_scams)} of them scams. They are the last days of the training world plus a completely new world. ${count(d.removed_known_scammers)} payments were removed because their scammer had already appeared in training.` }),
      h("div", { class: "stat-row" },
        tile("Scam payments flagged", percent(f.flagged), `${percent(act.careful_fraud.flagged)} of careful scams`),
        tile("Scam payments stopped", percent(f.stopped), "before the money moved"),
        tile("Genuine payments flagged", percent(g.flagged, 2), `${percent(g.stopped, 2)} stopped`),
        tile("Scam money stopped", percent(act.money.stopped / act.money.fraud_total), `${rupees(act.money.stopped)} of ${rupees(act.money.fraud_total)}`))));

    parts.push(card("How the decision is made",
      h("div", { class: "formula", text: "risk = 1 - (1 - XGBoost) x (1 - Isolation Forest) x (1 - rule 1) x (1 - rule 2) ..." }),
      h("p", { text: "More evidence never lowers the risk. The risk is then placed on a 0 to 100 scale using bands measured on validation data." }),
      table(["Score", "Level", "Decision", "Set so that, on genuine validation payments, no more than"], [
        ["40+", "Medium", "Warn: the person sees why and can continue after a pause", percent(m.policy.budgets.medium, 1) + " reach it"],
        ["60+", "High", "Hold, if the amount is ₹200 or more", percent(m.policy.budgets.high, 1) + " reach it"],
        ["80+", "Critical", "Block, only if two independent layers agree or a plain fact applies", percent(m.policy.budgets.critical, 2) + " reach it"]], 9),
      h("p", { class: "small muted", text: "A model alone can never refuse a payment." })));

    parts.push(card("Scam by scam",
      h("div", { class: "legend" }, h("span", { class: "legend-item" }, h("span", { class: "swatch bg-accent" }), "Flagged"), h("span", { class: "legend-item" }, h("span", { class: "swatch bg-gray" }), "Stopped before the money moved")),
      h("div", { class: "bars" }, Object.entries(act.by_type).map(([key, r]) => h("div", { class: "bar-row" }, h("div", { class: "bar-label", text: `${TYPE[key] || key} (${count(r.n)})` }),
        h("div", { class: "bar-pair" }, bar(r.flagged, "", percent(r.flagged), "flagged"), bar(r.stopped, "gray", percent(r.stopped), "stopped"))))),
      h("p", { class: "small muted", text: `Obvious scams flagged: ${percent(act.obvious_fraud.flagged)}. Careful scams, which try to look normal: ${percent(act.careful_fraud.flagged)}.` })));

    const layers = m.layers;
    const topRecall = Math.max(...layers.map((l) => l["recall_at_0.01"]));
    parts.push(card("What each layer adds",
      h("p", { text: "Each row retrains on more information. Recall is measured at the same budget: 1% of genuine payments flagged." }),
      h("div", { class: "bars" }, layers.map((l) => h("div", { class: "bar-row" }, h("div", { class: "bar-label", text: l.layers }), bar(l["recall_at_0.01"] / topRecall, l.layers.includes("alone") ? "gray" : "", percent(l["recall_at_0.01"]), "recall at 1% false alarms")))),
      h("details", { class: "table-view" }, h("summary", { text: "Show as a table" }), table(["Layers", "PR-AUC", "Recall at 0.1%", "Recall at 1%"], layers.map((l) => [l.layers, l.pr_auc.toFixed(3), percent(l["recall_at_0.001"]), percent(l["recall_at_0.01"])]), 1)),
      h("p", { text: "On scam types it has seen, XGBoost alone does well, and the other layers cost a little. Their value appears in the next test." })));

    parts.push(card("Scams it has never seen",
      h("p", { text: "Our test for new scams: train without any example of one scam type, then see what still catches it. The false-alarm budget is the same for both, 1%, fixed on validation data." }),
      h("div", { class: "legend" }, h("span", { class: "legend-item" }, h("span", { class: "swatch bg-accent" }), "Full system"), h("span", { class: "legend-item" }, h("span", { class: "swatch bg-gray" }), "XGBoost alone")),
      h("div", { class: "bars" }, m.leave_one_scam_out.map((r) => h("div", { class: "bar-row" }, h("div", { class: "bar-label", text: `${TYPE[r.held_out] || r.held_out} (${count(r.n_test)})` }),
        h("div", { class: "bar-pair" }, bar(r.full_system_recall, "", percent(r.full_system_recall), "full system"), bar(r.xgb_alone_recall, "gray", percent(r.xgb_alone_recall), "XGBoost alone"))))),
      h("details", { class: "table-view" }, h("summary", { text: "Show as a table" }), table(["Left out of training", "Full system", "XGBoost alone", "Anomaly model alone"], m.leave_one_scam_out.map((r) => [TYPE[r.held_out] || r.held_out, percent(r.full_system_recall), percent(r.xgb_alone_recall), percent(r.anomaly_alone_recall)]), 1))));

    const cw = m.careful_scammers_world;
    parts.push(card("If scammers get smarter",
      h("p", { text: `A separate world where ${percent(cw.stealth_share)} of scams try to look normal, instead of ${percent(d.stealth_share)}: older rented accounts, smaller amounts, neutral notes, some through verified sub-merchants. No retraining.` }),
      h("div", { class: "stat-row" }, tile("Scam payments flagged", percent(cw.actions.all_fraud.flagged)), tile("Scam payments stopped", percent(cw.actions.all_fraud.stopped)), tile("Genuine payments flagged", percent(cw.actions.genuine.flagged, 2)))));

    const groups = Object.values(m.false_alarms_by_group).sort((a, b) => b.flagged - a.flagged);
    parts.push(card("Honest people who look suspicious",
      h("p", { text: "These genuine situations were put into the simulation on purpose, because they look like fraud. This is how often they were flagged by mistake." }),
      table(["Situation", "Payments", "Flagged", "Stopped"], groups.map((x) => [x.name, count(x.n), percent(x.flagged, 2), percent(x.stopped, 2)]), 1)));

    parts.push(card("Why accuracy is the wrong number",
      h("p", { text: `Reported UPI fraud in FY25 was about ${rw.flagged.per_million.toFixed(1)} per million payments. A model that never flags anything would be 99.999% accurate and useless. This simulation has about ${Math.round(d.oversampling_factor).toLocaleString("en-IN")} times more fraud than that, so that the model has examples to learn from, which makes precision here look far better than real life would.` }),
      h("p", { text: "If real fraud were that rare and the model were this good, which is unproven, then:" }),
      table(["Decision", "False alarms per real scam", "Alerts per million payments"], [
        ["Any alert", Math.round(rw.flagged.false_alarms_per_real_fraud).toLocaleString("en-IN"), Math.round(rw.flagged.alerts_per_million_payments).toLocaleString("en-IN")],
        ["Held or blocked", Math.round(rw.stopped.false_alarms_per_real_fraud).toLocaleString("en-IN"), Math.round(rw.stopped.alerts_per_million_payments).toLocaleString("en-IN")],
        ["Blocked", rw.blocked.false_alarms_per_real_fraud === null ? "n/a" : Math.round(rw.blocked.false_alarms_per_real_fraud).toLocaleString("en-IN"), Math.round(rw.blocked.alerts_per_million_payments).toLocaleString("en-IN")]], 1),
      h("p", { class: "small muted", text: `The last row rests on ${count(Math.round(g.BLOCK * g.n))} genuine payment${Math.round(g.BLOCK * g.n) === 1 ? "" : "s"} blocked in the test, which is too few to be precise.` }),
      h("p", { text: "This is why a warning has to be cheap, a block has to be rare, and a person always has a way out. A bank would set a much tighter budget. Here is what that costs:" }),
      table(["Budget: genuine payments flagged", "Recall, full system", "Recall, XGBoost alone"], Object.keys(sys.full_system.at_false_alarm_rate).map((k) => [percent(Number(k), 2), percent(at("full_system", k).recall), percent(at("xgboost", k).recall)]), 1)));

    if (m.paysim) {
      const p = m.paysim;
      parts.push(card("The same recipe on public data",
        h("p", { text: `PaySim is a public mobile-money simulation that the team did not write (${p.source.paper}). It has no notes, links or devices, so it cannot show fake collects or phishing. It answers one question: does the recipe hold up on someone else's data? ${count(p.rows_used)} rows used, split by time.` }),
        table(["Model", "PR-AUC", "Recall at 0.1% false alarms", "Recall at 1%"], [
          ["XGBoost, with balance columns", p.with_balance_columns.pr_auc.toFixed(3), percent(p.with_balance_columns["recall_at_0.1pct"]), percent(p.with_balance_columns["recall_at_1pct"])],
          ["XGBoost, without balance columns", p.without_balance_columns.pr_auc.toFixed(3), percent(p.without_balance_columns["recall_at_0.1pct"]), percent(p.without_balance_columns["recall_at_1pct"])],
          ["Isolation Forest, no labels", p.isolation_forest_no_labels.pr_auc.toFixed(3), percent(p.isolation_forest_no_labels["recall_at_0.1pct"]), percent(p.isolation_forest_no_labels["recall_at_1pct"])]], 1),
        h("p", { text: `A shortcut we found: in ${percent(p.finding.fraud_where_amount_equals_balance, 1)} of fraud rows the amount equals the sender's whole balance, against ${percent(p.finding.genuine_where_amount_equals_balance, 4)} of genuine rows. So the near-perfect score with balance columns mostly finds that pattern, which real fraud does not follow so neatly. The number to trust is the one without them.` })));
    }

    if (m.latency) {
      const l = m.latency;
      parts.push(card("Speed, measured on this laptop",
        h("p", { text: l.note }),
        h("div", { class: "stat-row" }, tile("p50 over HTTP", l.http.p50_ms + " ms"), tile("p95 over HTTP", l.http.p95_ms + " ms"), tile("p99 over HTTP", l.http.p99_ms + " ms"), tile("Requests per second", count(Math.round(l.concurrent.per_second)), `over HTTP, ${l.concurrent.client_processes} clients at once`), tile("Scored per second", count(Math.round(l.engine.per_second)), "the stream, without HTTP"))));
    }

    parts.push(card("Known limits",
      h("ul", {}, [
        "Everything is synthetic. Accuracy on real payments is unknown. The scam patterns come from public reporting and the team's own reasoning, not from bank data.",
        "The team wrote the simulator, so the model may have learned the simulator. The hard cases, new worlds and leave-one-out test reduce this risk. They do not remove it.",
        "Payee signals such as fan-in need a view across banks, which a single bank does not have. That points to a network-level deployment, for example at the payment switch or through a shared intelligence platform. The first row of the layer table shows what is left without them.",
        "No real UPI integration. A hackathon cannot get one. /pay is a demo, and the integration point is a single API call before the payment is sent.",
        "Kafka is not built. The stream is a simple simulator, which the problem statement allows. The Bus class is where Kafka would go, and that has not been tested.",
        "SMS privacy: in this demo the laptop reads the SMS. The production design scores it on the phone and sends only the score.",
        `The "this looks like" label is a best guess from what drove the score: it named the right scam for ${percent(m.likely_type_accuracy.all)} of flagged scams in the test. The reasons are exact; the label is not.`,
      ].map((x) => h("li", { text: x })))));

    parts.push(card("Sources for the facts we quote",
      h("ul", {}, [
        ["NPCI ended P2P collect requests by 1 Oct 2025; merchant collect continues", "https://www.angelone.in/news/market-updates/npci-to-end-upi-person-to-person-collect-requests-from-october-to-curb-fraud"],
        ["UPI fraud figures, Lok Sabha, 15 Dec 2025", "https://ianslive.in/upi-frauds-worth-rs-805-crore-witnessed-this-fiscal-so-far-minister--20251215175703"],
        ["UPI volume in FY25", "https://www.business-standard.com/finance/news/upi-s-contribution-to-payments-ecosystem-volume-grows-to-83-4-in-fy25-125052900871_1.html"],
        ["Financial Fraud Risk Indicator", "https://www.medianama.com/2025/05/223-dot-financial-fraud-risk-indicator-upi/"],
      ].map(([label, url]) => h("li", {}, h("a", { href: url, rel: "noopener noreferrer", target: "_blank", text: label })))),
      h("p", { class: "small muted", text: `Numbers on this page were generated at ${m.generated_at}.` })));

    document.getElementById("how").replaceChildren(...parts);
  }

  document.getElementById("top").replaceWith(SP.topbar("/how"));
  getJSON("/api/v1/metrics").then(render).catch((e) => { document.getElementById("how").replaceChildren(h("p", { class: "error", text: "No results yet: " + e.message })); });
})();

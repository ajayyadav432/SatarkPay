// One account's own checks, with filters and downloads. The downloads use the same filters as the table.
(function () {
  const { h, getJSON, sendJSON, actionPill, rupees } = SP;
  const $ = (id) => document.getElementById(id);
  const t = () => SP_PAGES[SP.lang()];
  let me = null, q = "", action = "", kind = "", everyone = false, note = "", timer = null;

  const query = () => new URLSearchParams({ q, action, kind, limit: "1000", everyone: everyone ? "true" : "false" }).toString();

  function controls() {
    const tr = t();
    $("lang").replaceChildren(...SP.LANGS.map(([code, label]) => h("button", { type: "button", "aria-pressed": SP.lang() === code ? "true" : "false", text: label, onclick: () => { SP.setLang(code); controls(); rows(); } })));
    document.documentElement.lang = SP.lang();
    $("title").textContent = tr.historyTitle;
    $("intro").textContent = tr.historyIntro;
    $("filters").replaceChildren(
      h("input", { id: "hist-q", type: "search", value: q, maxlength: "100", placeholder: tr.search, "aria-label": tr.search, oninput: (e) => { q = e.target.value; clearTimeout(timer); timer = setTimeout(rows, 250); } }),
      h("select", { id: "hist-action", class: "select", "aria-label": tr.all, onchange: (e) => { action = e.target.value; rows(); } },
        [["", tr.all], ...Object.keys(SP.ACTIONS).map((a) => [a, SP.ACTIONS[a]["label_" + SP.lang()] || SP.ACTIONS[a].label])].map(([value, label]) => h("option", { value, selected: action === value, text: label }))),
      h("select", { id: "hist-kind", class: "select", "aria-label": tr.kind, onchange: (e) => { kind = e.target.value; rows(); } },
        [["", tr.kindAll], ["payment", tr.kindPayment], ["sms", tr.kindSms], ["email", tr.kindEmail], ["link", tr.kindLink]].map(([value, label]) => h("option", { value, selected: kind === value, text: label }))),
      me && me.role === "admin" && !me.test ? h("label", { class: "small" }, h("input", { type: "checkbox", id: "hist-all", checked: everyone, onchange: (e) => { everyone = e.target.checked; rows(); } }), " " + tr.everyone) : null,
      h("span", { class: "grow" }),
      h("a", { class: "btn btn-small", id: "export-csv", text: tr.exportCsv, download: "" }),
      h("a", { class: "btn btn-small", id: "export-json", text: tr.exportJson, download: "" }),
      h("button", { class: "btn btn-small", id: "hist-clear", type: "button", text: tr.clear, onclick: clear }));
  }

  async function clear() {
    try { await sendJSON("/api/v1/history", undefined, "DELETE"); note = t().cleared; await rows(); } catch (e) { note = e.message; paintNote(); }
  }

  function paintNote() {
    $("hist-note").textContent = note;
    $("hist-note").classList.toggle("hidden", !note);
  }

  async function rows() {
    const tr = t();
    $("export-csv").href = "/api/v1/history/export.csv?" + query().replace("limit=1000&", "");
    $("export-json").href = "/api/v1/history/export.json?" + query().replace("limit=1000&", "");
    paintNote();
    note = "";
    try {
      const { checks } = await getJSON("/api/v1/history?" + query());
      if (!checks.length) { $("hist-table").replaceChildren(h("p", { class: "muted", id: "hist-empty", text: tr.noHistory })); return; }
      $("hist-table").replaceChildren(h("table", { class: "table", id: "hist-rows" },
        h("thead", {}, h("tr", {}, [tr.when, tr.kind, tr.what2, tr.scoreWord, tr.result].map((label) => h("th", { scope: "col", text: label })))),
        h("tbody", {}, checks.map((c) => h("tr", {},
          h("td", { class: "small", text: c.when }), h("td", { class: "small", text: c.kind }),
          h("td", {}, h("div", { class: "mono small", text: c.subject }), h("div", { class: "small muted", text: [c.amount ? rupees(c.amount) : "", c.note].filter(Boolean).join(" · ") })),
          h("td", { text: c.score }), h("td", {}, actionPill(c.action, SP.lang()), c.outcome ? h("div", { class: "small muted", "data-outcome": c.outcome, text: tr.outcomes[c.outcome] || c.outcome }) : null))))));
    } catch (e) { note = e.message; paintNote(); }
  }

  $("top").replaceWith(SP.topbar("/history"));
  getJSON("/api/v1/auth/me").then((who) => { me = who; controls(); rows(); });
})();

// Small helpers shared by every screen. Text always goes in through textContent, so a scam note can never run code.
(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";

  function fill(el, attrs, children) {
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.setAttribute("class", value);
      else if (key === "text") el.textContent = value;
      else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
      else el.setAttribute(key, value === true ? "" : value);
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      el.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return el;
  }

  const h = (tag, attrs, ...children) => fill(document.createElement(tag), attrs, children);
  const s = (tag, attrs, ...children) => fill(document.createElementNS(SVG_NS, tag), attrs, children);

  function rupees(x) {
    const n = Math.round(Number(x) || 0);
    let str = String(Math.abs(n));
    if (str.length > 3) {
      let head = str.slice(0, -3);
      const parts = [];
      while (head.length > 2) { parts.unshift(head.slice(-2)); head = head.slice(0, -2); }
      if (head) parts.unshift(head);
      str = parts.join(",") + "," + str.slice(-3);
    }
    return (n < 0 ? "-" : "") + "₹" + str;
  }

  function count(x) {
    return (Number(x) || 0).toLocaleString("en-IN");
  }

  function percent(x, digits) {
    if (x === null || x === undefined) return "n/a";
    return (x * 100).toFixed(digits === undefined ? 0 : digits) + "%";
  }

  const ACTIONS = {
    ALLOW: { label: "Allowed", label_hi: "ठीक है", icon: "✓", cls: "ok" },
    WARN: { label: "Warned", label_hi: "चेतावनी", icon: "!", cls: "warn" },
    HOLD: { label: "Held", label_hi: "रोका गया", icon: "❚❚", cls: "hold" },
    BLOCK: { label: "Blocked", label_hi: "अस्वीकृत", icon: "✕", cls: "block" },
  };

  const LIKELY = {
    fake_collect: "Fake collect request", phishing: "Phishing link", qr: "\"Scan to receive\" QR", forward: "Mule moving money",
    takeover: "Account takeover", mule: "Payment to a mule", coached: "Pressure scam", unusual: "Unusual payment",
  };

  const KINDS = { PAY: "Typed", QR: "QR", LINK: "Link", COLLECT: "Collect" };

  // Status colour always comes with an icon and a word, never alone.
  function actionPill(action, hindi) {
    const m = ACTIONS[action] || ACTIONS.ALLOW;
    return h("span", { class: "pill pill-" + m.cls }, h("span", { class: "pill-icon", "aria-hidden": "true", text: m.icon }), hindi ? m.label_hi : m.label);
  }

  function shortVpa(v) {
    return v && v.length > 26 ? v.slice(0, 24) + "…" : (v || "");
  }

  function setTheme(next) {
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("satark-theme", next); } catch (e) { /* storage blocked: the choice lasts for this page */ }
  }

  function currentTheme() {
    const set = document.documentElement.getAttribute("data-theme");
    if (set) return set;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function themeButton() {
    const btn = h("button", { class: "icon-btn", type: "button", title: "Light or dark", "aria-label": "Switch between light and dark" });
    const paint = () => { btn.textContent = currentTheme() === "dark" ? "☀" : "☾"; };
    btn.addEventListener("click", () => { setTheme(currentTheme() === "dark" ? "light" : "dark"); paint(); document.dispatchEvent(new Event("themechange")); });
    paint();
    return btn;
  }

  function topbar(active) {
    const OWN = { admin: [["/", "Dashboard"], ["/pay", "Phone"], ["/merchant", "Merchant"]], user: [["/pay", "Phone"]], merchant: [["/merchant", "Merchant"]] };
    const nav = h("nav", { class: "nav", "aria-label": "Screens" });
    const account = h("div", { class: "account" });
    const paint = (me) => {
      const links = [...(me ? OWN[me.role] : []), ["/qr", "Test QR codes"], ["/how", "How it works"]];
      nav.replaceChildren(...links.map(([href, label]) =>
        h("a", { href, class: href === active ? "nav-link active" : "nav-link", "aria-current": href === active ? "page" : null, text: label })));
      account.replaceChildren(me
        ? h("button", { class: "btn btn-small", id: "btn-logout", type: "button", text: "Log out", title: me.name, onclick: () => sendJSON("/api/v1/auth/logout", {}).finally(() => { location.href = "/login"; }) })
        : h("a", { class: "btn btn-small", id: "link-login", href: "/login", text: "Log in" }));
    };
    paint(null);
    fetch("/api/v1/auth/me", { headers: { Accept: "application/json" } }).then((r) => (r.ok ? r.json() : null)).then(paint).catch(() => {});
    return h("header", { class: "topbar" },
      h("a", { class: "brand", href: "/" }, h("img", { src: "/static/logo.svg", alt: "", width: "30", height: "30" }), h("span", { text: "SatarkPay" })),
      nav, account, themeButton());
  }

  // One tooltip for the page. The value leads, the label follows. Everything it shows can also be read without it.
  let tipEl = null;
  function tooltip(target, content) {
    const show = (e) => {
      if (!tipEl) { tipEl = h("div", { class: "tip", role: "tooltip" }); document.body.append(tipEl); }
      tipEl.replaceChildren(...content());
      tipEl.classList.add("show");
      const box = tipEl.getBoundingClientRect();
      const r = target.getBoundingClientRect();
      const x = e && e.clientX !== undefined && e.type !== "focus" ? e.clientX : r.left + r.width / 2;
      const y = e && e.clientY !== undefined && e.type !== "focus" ? e.clientY : r.top;
      tipEl.style.left = Math.min(window.innerWidth - box.width - 8, Math.max(8, x + 12)) + "px";
      tipEl.style.top = Math.max(8, y - box.height - 10) + "px";
    };
    const hide = () => { if (tipEl) tipEl.classList.remove("show"); };
    target.addEventListener("pointermove", show);
    target.addEventListener("pointerleave", hide);
    target.addEventListener("focus", show);
    target.addEventListener("blur", hide);
  }

  const tipRow = (value, label) => h("div", { class: "tip-row" }, h("strong", { text: value }), h("span", { text: label }));

  async function getJSON(url) {
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    if (res.status === 401) { location.href = "/login"; throw new Error("Please log in."); }
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Request failed");
    return res.json();
  }

  async function sendJSON(url, body, method) {
    const res = await fetch(url, { method: method || "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && !url.endsWith("/auth/login")) { location.href = "/login"; throw new Error("Please log in."); }
    if (!res.ok) {
      const d = data.detail;
      throw new Error(Array.isArray(d) ? d.map((x) => (x.loc || []).slice(-1)[0] + ": " + x.msg).join("; ") : d || "Request failed");
    }
    return data;
  }

  window.SP = { h, s, rupees, count, percent, ACTIONS, LIKELY, KINDS, actionPill, shortVpa, topbar, tooltip, tipRow, getJSON, sendJSON, currentTheme };
})();

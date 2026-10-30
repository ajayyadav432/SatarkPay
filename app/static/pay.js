// The phone screen: what a person sees before their money moves. It is a demo payment app, not a real one.
(function () {
  const { h, rupees, actionPill, getJSON, sendJSON } = SP;
  const $ = (id) => document.getElementById(id);
  const NAMES = { sunita: "Sunita ji", rahul: "Rahul", priya: "Priya" };
  const PERSONA_NOTE = { sunita: "Retired teacher, Jaipur. A fictional person.", rahul: "Student, Jaipur. A fictional person.", priya: "Salaried, Bengaluru. A fictional person." };
  const T = {
    en: { balance: "Balance", ready: "Ready-made", beat: "Beat the model", payTo: "Pay to", amount: "Amount in ₹", how: "How did this start?", note: "Note on the payment", link: "Link that opened it", sms: "SMS received just before (optional)", check: "Check this payment",
      hType: { PAY: "I typed the UPI ID", QR: "I scanned a QR code", LINK: "I tapped a link", COLLECT: "A collect request came" }, beatIntro: "You are the scammer. Write anything you like. Can you get it past SatarkPay?", you: "You pay", fine: "Looks fine", payNow: "Pay", back: "Back", cancel: "Do not pay", report: "Do not pay and report it", call: "Call 1930", cyber: "cybercrime.gov.in",
      anyway: "Pay anyway", wait: (n) => `Pay anyway (wait ${n} s)`, sure: "I am sure. Continue after a pause", paid: "Paid", cancelled: "Not paid. Your money is safe.", reported: "Reported. Your money is safe.", reportedMore: (n) => `This account now has ${n} report${n === 1 ? "" : "s"}. The next person who pays it will see that.`, again: "Done", appeal: "Think this is wrong? Your bank can review it and release the payment.", held: "Held so that you can think. Your bank can also review it.",
      beatWon: "You got past it. That is a real limit. Tell the team what you did.", beatLost: "Caught. Try something more careful.", incoming: "New request", why: "Why", todo: "What to do", score: "Risk score", person: "You are", loading: "Checking..." },
    hi: { balance: "बैलेंस", ready: "तैयार उदाहरण", beat: "मॉडल को हराएँ", payTo: "किसे भुगतान", amount: "राशि ₹ में", how: "यह कैसे शुरू हुआ?", note: "भुगतान पर नोट", link: "लिंक जिससे यह खुला", sms: "इससे पहले मिला SMS (वैकल्पिक)", check: "इस भुगतान की जाँच करें",
      hType: { PAY: "मैंने UPI ID टाइप की", QR: "मैंने QR स्कैन किया", LINK: "मैंने लिंक पर टैप किया", COLLECT: "collect request आया" }, beatIntro: "आप धोखेबाज़ हैं। कुछ भी लिखें। क्या आप SatarkPay से बच पाएँगे?", you: "आप भुगतान कर रहे हैं", fine: "ठीक लग रहा है", payNow: "भुगतान करें", back: "वापस", cancel: "भुगतान न करें", report: "भुगतान न करें और शिकायत करें", call: "1930 पर कॉल करें", cyber: "cybercrime.gov.in",
      anyway: "फिर भी भुगतान करें", wait: (n) => `फिर भी भुगतान करें (${n} सेकंड रुकें)`, sure: "मुझे यकीन है। थोड़ा रुककर आगे बढ़ें", paid: "भुगतान हो गया", cancelled: "भुगतान नहीं हुआ। आपके पैसे सुरक्षित हैं।", reported: "शिकायत दर्ज। आपके पैसे सुरक्षित हैं।", reportedMore: (n) => `इस खाते पर अब ${n === 1 ? "1 शिकायत है" : n + " शिकायतें हैं"}। अगला व्यक्ति भुगतान करते समय यह देखेगा।`, again: "ठीक है", appeal: "क्या यह गलत लगता है? आपका बैंक जाँच करके भुगतान जारी कर सकता है।", held: "रोका गया ताकि आप सोच सकें। आपका बैंक भी इसकी जाँच कर सकता है।",
      beatWon: "आप बच निकले। यह एक असली कमी है। टीम को बताएँ कि आपने क्या किया।", beatLost: "पकड़े गए। कुछ और सावधानी से कोशिश करें।", incoming: "नया अनुरोध", why: "क्यों", todo: "क्या करें", score: "जोखिम स्कोर", person: "आप हैं", loading: "जाँच हो रही है..." },
  };

  for (const code of Object.keys(SP_STRINGS)) T[code] = { ...T[code], ...SP_STRINGS[code] };

  let lang = SP.lang();
  let persona = new URLSearchParams(location.search).get("persona") || "sunita";
  if (!NAMES[persona]) persona = "sunita";
  let demo = null;
  let tab = "ready";
  let view = "home";
  let last = null;
  let countdown = null;
  let stream = null;
  let beatFields = { payee: "", amount: "5000", kind: "PAY", note: "", link: "", sms: "" };
  let problem = "";
  const waiting = [];       // requests that arrived while the person was on another screen
  const seen = new Set();

  const t = () => T[lang];

  function paintLang() {
    $("lang").replaceChildren(...SP.LANGS.map(([code, label]) =>
      h("button", { type: "button", "aria-pressed": lang === code ? "true" : "false", text: label, onclick: () => { lang = code; SP.setLang(code); paintLang(); render(); } })));
  }

  function paintMe() {
    $("me-name").textContent = NAMES[persona];
    $("me-vpa").textContent = demo.me.vpa;
  }

  function clearTimer() {
    if (countdown) { clearInterval(countdown); countdown = null; }
  }

  function render() {
    clearTimer();
    if (view === "home") return renderHome();
    if (view === "review") return renderResult(last);
    if (view === "done") return renderDone(last);
    return null;
  }

  // --- home ------------------------------------------------------------------------------------

  function renderHome() {
    const tr = t();
    const who = h("select", { class: "select", "aria-label": tr.person, onchange: (e) => switchPerson(e.target.value) }, Object.keys(NAMES).map((k) => h("option", { value: k, selected: k === persona, text: NAMES[k] })));
    const tabs = h("div", { class: "tabs", role: "tablist" }, [["ready", tr.ready], ["beat", tr.beat]].map(([key, label]) =>
      h("button", { type: "button", role: "tab", "aria-selected": tab === key ? "true" : "false", text: label, onclick: () => { tab = key; render(); } })));
    $("screen").replaceChildren(
      h("div", { class: "pay-box" }, h("div", { class: "small muted", text: tr.balance }), h("div", { class: "balance", text: rupees(demo.me.balance) }), h("div", { class: "small muted", text: PERSONA_NOTE[persona] }), who),
      scanButtons(), tabs, tab === "ready" ? renderChips() : renderBeat());
  }

  // --- scanning a real QR code -------------------------------------------------------------------

  function scanButtons() {
    const tr = t();
    return h("div", { class: "scan-actions" },
      h("button", { class: "btn btn-primary", id: "btn-scan", type: "button", text: tr.scan, onclick: startCamera }),
      h("label", { class: "btn scan-photo" }, tr.photo, h("input", { type: "file", id: "scan-file", accept: "image/*", "aria-label": tr.photo, onchange: (e) => readPhoto(e.target.files[0]) })));
  }

  function readCanvas(source, width, height) {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(source, 0, 0, width, height);
    const found = jsQR(ctx.getImageData(0, 0, width, height).data, width, height);
    return found ? found.data : null;
  }

  async function readPhoto(file) {
    if (!file) return;
    try {
      const bitmap = await createImageBitmap(file);
      const scale = Math.min(1, 1400 / Math.max(bitmap.width, bitmap.height));
      const text = readCanvas(bitmap, Math.round(bitmap.width * scale), Math.round(bitmap.height * scale));
      bitmap.close();
      if (text) useQr(text); else { problem = t().noQr; render(); }
    } catch (e) { problem = t().noQr; render(); }
  }

  let camera = null;
  function stopCamera() {
    if (camera) { camera.getTracks().forEach((track) => track.stop()); camera = null; }
  }

  async function startCamera() {
    const tr = t();
    problem = "";
    if (!navigator.mediaDevices || !window.isSecureContext) { problem = tr.needHttps; render(); return; }
    try {
      camera = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
    } catch (e) { problem = tr.noCamera; render(); return; }
    const video = h("video", { class: "scan-video", id: "scan-video", autoplay: true, muted: true, playsinline: true });
    video.srcObject = camera;
    view = "scan";
    $("screen").replaceChildren(h("p", { class: "small muted", text: tr.scanHint }), video,
      h("button", { class: "btn", id: "scan-stop", type: "button", text: tr.stop, onclick: () => { stopCamera(); view = "home"; render(); } }));
    const look = () => {
      if (!camera || view !== "scan") return;
      if (video.videoWidth) {
        const scale = Math.min(1, 640 / video.videoWidth);
        const text = readCanvas(video, Math.round(video.videoWidth * scale), Math.round(video.videoHeight * scale));
        if (text) { stopCamera(); useQr(text); return; }
      }
      requestAnimationFrame(look);
    };
    look();
  }

  // A QR code is only ever read here. Nothing is paid until the person has seen the result and chosen.
  function useQr(text) {
    let url = null;
    try { url = new URL(text); } catch (e) { /* plain text, handled below */ }
    if (!url || url.protocol !== "upi:" || !url.searchParams.get("pa")) { problem = t().notUpi; view = "home"; render(); return; }
    const fields = { payee: url.searchParams.get("pa").trim().toLowerCase(), amount: url.searchParams.get("am") || "", kind: "QR", note: url.searchParams.get("tn") || "" };
    if (Number(fields.amount) > 0) { runQr(fields); return; }
    askAmount(fields);
  }

  function askAmount(fields) {
    const tr = t();
    view = "scan";
    const amount = h("input", { id: "qr-amount", type: "number", min: "1", max: "1000000", inputmode: "decimal", required: true });
    $("screen").replaceChildren(h("div", { class: "pay-box" }, h("div", { class: "small muted", text: tr.payTo }), h("div", { class: "pay-to", text: fields.payee })),
      h("p", { class: "small muted", text: tr.qrAmount }),
      h("form", { class: "chips", onsubmit: (e) => { e.preventDefault(); runQr({ ...fields, amount: amount.value }); } },
        h("label", { class: "field" }, tr.amount, amount),
        h("button", { class: "btn btn-primary", id: "qr-go", type: "submit", text: tr.check }),
        h("button", { class: "btn", type: "button", text: tr.back, onclick: () => { view = "home"; render(); } })));
  }

  async function runQr(fields) {
    problem = "";
    try { await check(txnBody(fields), { beat: false }); } catch (e) { showProblem(e); }
  }

  function renderChips() {
    return h("div", { class: "chips" }, problem ? h("p", { class: "error", id: "ready-error", text: problem }) : null, demo.scenarios.map((sc) =>
      h("button", { class: "chip", type: "button", "data-scenario": sc.id, onclick: () => runScenario(sc) }, h("span", { text: sc["title_" + lang] || sc.title }), h("small", { text: rupees(sc.amount) }))));
  }

  function renderBeat() {
    const tr = t();
    const set = (key) => (e) => { beatFields[key] = e.target.value; };
    const err = h("p", { class: problem ? "error" : "error hidden", id: "beat-error", text: problem });
    const form = h("form", { class: "chips", onsubmit: (e) => { e.preventDefault(); runBeat(); } },
      h("p", { class: "small muted", text: tr.beatIntro }),
      h("label", { class: "field" }, tr.payTo, h("input", { id: "beat-payee", value: beatFields.payee, placeholder: "name@bank", autocomplete: "off", autocapitalize: "none", spellcheck: "false", maxlength: "120", required: true, oninput: set("payee") })),
      h("label", { class: "field" }, tr.amount, h("input", { id: "beat-amount", value: beatFields.amount, inputmode: "decimal", type: "number", min: "1", max: "1000000", step: "any", required: true, oninput: set("amount") })),
      h("label", { class: "field" }, tr.how, h("select", { id: "beat-kind", onchange: (e) => { beatFields.kind = e.target.value; render(); } }, Object.entries(tr.hType).map(([k, label]) => h("option", { value: k, selected: k === beatFields.kind, text: label })))),
      h("label", { class: "field" }, tr.note, h("input", { id: "beat-note", value: beatFields.note, maxlength: "200", autocomplete: "off", oninput: set("note") })),
      beatFields.kind === "LINK" ? h("label", { class: "field" }, tr.link, h("input", { id: "beat-link", value: beatFields.link, maxlength: "2048", placeholder: "https://...", autocomplete: "off", oninput: set("link") })) : null,
      h("label", { class: "field" }, tr.sms, h("textarea", { id: "beat-sms", rows: "2", maxlength: "2000", oninput: set("sms") }, beatFields.sms)),
      err, h("button", { class: "btn btn-primary", type: "submit", id: "beat-go", text: tr.check }));
    return form;
  }

  // --- paying ----------------------------------------------------------------------------------

  function txnBody(fields) {
    const body = { payer: demo.me.vpa, payee: fields.payee, amount: Number(fields.amount), kind: fields.kind, device: demo.me.device, city: demo.me.city, balance: demo.me.balance };
    if (fields.note) body.note = fields.note;
    if (fields.link) body.link = fields.link;
    if (fields.sms) { body.sms = fields.sms; body.sms_sender = fields.sms_sender || "unknown"; }
    return body;
  }

  // The form is gone while a payment is being checked, so a problem is shown when the home screen comes back.
  function showProblem(e) {
    problem = e.message;
    view = "home";
    render();
  }

  async function runScenario(sc) {
    problem = "";
    try {
      const body = txnBody({ payee: sc.payee, amount: sc.amount, kind: sc.kind, note: sc.note, link: sc.link, sms: sc.sms, sms_sender: sc.sms_sender });
      await check(body, { sms: sc.sms, beat: false });
    } catch (e) { showProblem(e); }
  }

  async function runBeat() {
    problem = "";
    try {
      await check(txnBody({ ...beatFields, sms: beatFields.sms.trim() }), { beat: true, sms: beatFields.sms.trim() });
    } catch (e) { showProblem(e); }
  }

  async function check(body, extra) {
    $("screen").replaceChildren(h("p", { class: "muted", text: t().loading }));
    const result = await sendJSON("/api/v1/score", body);
    last = { body, result, ...extra };
    await playStages(result);
    view = "review";
    render();
  }

  // The check has already finished. This shows what each step really found, slowly enough to read, and can be skipped.
  function playStages(result) {
    const tr = t(), stages = result.stages || [];
    if (!stages.length || (window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches)) return Promise.resolve();
    view = "stages";
    return new Promise((resolve) => {
      let step = 0, timer = null;
      const bar = h("span", {});
      const track = h("div", { class: "stage-bar", role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-label": tr.checking }, bar);
      const row = (stage, i) => h("div", { class: i < step ? "stage done" : "stage", "data-stage": stage.id },
        h("span", { class: "stage-mark", "aria-hidden": "true", text: i < step ? (stage.warn ? "!" : "✓") : "·" }),
        h("span", {}, tr.stageNames[stage.id], i < step ? h("span", { class: "small", text: stage.warn ? tr.stageWarn : tr.stageOk }) : null));
      const finish = () => { clearTimeout(timer); resolve(); };
      const list = h("div", { class: "stages", id: "stages" });
      const paint = () => {
        const done = Math.round((step / stages.length) * 100);
        bar.style.width = done + "%";
        track.setAttribute("aria-valuenow", done);
        list.replaceChildren(...stages.map(row));
      };
      $("screen").replaceChildren(h("h2", { class: "section-title", text: tr.checking }),
        track, list, h("p", { class: "small muted", text: tr.slowed(Math.max(1, Math.round(result.latency_ms || 0))) }),
        h("button", { class: "btn", id: "stage-skip", type: "button", text: tr.skip, onclick: finish }));
      const next = () => {
        step += 1;
        paint();
        timer = setTimeout(step < stages.length ? next : finish, step < stages.length ? 260 : 350);
      };
      paint();
      timer = setTimeout(next, 120);
    });
  }

  function verdictClass(action) {
    return { ALLOW: "verdict-ok", WARN: "verdict-warn", HOLD: "verdict-hold", BLOCK: "verdict-block" }[action];
  }

  function renderResult(x) {
    const tr = t(), r = x.result, b = x.body;
    const box = h("div", { class: "pay-box" },
      x.incoming ? h("div", { class: "small muted", text: tr.incoming }) : h("div", { class: "small muted", text: tr.you }),
      h("div", { class: "pay-amount", text: rupees(b.amount) }), h("div", { class: "pay-to", text: b.payee }),
      b.note ? h("div", { class: "pay-note", text: b.note }) : null);
    const verdict = h("div", { class: "verdict " + verdictClass(r.action), id: "verdict", "data-action": r.action },
      h("div", { class: "verdict-head" }, actionPill(r.action, lang), h("div", {}, h("span", { class: "small muted", text: tr.score + " " }), h("span", { class: "verdict-score", id: "verdict-score", text: r.score }))),
      h("div", { class: "verdict-title", id: "verdict-title", text: r["headline_" + lang] || r.headline_en }));
    const parts = [box, verdict];
    if (r.action !== "ALLOW" && r.reasons.length) {
      parts.push(h("div", {}, h("div", { class: "small muted", text: tr.why }), h("ul", { class: "phone-reasons", id: "reasons" }, r.reasons.map((reason) => h("li", {}, h("span", { text: reason["text_" + lang] || reason.text_en }))))));
    }
    if (r.action !== "ALLOW" && r.advice.length) {
      parts.push(h("div", { class: "advice" }, h("div", { class: "small muted", text: tr.todo }), r.advice.map((a) => h("div", { text: a["text_" + lang] || a.text_en }))));
    }
    if (x.beat) parts.push(h("p", { class: r.action === "ALLOW" ? "error" : "small muted", id: "beat-verdict", text: r.action === "ALLOW" ? tr.beatWon : tr.beatLost }));
    parts.push(actionsFor(r));
    $("screen").replaceChildren(...parts);
  }

  function actionsFor(r) {
    const tr = t();
    if (r.action === "ALLOW") {
      return h("div", { class: "actions" }, h("button", { class: "btn btn-primary", id: "btn-pay", type: "button", text: `${tr.payNow} ${rupees(last.body.amount)}`, onclick: () => decide("paid") }), h("button", { class: "btn", type: "button", text: tr.back, onclick: () => decide("cancelled") }));
    }
    const report = h("button", { class: "btn btn-danger", id: "btn-report", type: "button", text: tr.report, onclick: () => decide("reported") });
    const cancel = h("button", { class: "btn", id: "btn-cancel", type: "button", text: tr.cancel, onclick: () => decide("cancelled") });
    const help = h("div", { class: "actions-2" }, h("a", { class: "btn", href: "tel:1930", text: tr.call }), h("a", { class: "btn", href: "https://cybercrime.gov.in", rel: "noopener noreferrer", target: "_blank", text: tr.cyber }));
    if (r.action === "BLOCK") {
      return h("div", { class: "actions" }, report, cancel, help, h("p", { class: "small muted", text: tr.appeal }));
    }
    // The person stays in control. A pause helps them step out of the scammer's pressure. On hold, the pause stands in for the real cooling-off time.
    const seconds = r.action === "HOLD" ? 15 : 5;
    let left = seconds;
    const anyway = h("button", { class: "btn", id: "btn-anyway", type: "button", disabled: true, text: tr.wait(left), onclick: () => decide("paid") });
    countdown = setInterval(() => {
      left -= 1;
      if (left <= 0) { clearTimer(); anyway.disabled = false; anyway.textContent = tr.anyway; } else anyway.textContent = tr.wait(left);
    }, 1000);
    return h("div", { class: "actions" }, report, cancel, help, r.action === "HOLD" ? h("p", { class: "small muted", text: tr.held }) : null, anyway);
  }

  async function decide(decision) {
    clearTimer();
    try {
      const out = await sendJSON("/api/v1/outcome", { txn_id: last.result.txn_id, token: last.result.token, decision });
      last.outcome = { decision, ...out };
      if (decision === "paid") demo.me.balance = Math.max(0, demo.me.balance - last.body.amount);
      problem = "";
      view = "done";
      render();
    } catch (e) { showProblem(e); }
  }

  function renderDone(x) {
    const tr = t(), o = x.outcome;
    const paid = o.decision === "paid";
    $("screen").replaceChildren(h("div", { class: "done", id: "done", "data-decision": o.decision },
      h("div", { class: "done-mark", "aria-hidden": "true", text: paid ? "✓" : "🛡" }),
      h("h2", { text: paid ? `${tr.paid}: ${rupees(x.body.amount)}` : (o.decision === "reported" ? tr.reported : tr.cancelled) }),
      o.decision === "reported" ? h("p", { id: "report-count", text: tr.reportedMore(o.reports) }) : null,
      paid && x.result.action !== "ALLOW" ? h("p", { class: "small muted", text: tr.call + " · " + tr.cyber }) : null),
      h("button", { class: "btn btn-primary", id: "btn-again", type: "button", text: tr.again, onclick: () => { view = "home"; render(); offerNext(); } }));
  }

  // --- a request that arrives by itself -------------------------------------------------------------

  function listen() {
    if (stream) stream.close();
    stream = new EventSource("/api/v1/stream/user/" + encodeURIComponent(demo.me.vpa));
    stream.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      for (const item of msg.items || []) {
        if (item.type === "incoming" && !seen.has(item.txn.txn_id)) {
          seen.add(item.txn.txn_id);
          waiting.push(item);
        }
      }
      offerNext();
    };
  }

  function offerNext() {
    if (view !== "home" || !waiting.length) return;
    const item = waiting.shift();
    const txn = item.txn;
    last = { body: { payer: txn.payer, payee: txn.payee, amount: txn.amount, kind: txn.kind, note: txn.note, link: txn.link }, result: { ...item.result, txn_id: txn.txn_id }, incoming: true };
    view = "review";
    render();
    if (navigator.vibrate && navigator.userActivation && navigator.userActivation.hasBeenActive) navigator.vibrate(180);
  }

  async function switchPerson(next) {
    persona = next;
    waiting.length = 0;
    seen.clear();
    await load();
  }

  async function load() {
    demo = await getJSON("/api/v1/demo?persona=" + persona);
    paintMe();
    view = "home";
    render();
    listen();
  }

  $("top").replaceWith(SP.topbar("/pay"));
  paintLang();
  load();
})();

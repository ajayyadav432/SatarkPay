// The public scam feed. Reports only warn people; blocking is left to an admin, so a group cannot get an honest shop blocked.
(function () {
  const { h, getJSON, sendJSON } = SP;
  const $ = (id) => document.getElementById(id);
  const t = () => SP_PAGES[SP.lang()];
  let me = null, sort = "new", categories = [], open = new Set(), problem = "";

  const fail = (e) => { problem = e.message; paint(); };

  async function paint() {
    const tr = t();
    document.documentElement.lang = SP.lang();
    $("lang").replaceChildren(...SP.LANGS.map(([code, label]) => h("button", { type: "button", "aria-pressed": SP.lang() === code ? "true" : "false", text: label, onclick: () => { SP.setLang(code); paint(); } })));
    $("title").textContent = tr.feedTitle;
    $("intro").textContent = tr.feedIntro;
    const data = await getJSON("/api/v1/posts?sort=" + sort);
    categories = data.categories;
    $("problem").textContent = problem;
    $("problem").classList.toggle("hidden", !problem);
    $("sort").replaceChildren(...[["new", tr.newest], ["top", tr.top]].map(([key, label]) => h("button", { type: "button", role: "tab", "aria-selected": sort === key ? "true" : "false", text: label, onclick: () => { sort = key; problem = ""; paint(); } })));
    $("compose").replaceChildren(me ? composer() : h("a", { class: "btn", href: "/login", id: "feed-login", text: tr.loginToShare }));
    const cards = await Promise.all(data.posts.map(postCard));
    $("posts").replaceChildren(...(cards.length ? cards : [h("p", { class: "muted", id: "feed-empty", text: tr.empty })]));
    if (me && me.role === "admin") await paintAdmin(); else $("admin").replaceChildren();
  }

  function composer() {
    const tr = t();
    const payee = h("input", { id: "post-payee", placeholder: "name@bank", maxlength: "100", autocomplete: "off", autocapitalize: "none" });
    const category = h("select", { id: "post-category" }, categories.map((c) => h("option", { value: c, text: c })));
    const body = h("textarea", { id: "post-body", rows: "3", minlength: "10", maxlength: "1000", required: true, placeholder: tr.what });
    return h("form", { class: "card feed-form", onsubmit: async (e) => {
      e.preventDefault();
      try { await sendJSON("/api/v1/posts", { payee: payee.value.trim(), category: category.value, body: body.value.trim() }); problem = ""; await paint(); } catch (err) { fail(err); }
    } }, h("h2", { class: "section-title", text: tr.share }),
      h("label", { class: "field" }, tr.upiOpt, payee), h("label", { class: "field" }, tr.category, category), h("label", { class: "field" }, tr.what, body),
      h("button", { class: "btn btn-primary", type: "submit", id: "post-go", text: tr.post }));
  }

  async function postCard(p) {
    const tr = t();
    const vote = (value, icon, label) => h("button", { class: "vote" + (p.my_vote === value ? " on" : ""), type: "button", "aria-label": label, title: label, "aria-pressed": p.my_vote === value ? "true" : "false", disabled: !me, text: icon,
      onclick: async () => { try { await sendJSON(`/api/v1/posts/${p.id}/vote`, { value: p.my_vote === value ? 0 : value }); await paint(); } catch (e) { fail(e); } } });
    const when = new Date(p.created * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
    const thread = open.has(p.id) ? await commentsFor(p) : null;
    return h("article", { class: "card feed-post", "data-post": p.id },
      h("div", { class: "feed-votes" }, vote(1, "▲", tr.up), h("strong", { class: "feed-score", text: p.votes }), vote(-1, "▼", tr.down)),
      h("div", { class: "feed-main" },
        h("div", { class: "small muted" }, p.sample ? h("span", { class: "pill pill-warn", title: tr.sampleNote, text: tr.sample }) : null, " ", h("span", { class: "pill", text: p.category }), ` ${p.author} · ${when}`),
        p.payee ? h("div", { class: "feed-payee" }, h("span", { class: "mono", text: p.payee }), p.reports ? h("span", { class: "pill pill-warn", text: tr.reports(p.reports) }) : null, p.blocked ? h("span", { class: "pill pill-block", text: tr.blocked }) : null) : null,
        h("p", { class: "feed-body", text: p.body }),
        h("div", { class: "feed-actions" },
          h("button", { class: "btn btn-small", type: "button", "aria-expanded": open.has(p.id) ? "true" : "false", text: `${tr.comments} (${p.comments})`, onclick: () => { if (open.has(p.id)) open.delete(p.id); else open.add(p.id); paint(); } }),
          me && me.role === "admin" ? h("button", { class: "btn btn-small", type: "button", text: tr.hide, onclick: async () => { try { await sendJSON(`/api/v1/posts/${p.id}`, undefined, "DELETE"); await paint(); } catch (e) { fail(e); } } }) : null),
        thread));
  }

  async function commentsFor(p) {
    const tr = t();
    const { comments } = await getJSON(`/api/v1/posts/${p.id}/comments`);
    const input = h("input", { maxlength: "500", required: true, "aria-label": tr.addComment, placeholder: tr.addComment });
    return h("div", { class: "feed-comments" },
      comments.map((c) => h("p", { class: "small" }, h("strong", { text: c.author + ": " }), c.body)),
      me ? h("form", { class: "feed-comment-form", onsubmit: async (e) => { e.preventDefault(); try { await sendJSON(`/api/v1/posts/${p.id}/comments`, { body: input.value.trim() }); await paint(); } catch (err) { fail(err); } } }, input, h("button", { class: "btn btn-small", type: "submit", text: tr.send })) : null);
  }

  async function paintAdmin() {
    const tr = t();
    const data = await getJSON("/api/v1/blocks");
    const blockRow = (r) => {
      const reason = h("input", { maxlength: "300", minlength: "3", required: true, "aria-label": tr.reason, placeholder: tr.reason });
      return h("form", { class: "admin-row", onsubmit: async (e) => { e.preventDefault(); try { await sendJSON("/api/v1/blocks", { payee: r.payee, reason: reason.value.trim() }); problem = ""; await paint(); } catch (err) { fail(err); } } },
        h("span", { class: "mono", text: r.payee }), h("span", { class: "pill pill-warn", text: tr.reports(r.n) }), reason, h("button", { class: "btn btn-small btn-danger", type: "submit", text: tr.block }));
    };
    $("admin").replaceChildren(h("section", { class: "card", id: "admin-panel" },
      h("h2", { class: "section-title", text: tr.adminTitle }),
      data.most_reported.length ? data.most_reported.map(blockRow) : h("p", { class: "muted small", text: tr.empty }),
      h("h2", { class: "section-title", text: tr.blockedTitle }),
      data.blocks.length ? data.blocks.map((b) => h("div", { class: "admin-row" }, h("span", { class: "mono", text: b.payee }), h("span", { class: "small muted", text: b.reason }),
        h("button", { class: "btn btn-small", type: "button", text: tr.unblock, onclick: async () => { try { await sendJSON("/api/v1/blocks/" + encodeURIComponent(b.payee), undefined, "DELETE"); problem = ""; await paint(); } catch (e) { fail(e); } } }))) : h("p", { class: "muted small", text: tr.empty })));
  }

  $("top").replaceWith(SP.topbar("/feed"));
  fetch("/api/v1/auth/me", { headers: { Accept: "application/json" } }).then((r) => (r.ok ? r.json() : null)).catch(() => null).then((who) => { me = who; paint().catch(fail); });
})();

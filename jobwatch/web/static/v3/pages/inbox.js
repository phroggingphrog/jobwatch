(function () {
  "use strict";
  var V = window.V3, META = null;
  function nice(s) { return String(s || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function state(k) { return (META && META.states && META.states[k]) || nice(k); }
  function jobLink(p) { var t = V.esc(p.title || "Unknown job"); return p.posting_id ? '<a href="#job/' + p.posting_id + '">' + t + "</a>" : t; }
  function how(p) {
    return [p.from_addr ? "From " + p.from_addr : "", p.received_at ? "Received " + p.received_ago : "", p.confidence != null ? Math.round(p.confidence * 100) + "% sure" : "",
      p.method ? (p.method === "llm" ? "read by AI" : p.method === "rules" ? "matched by rules" : p.method) : ""].filter(Boolean).map(V.esc).join(" · ");
  }
  function item(p, i) { var first = i === 0;
    var flags = p.proposed_status === "offer" ? p.flags_list.filter(function (x) { return x !== "offer_review"; }) : p.flags_list, lab = p.ev_flag_labels || [];
    return '<article class="card ib"><h3 class="ib__t">' + jobLink(p) + (p.company ? ' <span class="ib__co">· ' + V.esc(p.company) + "</span>" : "") + "</h3>" +
      '<p class="ib__what">This reply looks like: <span class="stage">' + V.esc(state(p.proposed_status)) + "</span></p>" +
      (p.proposed_status === "offer" ? '<p class="ib__warn">This looks like an offer. Read it yourself before you approve. Jobwatch only records the status and never replies.</p>' : "") +
      '<p class="ib__subj">' + V.esc(p.subject || "(no subject)") + '</p><p class="ib__m">' + how(p) + "</p>" +
      (p.evidence ? '<blockquote class="ib__q">' + V.esc(p.evidence) + "</blockquote>" : "") +
      (flags.length ? '<p class="row">' + flags.map(function (f) { return '<span class="chip">' + V.esc((META.flag_text || {})[f] || lab[p.flags_list.indexOf(f)] || nice(f)) + "</span>"; }).join("") + "</p>" : "") +
      (p.app_status ? '<p class="ib__m">Approve moves this job from <strong>' + V.esc(state(p.app_status)) + "</strong> to <strong>" + V.esc(state(p.proposed_status)) + "</strong>.</p>" : "") +
      '<div class="row"><button class="btn' + (first ? " btn--main" : "") + '" data-decide="approve" data-pid="' + p.id + '">Approve</button><button class="btn" data-decide="reject" data-pid="' + p.id + '">Reject</button></div></article>';
  }
  function draw(d, flash) {
    var h = d.history || d.closed || [];
    V.view.innerHTML = '<h1>Inbox</h1><p class="sub">' + (d.open.length ? d.open.length + " mail repl" + (d.open.length === 1 ? "y" : "ies") + " waiting for your yes or no." : "All caught up.") +
      " Jobwatch reads your mail (read-only) and nothing changes on your applications until you approve it here.</p>" +
      (flash ? '<p class="ib__flash" role="status">' + V.esc(String(flash).replace(/^#\d+ /, "")) + "</p>" : "") +
      (d.open.length ? d.open.map(item).join("") : '<p class="empty">Nothing to review. Jobwatch checks your mail every 2 hours, 7am to 9pm, after you mark a job applied.</p>') +
      (h.length ? '<details class="card fold"><summary>History (' + h.length + ')</summary><div class="fold__b">' + h.map(function (p) {
        return '<div class="ib__h"><span class="stage">' + V.esc(nice(p.status)) + '</span> <span class="stage">' + V.esc(state(p.proposed_status)) + "</span> " + jobLink(p) + (p.company ? ' <span class="ib__m">· ' + V.esc(p.company) + "</span>" : "") + ' <span class="ib__m">' + V.esc(p.when_ago || "") + "</span></div>";
      }).join("") + "</div></details>" : "");
  }
  function load() {
    return Promise.all([META ? 0 : V.api("/api/meta").then(function (m) { META = m; }), 0]).then(function () { return V.api("/api/inbox"); });
  }
  V.page("inbox", function () {
    load().then(function (d) { if (location.hash === "#inbox") draw(d); }).catch(function (e) { V.view.innerHTML = '<h1>Inbox</h1><p class="empty">' + V.esc(e.message) + "</p>"; });
  });
  document.addEventListener("click", function (e) {
    if (location.hash !== "#inbox") return;
    var t = e.target.closest("[data-decide]"); if (!t) return;
    if (t.dataset.decide === "reject" && !confirm("Reject this suggestion? Your application keeps its current status.")) return;
    t.disabled = true;
    V.api("/api/inbox/" + t.dataset.pid + "/" + t.dataset.decide, {}).then(function (d) { V.toast(d.toast || "Done"); draw(d, d.toast); V.refreshNav(); }).catch(function (err) { t.disabled = false; V.fail(err); });
  });
})();

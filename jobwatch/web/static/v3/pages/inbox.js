(function () {
  "use strict";
  var V = window.V3, META = null;
  function nice(s) { return String(s || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function state(k) { return (META && META.states && META.states[k]) || nice(k); }
  function jobLink(p) { var t = V.esc(p.title || "Unknown job"); return p.posting_id ? '<a class="wk-link" href="#job/' + p.posting_id + '">' + t + "</a>" : t; }
  function how(p) {
    return [p.from_addr ? "From " + p.from_addr : "", p.received_at ? "received " + p.received_ago : "", p.method ? (p.method === "llm" ? "read by AI" : p.method === "rules" ? "matched by rules" : p.method) : ""].filter(Boolean).map(V.esc).join(" · ");
  }
  function item(p, i) {
    var flags = p.proposed_status === "offer" ? p.flags_list.filter(function (x) { return x !== "offer_review"; }) : p.flags_list, lab = p.ev_flag_labels || [], pct = p.confidence != null ? Math.round(p.confidence * 100) : null;
    return '<article class="wk-panel" aria-label="Reply from ' + V.esc(p.company || "employer") + '"><div class="wk-ib-head">' + V.co(p.company || p.title) + '<div style="flex:1;min-width:0"><h2 class="wk-h3" style="font-size:17px">' + jobLink(p) + (p.company ? " · " + V.esc(p.company) : "") + '</h2><p class="wk-sub">' + how(p) + "</p></div>" +
      '<span class="wk-row">' + (p.app_status ? '<span class="tag">' + V.esc(state(p.app_status)) + '</span><span class="wk-arrow" aria-hidden="true">→</span>' : "") + '<span class="chip on" style="cursor:default">' + V.esc(state(p.proposed_status)) + "</span></span></div>" +
      '<div class="wk-ib-body"><div class="wk-sec"><div class="wk-eyebrow">Evidence</div><p class="wk-title">' + V.esc(p.subject || "(no subject)") + "</p>" + (p.evidence ? '<div class="wk-evidence">' + V.esc(p.evidence) + "</div>" : '<p class="wk-sub">No quote was saved.</p>') + "</div>" +
      '<div class="wk-sec"><div class="wk-eyebrow">Confidence</div>' + (pct != null ? '<div class="wk-row" style="flex-wrap:nowrap"><div class="wk-meter" style="flex:1"><i style="width:' + pct + '%"></i></div><b class="wk-mono">' + pct + "%</b></div>" : '<p class="wk-sub">Not recorded.</p>') +
      (flags.length ? '<div class="wk-chips">' + flags.map(function (f) { return '<span class="tag">' + V.esc((META.flag_text || {})[f] || lab[p.flags_list.indexOf(f)] || nice(f)) + "</span>"; }).join("") + "</div>" : "") +
      '<div class="wk-eyebrow" style="margin-top:6px">On approval</div><ul class="wk-prose" style="margin:0;padding-left:20px">' + (p.app_status ? "<li>Stage moves from " + V.esc(state(p.app_status)) + " to " + V.esc(state(p.proposed_status)) + ".</li>" : "<li>Stage is recorded as " + V.esc(state(p.proposed_status)) + ".</li>") + "<li>Nothing is sent to the employer. Jobwatch never replies.</li></ul>" +
      (p.proposed_status === "offer" ? '<div class="wk-note warn">This looks like an offer. Read it yourself before you approve.</div>' : "") + "</div></div>" +
      '<div class="wk-ib-foot"><button class="btn' + (i === 0 ? " primary" : "") + '" type="button" data-decide="approve" data-pid="' + p.id + '">Approve</button><button class="btn" type="button" data-decide="reject" data-pid="' + p.id + '">Reject</button></div></article>';
  }
  function draw(d, flash) {
    var h = d.history || d.closed || [], n = d.open.length;
    V.draw(V.head("Inbox", "Jobwatch reads your mail read-only and proposes changes. Nothing changes on your applications until you approve it here.") +
      (flash ? '<div class="wk-note ok" role="status">' + V.esc(String(flash).replace(/^#\d+ /, "")) + "</div>" : "") +
      '<div class="wk-sec"><h2 class="wk-h2">Pending<span class="n">' + n + "</span></h2>" +
      (n ? d.open.map(item).join("") : '<div class="wk-panel"><div class="wk-empty"><b>All caught up</b><span>Jobwatch checks your mail every 2 hours, 7am to 9pm, after you mark a job applied.</span></div></div>') + "</div>" +
      (h.length ? '<div class="wk-sec"><h2 class="wk-h2">Handled<span class="n">' + h.length + '</span></h2><div class="wk-rows">' + h.map(function (p) {
        return '<div class="wk-prow">' + V.co(p.company || p.title) + '<div class="grow"><div class="wk-title">' + jobLink(p) + (p.company ? " · " + V.esc(p.company) : "") + '</div><div class="wk-sub">' + V.esc(state(p.proposed_status)) + " · " + V.esc(p.when_ago || "") + "</div></div>" + V.st(nice(p.status), p.status === "approved" ? "ok" : "") + "</div>";
      }).join("") + "</div></div>" : ""));
  }
  function load() {
    return Promise.all([META ? 0 : V.api("/api/meta").then(function (m) { META = m; }), 0]).then(function () { return V.api("/api/inbox"); });
  }
  V.page("inbox", function () {
    load().then(function (d) { if (location.hash === "#inbox") draw(d); }).catch(function (e) { V.failPage("Inbox", e); });
  });
  document.addEventListener("click", function (e) {
    if (location.hash !== "#inbox") return;
    var t = e.target.closest("[data-decide]"); if (!t) return;
    if (t.dataset.decide === "reject" && !confirm("Reject this suggestion? Your application keeps its current status.")) return;
    t.disabled = true;
    V.api("/api/inbox/" + t.dataset.pid + "/" + t.dataset.decide, {}).then(function (d) { V.toast(d.toast || "Done"); draw(d, d.toast); V.refreshNav(); }).catch(function (err) { t.disabled = false; V.fail(err); });
  });
})();

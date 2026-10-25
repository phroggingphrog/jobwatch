/* Jobwatch app views: Today, Jobs (Seek layout), one job, Pipeline. Other views live in v3/pages/*.js and register with V3.page().
   The shell (top bar, rail, theme) is base.html + shell.js; this file only draws into <main id="view">. */
(function () {
  "use strict";
  var view = document.getElementById("view"), META = {}, F = { ai: "show", q: "", page: 1, st: "", arr: "", minscore: "", sal: "", entry: "" }, rows = [], SEL = null, GEN = 0, PAGES = {};
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function friendly(c) { return c === 404 ? "Not found. It may have been removed." : c === 401 || c === 403 ? "You are signed out. Reload the page and sign in." : c >= 500 ? "Jobwatch hit a problem. Nothing was changed. Try again." : "That did not work (" + c + "). Nothing changed."; }
  function api(path, body) {
    var opt = body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
    return fetch(path, opt).then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { if (!r.ok) { var er = new Error(typeof (d.error || d.detail) === "string" ? (d.error || d.detail) : friendly(r.status)); er.status = r.status; throw er; } return d; }); }, function () { var er = new Error("Cannot reach Jobwatch. Check that it is running, then try again."); er.status = 0; throw er; });
  }
  function toast(m, bad) { window.jwToast(m, bad); }
  function fail(e) { toast(e.message || "That did not work. Nothing changed.", true); }
  function clean(t) { return String(t || "").replace(/\s+/g, " ").replace(/^(opportunity\s*\/\s*archetype|archetype|tl;?dr)\s*[:\-–]\s*/i, "").replace(/\b(opportunity\s*\/\s*archetype)\s*:\s*/ig, "").trim(); }
  function place(r) { return String(r.where || "").split(" · ")[0].split(",")[0]; }
  function wide() { return matchMedia("(min-width: 901px)").matches; }
  function draw(html) { view.innerHTML = '<div class="wk-page">' + html + "</div>"; }
  function head(title, sub, right) { return '<div class="wk-head"><div><h1 class="wk-h1">' + esc(title) + "</h1>" + (sub ? '<p class="wk-sub" style="margin-top:6px">' + sub + "</p>" : "") + "</div>" + (right || "") + "</div>"; }
  function errBox(msg, nr) { return '<div class="wk-err" role="alert"><span>' + esc(msg) + "</span>" + (nr ? '<a class="btn" href="#jobs">Back to Jobs</a>' : '<button class="btn" type="button" data-retry>Try again</button>') + "</div>"; }
  function failPage(title, e) { draw(head(title) + errBox(e.message || "This page could not load.", e.status === 404)); }
  function sentence(s) { s = String(s || ""); return s.replace(/^./, function (c) { return c.toUpperCase(); }); }

  /* ---- shared pieces ---- */
  function co(name) { var m = /[A-Za-z0-9]/.exec(String(name || "")); return '<span class="wk-co" aria-hidden="true">' + (m ? m[0].toUpperCase() : "?") + "</span>"; }
  function ring(r, sm) {
    var s = r.score5, guess = r.ai_state === "review" && s != null;
    return '<span class="wk-ring' + (guess ? " guess" : "") + (sm ? " sm" : "") + '" style="--p:' + (s != null ? Math.round(Number(s) * 20) : 0) + '"' + (guess ? ' title="A guess: the AI could not read the whole ad"' : "") + ' aria-label="' + (s != null ? "Fit " + Number(s).toFixed(1) + " out of 5" + (guess ? ", a guess" : "") : "Not scored yet") + '">' + (s != null ? (guess ? "~" : "") + Number(s).toFixed(1) : "n/a") + "</span>";
  }
  var ROW_ST = { new: ["New", "accent"], seen: ["Seen", ""], saved: ["Saved", ""], applied: ["Applied", "ok"], hidden: ["Hidden by you", ""], closed: ["Closed", ""] };
  function st(word, tone) { return '<span class="st"' + (tone ? ' data-t="' + tone + '"' : "") + '><span class="pip" aria-hidden="true"></span>' + esc(word) + "</span>"; }
  function rowSt(r) { var x = ROW_ST[r.status] || [r.status || "", ""]; return x[0] ? st(x[0], x[1]) : ""; }
  function jobRow(r, sel) {
    var why = r.ai && r.ai.reason ? clean(r.ai.reason) : r.ai_state === "hide" ? "Hidden: " + r.hide_sentence : clean(r.teaser);
    return '<a class="wk-jrow' + (String(sel) === String(r.id) ? " sel" : "") + '" data-job="' + r.id + '" href="#job/' + r.id + '">' + ring(r) + '<span class="main"><span class="wk-title">' + esc(r.title) + '</span><span class="wk-sub">' + esc(r.company || "Employer not stated") + '</span><span class="wk-sub">' + esc([place(r), r.salary].filter(Boolean).join(" · ")) + "</span>" +
      (why ? '<span class="why">' + esc(why) + "</span>" : "") + (r.ai_state === "review" ? '<span class="wk-sub" style="color:var(--warn)">Held back: the AI did not read the whole ad</span>' : "") +
      '<span class="meta">' + rowSt(r) + '<span class="wk-sub">' + esc(r.listed_ago || "") + "</span></span></span></a>";
  }
  function row(href, lead, title, sub, right) {
    return '<a class="wk-prow" href="' + href + '">' + lead + '<div class="grow"><div class="wk-title">' + title + '</div><div class="wk-sub">' + sub + "</div></div>" + (right || "") + "</a>";
  }

  window.V3 = { api: api, esc: esc, toast: toast, fail: fail, clean: clean, place: place, view: view, draw: draw, head: head, errBox: errBox, failPage: failPage, co: co, ring: ring, st: st, sentence: sentence,
    page: function (name, fn) { PAGES[name] = fn; }, refreshNav: function () { return window.JW.refreshNav(); } };

  /* ---- Today ---- */
  function today() {
    var g = GEN;
    Promise.all([api("/api/board?ai=show&page=1"), api("/api/board?ai=worth&page=1"), api("/api/applications"), api("/api/insights").catch(function () { return null; }), window.JW.refreshNav()]).then(function (r) {
      if (g !== GEN) return;
      var NAV = window.JW.nav(), good = r[0], worth = r[1], apps = r[2], ins = r[3], prog = worth.progress || {}, held = Math.max(0, (worth.total || 0) - (good.total || 0));
      var ready = null, pend = [];
      (apps.cols || []).forEach(function (c) { if (c[0] === "drafted") c[2].forEach(function (a) { if (String(a.draft || "").indexOf("ready") === 0 && !ready) ready = a; }); });
      if (NAV.inbox) pend.push(row("#inbox", co("I"), NAV.inbox + " mail repl" + (NAV.inbox === 1 ? "y" : "ies") + " to confirm", "Jobwatch read your mail and needs a yes or no.", st("Awaiting approval", "warn")));
      if (NAV.sources_bad) pend.push(row("#sources", co("S"), NAV.sources_bad + " job source" + (NAV.sources_bad === 1 ? " is" : "s are") + " failing", "New jobs from it may be missing.", st("Check sources", "bad")));
      var sub = (good.total ? good.total + " job" + (good.total === 1 ? " is" : "s are") + " worth applying to." : "No job is rated Good yet.") + (held ? " " + held + " more are held back because the AI could not read the whole ad." : "");
      var cb = ins && ins.callbacks && ins.callbacks._all ? ins.callbacks._all : { n: 0, successes: 0 }, t7 = ins && ins.totals ? ins.totals.matches_7d : null;
      var fresh = ins && ins.totals && ins.totals.postings === 0 && !ready;
      var focus = fresh ? '<div class="wk-panel wk-focus"><div class="wk-empty"><b>Start here</b><span>Add your CV and Jobwatch builds your profile and your job searches. The first jobs show up after the first search runs.</span><a class="btn primary" href="/welcome">Add your CV</a></div></div>' : ready ? '<div class="wk-panel wk-focus"><div class="wk-row" style="gap:14px;flex-wrap:nowrap">' + co(ready.company) + '<div style="flex:1;min-width:0"><div class="wk-eyebrow">Next action</div><h2 class="wk-h2" style="margin-top:4px">' + esc(ready.title) + (ready.company ? ", " + esc(ready.company) : "") + '</h2><p class="wk-sub">' + esc([ready.where, ready.updated_ago ? "updated " + ready.updated_ago : ""].filter(Boolean).join(" · ")) + "</p></div></div>" +
        '<div class="wk-steps" aria-label="Progress"><div class="wk-step done"><i></i>Ad read</div><div class="wk-step done"><i></i>CV and letter</div><div class="wk-step now"><i></i>You check it</div><div class="wk-step"><i></i>Submit</div></div>' +
        '<div class="wk-row" style="gap:12px">' + ((ready.files || {}).cv ? '<a class="wk-doc" target="_blank" rel="noopener" href="' + esc(ready.files.cv) + '"><b>CV</b><span class="wk-sub">Open the PDF</span></a>' : "") + ((ready.files || {}).letter ? '<a class="wk-doc" target="_blank" rel="noopener" href="' + esc(ready.files.letter) + '"><b>Letter</b><span class="wk-sub">Open the PDF</span></a>' : "") + '<span class="wk-grow" style="flex:1"></span><a class="btn primary" href="/job/' + ready.posting_id + '/prepare">Review application</a></div></div>'
        : '<div class="wk-panel"><div class="wk-empty"><b>Nothing to check right now</b><span>When a CV and letter are ready, the form to review shows up here.</span><a class="btn" href="#jobs">Browse jobs</a></div></div>';
      draw(head("Today", esc(new Date().toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long" }) + ". " + sub)) +
        '<div class="wk-two"><div class="wk-sec" style="gap:20px">' + focus +
        '<div class="wk-sec"><h2 class="wk-h2">Needs you</h2>' + (pend.length ? '<div class="wk-rows">' + pend.join("") + "</div>" : '<div class="wk-panel"><div class="wk-empty">Nothing else needs you right now.</div></div>') + "</div>" +
        '<div class="wk-sec"><div class="wk-sechead"><h2 class="wk-h2">Best matches</h2><a class="btn" href="#jobs">View all ' + (worth.total || 0) + "</a></div>" +
        (good.rows.length ? '<div class="wk-rows">' + good.rows.slice(0, 5).map(function (j) { return row("#job/" + j.id, ring(j), esc(j.title), esc([j.company, place(j), clean(j.ai && j.ai.reason)].filter(Boolean).join(" · "))); }).join("") + "</div>" : '<div class="wk-panel"><div class="wk-empty"><b>Nothing rated Good yet</b><span>Jobwatch is still reading new ads.</span></div></div>') + "</div></div>" +
        '<div class="wk-sec" style="gap:20px">' + (ins ? '<div class="wk-sec"><h2 class="wk-h2">Your numbers</h2><div class="wk-panel wk-pad wk-g3"><div><div class="wk-big">' + (t7 == null ? 0 : t7) + '</div><div class="wk-sub">new, 7 days</div></div><div><div class="wk-big">' + cb.n + '</div><div class="wk-sub">applied</div></div><div><div class="wk-big">' + cb.successes + '</div><div class="wk-sub">callbacks</div></div></div></div>' : "") +
        (prog.total ? '<div class="wk-sec"><h2 class="wk-h2">AI reading</h2><div class="wk-panel wk-pad" style="display:flex;flex-direction:column;gap:10px"><div class="wk-row" style="justify-content:space-between"><span class="wk-body">Read <b>' + prog.read + "</b> of " + prog.total + ' matched ads</span><span class="wk-body">' + Math.round(prog.read * 100 / prog.total) + '%</span></div><div class="wk-meter"><i style="width:' + Math.round(prog.read * 100 / prog.total) + '%"></i></div></div></div>' : "") +
        "</div></div>");
    }).catch(function (e) { failPage("Today", e); });
  }

  /* ---- Jobs: Seek layout. Search and filter chips on top, list on the left, selected job on the right with a sticky action header. ---- */
  var VIEWS = [["show", "Good"], ["review", "Held back"], ["hide", "Hidden by AI"], ["pending", "Waiting"]];
  var TOGGLES = [["st", "new", "New"], ["sal", "1", "Pay shown"], ["entry", "1", "Entry level"], ["arr", "remote", "Remote"], ["minscore", "4.0", "Fit 4.0+"]];
  function jobs(append) {
    var g = GEN, p = new URLSearchParams({ ai: F.ai, page: F.page, sort: "fit" });
    ["q", "st", "arr", "minscore", "sal", "entry"].forEach(function (k) { if (F[k]) p.set(k, F[k]); });
    api("/api/board?" + p).then(function (d) {
      if (g !== GEN) return;
      rows = append ? rows.concat(d.rows) : d.rows;
      var c = d.counts.ai || {};
      if (F.auto !== 1 && F.ai === "show" && !d.total && (c.review || 0) > 0) { F.auto = 1; F.ai = "review"; jobs(false); return; }
      if (!SEL || !rows.some(function (r) { return String(r.id) === String(SEL); })) SEL = rows[0] ? rows[0].id : null;
      var list = rows.map(function (r) { return jobRow(r, wide() ? SEL : null); }).join("");
      var more = d.page < d.pages ? '<div style="padding:12px;display:flex;justify-content:center"><button class="btn" type="button" data-more>Show more (' + (d.total - rows.length) + " left)</button></div>" : "";
      var empty = '<div class="wk-empty"><b>No jobs here' + (F.q ? " for “" + esc(F.q) + "”" : "") + '</b><span>' + (F.q || F.st || F.sal || F.entry || F.arr || F.minscore ? "Try removing a filter." : "Nothing is in this view yet.") + "</span>" + (F.q || F.st || F.sal || F.entry || F.arr || F.minscore ? '<button class="btn" type="button" data-clear>Clear filters</button>' : "") + "</div>";
      if (append) { document.getElementById("list").innerHTML = list; document.getElementById("moreWrap").innerHTML = more; return; }
      draw('<div class="wk-seek"><div class="wk-sbar"><label class="wk-sfield"><svg class="wk-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg><input class="wk-sin" id="q" type="search" placeholder="Job title, company or skill" value="' + esc(F.q) + '" aria-label="Search jobs"></label></div>' +
        '<div class="wk-row" style="justify-content:space-between"><div class="wk-chips" role="group" aria-label="Filters">' + TOGGLES.map(function (x) { return '<button class="chip" type="button" data-tog="' + x[0] + '" data-val="' + x[1] + '" aria-pressed="' + (F[x[0]] === x[1]) + '">' + x[2] + "</button>"; }).join("") + "</div>" +
        '<div class="wk-seg" role="group" aria-label="View">' + VIEWS.map(function (x) { return '<button type="button" data-pill="' + x[0] + '"' + (F.ai === x[0] ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + x[1] + " " + (c[x[0]] || 0) + "</button>"; }).join("") + "</div></div>" +
        '<p class="wk-sub">' + d.total + (d.total === 1 ? " job" : " jobs") + (F.ai === "review" ? ". Their scores are guesses: the AI could not read the whole ad." : F.ai === "show" ? ", read in full by the AI, best fit first" : "") + '</p>' +
        '<div class="wk-sgrid"><div class="wk-list"><div id="list">' + (list || empty) + '</div><div id="moreWrap">' + more + '</div></div><aside class="wk-sdetail" id="pane" aria-label="Job details"></aside></div></div>');
      var q = document.getElementById("q"); if (F.q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
      if (wide() && SEL) pick(SEL); else { var pn = document.getElementById("pane"); if (pn && !SEL) pn.innerHTML = ""; }
    }).catch(function (e) { failPage("Jobs", e); });
  }
  function pick(id) {
    SEL = id;
    document.querySelectorAll("#list .wk-jrow").forEach(function (a) { a.classList.toggle("sel", a.dataset.job === String(id)); });
    var pane = document.getElementById("pane"); if (!pane) return;
    pane.innerHTML = '<div class="wk-sbody"><p class="wk-sub">Loading…</p></div>';
    api("/api/job/" + id).then(function (d) { if (String(SEL) === String(id)) { pane.innerHTML = jobBody(d); pane.scrollTop = 0; if ((d.draft || {}).state === "running") setTimeout(function () { if (String(SEL) === String(id) && document.getElementById("pane")) pick(id); }, 5000); } }).catch(function (e) { pane.innerHTML = '<div class="wk-sbody">' + errBox(e.message) + "</div>"; });
  }

  /* ---- one job ---- */
  function fold(title, body, open) { return '<details class="wk-fold"' + (open ? " open" : "") + "><summary>" + esc(title) + '</summary><div class="wk-fold-b wk-prose">' + body + "</div></details>"; }
  function adText(b) { return !b || !b.length ? "<p>No ad text was saved. Open the ad to read it.</p>" : b.map(function (x) { return x.ul ? "<ul>" + x.ul.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ul>" : x.h ? "<p><strong>" + esc(x.h) + "</strong></p>" : "<p>" + esc(x.p || "") + "</p>"; }).join(""); }
  function verdict(j) {
    var ai = j.ai || {};
    if (!j.ai) return ["", "Not read by the AI yet", "Only a keyword guess exists so far."];
    if (j.ai_state === "hide") return ["bad", "Hidden by the AI", sentence(j.hide_sentence || "Not a fit") + "."];
    if (j.ai_state === "show") return [j.score5 >= 4 ? "ok" : "", j.score5 >= 4 ? "Strong match" : "Decent match", clean((ai.report && ai.report.tldr) || ai.reason)];
    return ["warn", "Held back: treat the score as a guess", "The AI could not read the whole ad, so it could not check everything. It will look again."];
  }
  function heads(j) {
    var ai = j.ai || {}, rep = ai.report || {}, role = rep.role || {}, h = [];
    if (j.ai && ai.text_source && ai.text_source !== "full") h.push("The AI only saw part of this ad.");
    if (role.hours && META.hours_text && ["casual", "part_time_ok", "full_time_only"].indexOf(role.hours) >= 0) h.push("Hours: " + META.hours_text[role.hours] + ".");
    if (role.location_fit && ["cbd_or_far_suburb", "outer", "out_of_scope"].indexOf(role.location_fit) >= 0) h.push("Location: " + META.location_text[role.location_fit] + ".");
    if (ai.rights && ["citizen_or_pr", "citizen_only", "clearance", "unrestricted_work_rights"].indexOf(ai.rights) >= 0 && META.rights_text) h.push(META.rights_text[ai.rights]);
    if (ai.legitimacy === "caution" || ai.legitimacy === "suspicious") h.push("Check this posting is real before applying.");
    if (ai.ad_kind && META.ad_kind_label && META.ad_kind_label[ai.ad_kind]) h.push("Posted by: " + META.ad_kind_label[ai.ad_kind] + ".");
    return h.length ? '<div class="wk-note warn"><ul style="margin:0;padding-left:20px">' + h.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul></div>" : "";
  }
  function docs(d) {
    var dr = d.draft || {}, l = d.draft_links || {};
    if (dr.state === "running") return '<div class="wk-note" role="status"><b>Writing your CV and letter…</b> This takes a few minutes and updates by itself.</div>';
    if (dr.state === "failed" || dr.state === "error") return '<div class="wk-note bad" role="alert">The CV and letter could not be written. Use “Write my CV + letter” to try again.</div>';
    if (dr.state !== "ready") return "";
    return '<div class="wk-sec"><h2 class="wk-h3">Documents</h2><div class="wk-rows">' + [["CV", l.cv], ["Cover letter", l.letter]].filter(function (x) { return x[1]; }).map(function (x) { return '<div class="wk-prow"><div class="grow"><div class="wk-title">' + x[0] + '</div><div class="wk-sub">PDF, ready</div></div><a class="btn" target="_blank" rel="noopener" href="' + esc(x[1]) + '">Open</a></div>'; }).join("") + "</div></div>";
  }
  function jobBody(d, full) {
    var j = d.job, id = j.id, v = verdict(j), stt = j.app_status || "", saved = stt && stt !== "skipped", dr = d.draft || {}, ai = j.ai || {}, rep = ai.report, acts = "";
    if (dr.state === "ready") acts += '<a class="btn primary" href="/job/' + id + '/prepare">Review application</a>';
    else if (!saved) acts += '<button class="btn primary" type="button" data-act="save" data-id="' + id + '">Save this job</button>';
    else if (dr.state !== "running") acts += '<button class="btn primary" type="button" data-act="draft" data-id="' + id + '">Write my CV + letter</button>';
    if (/^https?:/i.test(j.url || "")) acts += '<a class="btn" target="_blank" rel="noopener" href="' + esc(j.url) + '">Open the ad</a>';
    if (saved && stt !== "applied") acts += '<button class="btn" type="button" data-act="applied" data-id="' + id + '">I applied</button>';
    acts += stt === "skipped" ? '<button class="btn ghost" type="button" data-act="unhide" data-id="' + id + '">Unhide</button>' : stt !== "applied" ? '<button class="btn ghost" type="button" data-act="hide" data-id="' + id + '">Not for me</button>' : "";
    if (stt === "applied" || stt === "interview") acts += '<a class="btn" href="#interview/' + id + '">Interview prep</a>';
    var dims = rep && rep.dimensions ? '<ul class="wk-dims">' + (META.dim_label || []).map(function (x) { var s = rep.dimensions[x[0]]; return s == null ? "" : "<li><span>" + esc(x[1]) + '</span><strong class="wk-mono">' + Number(s).toFixed(1) + '</strong><span class="wk-meter"><i style="width:' + Math.round(s * 20) + '%"></i></span></li>'; }).join("") + "</ul>" : "";
    var pc = (ai.pros || []).length || (ai.cons || []).length ? "<p><strong>For:</strong></p><ul>" + (ai.pros || []).slice(0, 4).map(function (t) { return "<li>" + esc(clean(t)) + "</li>"; }).join("") + "</ul><p><strong>Against:</strong></p><ul>" + (ai.cons || []).slice(0, 4).map(function (t) { return "<li>" + esc(clean(t)) + "</li>"; }).join("") + "</ul>" : "";
    var facts = [["Pay", j.salary || "Not stated"], ["Type", j.wt_label || "Not stated"], ["Where", j.where], ["Found on", (j.src_labels || []).join(", ")], ["Posted", j.posted_abs || j.posted_ago || ""]].filter(function (x) { return x[1]; });
    var evs = (j.events || []).length ? fold("History", '<ul>' + j.events.map(function (e) { return "<li>" + esc(e.ago || "") + ": " + esc((e.kind || "").replace(/_/g, " ") + (e.to_status ? " to " + e.to_status : "")) + "</li>"; }).join("") + "</ul>", false) : "";
    return '<div class="wk-shead"><div class="titles"><h' + (full ? "1" : "2") + ' class="wk-h2">' + esc(j.title) + '</h' + (full ? "1" : "2") + '><p class="wk-sub" style="margin-top:4px">' + esc([j.company || "Employer not stated", j.where, j.salary].filter(Boolean).join(" · ")) + (j.posted_ago ? " · posted " + esc(j.posted_ago) : "") + "</p></div>" + acts + "</div>" +
      '<div class="wk-sbody"><div class="wk-row" style="gap:16px;flex-wrap:nowrap">' + ring(j) + '<div style="min-width:0"><div class="wk-title" style="font-size:17px">' + esc(v[1]) + '</div><p class="wk-sub">' + esc(v[2]) + "</p></div></div>" + heads(j) + docs(d) +
      '<div class="wk-sec"><h2 class="wk-h3">Job details</h2><dl class="wk-kv">' + facts.map(function (x) { return "<dt>" + esc(x[0]) + "</dt><dd>" + esc(x[1]) + "</dd>"; }).join("") + "</dl></div>" +
      fold("About the job", adText(j.blocks), true) + (dims || pc ? fold("How the AI scored it", (ai.reason ? "<p>" + esc(clean(ai.reason)) + "</p>" : "") + dims + pc, false) : "") + evs + "</div>";
  }
  function job(id) {
    var g = GEN;
    api("/api/job/" + id).then(function (d) {
      if (g !== GEN) return;
      var j = d.job, dr = d.draft || {};
      draw('<div class="wk-sdetail full">' + jobBody(d, true) + "</div>");
      document.title = j.title + " – Jobwatch";
      window.JW.page("jobs", '<a href="#jobs">Jobs</a><span aria-hidden="true">›</span><span class="here">' + esc(j.title) + "</span>");
      if (dr.state === "running") setTimeout(function () { if (location.hash === "#job/" + id) job(id); }, 5000);
    }).catch(function (e) { draw('<a class="wk-link" href="#jobs">← Jobs</a>' + errBox(e.message, e.status === 404)); });
  }

  /* ---- Pipeline (applications): rows by whose move it is. Dots show the stage. ---- */
  var STAGES = ["interested", "drafted", "applied", "interview", "offer"];
  function stageDots(s) { var i = Math.max(0, STAGES.indexOf(s === "assessment" ? "interview" : s)); return '<span class="wk-track5" title="Saved, draft, applied, interview, offer" aria-hidden="true">' + STAGES.map(function (_, k) { return "<i" + (k < i ? ' class="d"' : k === i ? ' class="n"' : "") + "></i>"; }).join("") + "</span>"; }
  function appRow(c, a) {
    var f = a.files || {}, ready = String(a.draft || "").indexOf("ready") === 0, act = "";
    if (ready) act = '<a class="btn primary" href="/job/' + a.posting_id + '/prepare">Review application</a>';
    else if (c[0] === "interested" || c[0] === "drafted") act = '<button class="btn" type="button" data-act="applied" data-id="' + a.posting_id + '">I applied</button>';
    else if (c[0] === "applied") act = '<a class="btn" href="#followup/' + a.posting_id + '/email">Follow-up</a>';
    else if (c[0] === "interview" || c[0] === "assessment") act = '<a class="btn" href="#interview/' + a.posting_id + '">Interview prep</a>';
    var links = ready ? (f.cv ? '<a class="btn ghost" target="_blank" rel="noopener" href="' + esc(f.cv) + '">CV</a>' : "") + (f.letter ? '<a class="btn ghost" target="_blank" rel="noopener" href="' + esc(f.letter) + '">Letter</a>' : "") : "";
    return '<div class="wk-prow">' + co(a.company) + '<div class="grow"><a class="wk-title" href="#job/' + a.posting_id + '">' + esc(a.title) + '</a><div class="wk-sub">' + esc([a.company, c[1], a.last_ago ? a.last_ago : ""].filter(Boolean).join(" · ")) + '</div></div>' + stageDots(c[0]) + links + act + "</div>";
  }
  function applications() {
    var g = GEN;
    api("/api/applications").then(function (d) {
      if (g !== GEN) return;
      var todo = [], wait = [];
      (d.cols || []).forEach(function (c) { c[2].forEach(function (a) { (c[0] === "interested" || c[0] === "drafted" ? todo : wait).push(appRow(c, a)); }); });
      var closed = (d.closed || []).map(function (a) { return '<div class="wk-prow">' + co(a.company) + '<div class="grow"><a class="wk-title" href="#job/' + a.posting_id + '">' + esc(a.title) + '</a><div class="wk-sub">' + esc(a.company || "") + "</div></div>" + st((META.states || {})[a.status] || a.status, "") + "</div>"; });
      var sec = function (title, list, hint) { return '<div class="wk-sec"><div class="wk-sechead"><h2 class="wk-h2">' + title + '<span class="n">' + list.length + "</span></h2></div>" + (list.length ? '<div class="wk-rows">' + list.join("") + "</div>" : '<div class="wk-panel"><div class="wk-empty">' + hint + "</div></div>") + "</div>"; };
      var total = todo.length + wait.length;
      draw(head("Pipeline", total ? "Everything you are chasing, by whose move it is. Jobwatch writes the CV and letter; you check the form and press Submit." : "Nothing yet. Save a job and it shows up here.", '<a class="btn" href="#interview">New interview prep</a>') +
        (total ? sec("Your move", todo, "Nothing waiting on you.") + sec("Waiting on them", wait, "No applications sent yet.") : '<div class="wk-panel"><div class="wk-empty"><b>No applications yet</b><span>Open a job and choose “Save this job”.</span><a class="btn primary" href="#jobs">Browse jobs</a></div></div>') +
        (closed.length ? sec("Closed", closed, "") : "") + (total ? '<p class="wk-sub">Dots show the stage: saved, draft, applied, interview, offer.</p>' : ""));
    }).catch(function (e) { failPage("Pipeline", e); });
  }

  /* ---- router and clicks ---- */
  var CRUMB = { today: "Today", jobs: "Jobs", applications: "Pipeline", inbox: "Inbox", chat: "Ask Jobwatch", interview: "Interview prep", followup: "Follow-up", table: "Data</span><span aria-hidden=\"true\">›</span><span class=\"here\">Table", sources: "Data</span><span aria-hidden=\"true\">›</span><span class=\"here\">Sources", insights: "Data</span><span aria-hidden=\"true\">›</span><span class=\"here\">Insights" };
  var KEY = { job: "jobs", followup: "applications" };
  function route() {
    GEN++;
    var h = location.hash.replace(/^#/, "") || "today", p = h.split("/"), n = p[0];
    if (["today", "jobs", "job", "applications"].indexOf(n) < 0 && !PAGES[n]) { location.replace("#today"); return; }
    window.JW.page(KEY[n] || n, n === "job" ? '<a href="#jobs">Jobs</a><span aria-hidden="true">›</span><span class="here">Job</span>' : '<span class="here">' + (CRUMB[n] || "") + "</span>");
    document.title = (CRUMB[n] ? CRUMB[n].replace(/<[^>]*>/g, "").replace("›", " ") : "Jobwatch") + " · Jobwatch";
    view.innerHTML = '<div class="wk-page"><p class="wk-sub">Loading…</p></div>';
    if (PAGES[n]) { PAGES[n](p[1], p[2]); } else { ({ today: today, jobs: function () { F.page = 1; jobs(false); }, job: function () { job(p[1]); }, applications: applications })[n](); }
    window.scrollTo(0, 0); view.focus({ preventScroll: true });
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("a.skip")) { e.preventDefault(); view.focus(); return; }
    var t = e.target.closest("a[data-job]"); if (t && wide() && document.getElementById("pane")) { e.preventDefault(); pick(t.dataset.job); return; }
    t = e.target.closest("[data-tog]"); if (t) { var k = t.dataset.tog; F[k] = F[k] === t.dataset.val ? "" : t.dataset.val; F.page = 1; jobs(false); return; }
    t = e.target.closest("[data-clear]"); if (t) { F.q = F.st = F.arr = F.minscore = F.sal = F.entry = ""; F.page = 1; jobs(false); return; }
    t = e.target.closest("[data-pill]"); if (t) { F.ai = t.dataset.pill; F.page = 1; jobs(false); return; }
    t = e.target.closest("[data-more]"); if (t) { F.page++; jobs(true); return; }
    t = e.target.closest("[data-retry]"); if (t) { route(); return; }
    t = e.target.closest("[data-act]");
    if (t) { t.disabled = true; api("/api/job/" + t.dataset.id + "/" + t.dataset.act, {}).then(function (d) { toast(d.toast || "Done"); window.JW.refreshNav().finally(function () { if (document.getElementById("pane")) jobs(false); else route(); }); }).catch(function (err) { t.disabled = false; fail(err); }); }
  });
  var qt; document.addEventListener("input", function (e) { if (e.target.id === "q") { clearTimeout(qt); qt = setTimeout(function () { F.q = e.target.value.trim(); F.page = 1; jobs(false); }, 400); } });
  window.addEventListener("hashchange", route);
  api("/api/meta").then(function (m) { META = m; }).catch(function () { }).finally(route);
})();

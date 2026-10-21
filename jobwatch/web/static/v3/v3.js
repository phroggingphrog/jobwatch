(function () {
  "use strict";
  var view = document.getElementById("view"), META = {}, NAV = {}, F = { ai: "show", q: "", page: 1 }, rows = [];
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function api(path, body) {
    var opt = body === undefined ? {} : { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) };
    return fetch(path, opt).then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { if (!r.ok) throw new Error(d.error || d.detail || "Request failed (" + r.status + ")"); return d; }); });
  }
  var tt;
  function toast(m, bad) { var t = document.getElementById("toast"); t.textContent = m; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false; clearTimeout(tt); tt = setTimeout(function () { t.hidden = true; }, 3000); }
  function band(s) { return s == null ? "" : s >= 4 ? "good" : s >= 3 ? "ok" : "low"; }
  function score(r, lg) { var guess = r.ai_state === "review" && r.score5 != null; return '<span class="score' + (lg ? " score--lg" : "") + (guess ? " is-guess" : "") + '" data-b="' + (guess ? "" : band(r.score5)) + '"' + (guess ? ' title="A guess: the AI could not read the whole ad"' : "") + ">" + (r.score5 != null ? (guess ? "~" : "") + Number(r.score5).toFixed(1) : "–") + "</span>"; }
  function place(r) { return String(r.where || "").split(" · ")[0].split(",")[0]; }
  function clean(t) { return String(t || "").replace(/\s+/g, " ").replace(/^(opportunity\s*\/\s*archetype|archetype|tl;?dr)\s*[:\-–]\s*/i, "").replace(/\b(opportunity\s*\/\s*archetype)\s*:\s*/ig, "").trim(); }
  function fail(e) { toast(e.message || "That did not work. Nothing changed.", true); }

  /* ---- page modules: v3/pages/<name>.js call V3.page("<name>", function (arg1, arg2) { ... }) ---- */
  var PAGES = {}, GEN = 0;
  window.V3 = { api: api, esc: esc, toast: toast, fail: fail, clean: clean, place: place, avatar: function (n) { return avatar(n); }, score: score, view: view, page: function (name, fn) { PAGES[name] = fn; }, refreshNav: function () { return api("/api/nav").then(function (n) { NAV = n; }); } };

  /* ---- tabs ---- */
  var TABS = [["today", "Today"], ["jobs", "Jobs"], ["applications", "Applications"], ["more", "More"]];
  function drawTabs(cur) {
    document.getElementById("tabs").innerHTML = TABS.map(function (t) {
      var n = t[0] === "applications" ? NAV.applications : 0;
      return '<a class="tab" href="#' + t[0] + '"' + (t[0] === cur ? ' aria-current="page"' : "") + ">" + t[1] + (n ? '<span class="tab__n">' + n + "</span>" : "") + "</a>";
    }).join("");
  }

  /* ---- shared pieces ---- */
  var TINTS = ["#efe9de", "#f3dfd6", "#dcebe5", "#f4e7c8", "#e4e1ee", "#e8e0d2"];
  function avatar(name) { var h = 0, s = String(name || "?"); for (var i = 0; i < s.length; i++) h += s.charCodeAt(i) * (i + 1); var m = /[A-Za-z0-9]/.exec(s); return '<span class="av" style="background:' + TINTS[h % TINTS.length] + '" aria-hidden="true">' + (m ? m[0].toUpperCase() : "?") + "</span>"; }
  function jobRow(r, sel) {
    var why = r.ai && r.ai.reason ? clean(r.ai.reason) : r.ai_state === "hide" ? "Hidden: " + r.hide_sentence : clean(r.teaser);
    var held = r.ai_state === "review" ? '<span class="job__flag">Held back: AI did not read the whole ad</span>' : "";
    return '<a class="card job' + (r.status === "new" ? " is-new" : "") + (String(sel) === String(r.id) ? " is-sel" : "") + '" data-job="' + r.id + '" href="#job/' + r.id + '">' + avatar(r.company) + '<span class="job__main"><h3 class="job__t">' + esc(r.title) + "</h3>" + (r.status === "saved" || r.status === "applied" || r.status === "hidden" ? '<span class="job__state">' + (r.status === "saved" ? "Saved" : r.status === "applied" ? "Applied" : "Hidden by you") + "</span>" : "") +
      '<p class="job__co">' + esc(r.company || "Employer not stated") + '</p><p class="job__m">' + esc(place(r)) + (r.listed_ago ? " · " + esc(r.listed_ago) : "") + "</p>" +
      (r.salary ? '<span class="chip">' + esc(r.salary) + "</span>" : "") + (why ? '<p class="job__why">' + esc(why) + "</p>" : "") + held + "</span>" + score(r) + "</a>";
  }

  /* ---- Today ---- */
  function today() {
    var g = GEN;
    Promise.all([api("/api/board?ai=show&page=1"), api("/api/board?ai=worth&page=1"), api("/api/applications")]).then(function (r) {
      if (g !== GEN) return;
      var good = r[0], worth = r[1], apps = r[2], todo = [], held = Math.max(0, (worth.total || 0) - (good.total || 0)), prog = worth.progress || {};
      (apps.cols || []).forEach(function (c) { if (c[0] === "drafted") c[2].forEach(function (a) { if (String(a.draft || "").indexOf("ready") === 0) todo.push(["#applications", "Check and submit: " + a.title, (a.company || "") + " · CV and letter are ready. You press Submit."]); }); });
      if (NAV.inbox) todo.push(["#inbox", NAV.inbox + " email repl" + (NAV.inbox === 1 ? "y" : "ies") + " to confirm", "Jobwatch read your mail and needs a yes or no."]);
      if (NAV.sources_bad) todo.push(["#sources", NAV.sources_bad + " job source" + (NAV.sources_bad === 1 ? " is" : "s are") + " broken", "New jobs from it may be missing."]);
      var big = good.total ? good.total + " job" + (good.total === 1 ? " is" : "s are") + " worth applying to." : "No job is rated Good yet.";
      var small = held ? held + " more are held back because the AI couldn't read the whole ad" + (prog.left > 0 ? " (it has read " + prog.read + " of " + prog.total + " so far)" : "") + "." : "";
      view.innerHTML = '<h1>Today</h1><p class="sub">' + new Date().toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long" }) + "</p>" +
        '<div class="card hero"><p class="hero__big">' + big + '</p><p class="hero__small">' + esc(small) + "</p>" + (prog.total ? '<div class="strip"><div class="strip__t"><span>AI has read <strong>' + prog.read + "</strong> of " + prog.total + " matched ads</span><span>" + Math.round(prog.read * 100 / prog.total) + '%</span></div><div class="strip__bar"><i style="width:' + Math.round(prog.read * 100 / prog.total) + '%"></i></div></div>' : "") + "</div>" +
        "<h2>Needs you</h2>" + (todo.length ? todo.map(function (t) { return '<a class="card todo" href="' + t[0] + '"><span><strong>' + esc(t[1]) + "</strong><span>" + esc(t[2]) + '</span></span><span class="todo__go">Open →</span></a>'; }).join("") : '<p class="empty">Nothing needs you right now.</p>') +
        "<h2>Best matches</h2>" + (good.rows.length ? good.rows.slice(0, 5).map(jobRow).join("") : '<p class="empty">Nothing rated Good yet.</p>') +
        '<p><a class="btn" href="#jobs">Browse all ' + (worth.total || 0) + " jobs</a></p>";
    }).catch(function (e) { view.innerHTML = '<h1>Today</h1><p class="empty">' + esc(e.message) + '</p><button class="btn" data-retry>Try again</button>'; });
  }

  /* ---- Jobs: search on top, list left, detail right (phone: list, then a full page) ---- */
  var PILLS = [["show", "Checked matches"], ["review", "Held back"], ["hide", "Hidden by AI"], ["pending", "Waiting for AI"]], SEL = null;
  function wide() { return matchMedia("(min-width: 900px)").matches; }
  function jobs(append) {
    var g = GEN;
    var cnt = function (c, k) { return c[k] || 0; };
    var p = new URLSearchParams({ ai: F.ai, page: F.page, sort: "fit" }); if (F.q) p.set("q", F.q); if (F.sal) p.set("sal", "1"); if (F.entry) p.set("entry", "1");
    api("/api/board?" + p).then(function (d) {
      if (g !== GEN) return;
      rows = append ? rows.concat(d.rows) : d.rows;
      var c = d.counts.ai || {};
      if (F.auto !== 1 && F.ai === "show" && !d.total && (c.review || 0) > 0) { F.auto = 1; F.ai = "review"; jobs(false); return; }
      if (!SEL || !rows.some(function (r) { return String(r.id) === String(SEL); })) SEL = rows[0] ? rows[0].id : null;
      var list = rows.map(function (r) { return jobRow(r, wide() ? SEL : null); }).join("") || '<p class="empty">No jobs here' + (F.q ? " for “" + esc(F.q) + "”" : "") + ".</p>";
      var more = d.page < d.pages ? '<button class="btn more" data-more>Show more (' + (d.total - rows.length) + " left)</button>" : "";
      if (append) { document.getElementById("list").innerHTML = list; document.getElementById("moreWrap").innerHTML = more; return; }
      view.innerHTML = '<div class="searchbar"><input class="search" id="q" type="search" placeholder="Job title, company or skill" value="' + esc(F.q) + '" aria-label="Search jobs"></div>' +
        '<div class="pills" role="group" aria-label="Filters">' + PILLS.map(function (x) { return '<button class="pill" data-pill="' + x[0] + '" aria-pressed="' + (F.ai === x[0]) + '">' + x[1] + " <small>" + cnt(c, x[0]) + "</small></button>"; }).join("") +
        '<button class="pill" data-tog="sal" aria-pressed="' + !!F.sal + '">Pay shown</button><button class="pill" data-tog="entry" aria-pressed="' + !!F.entry + '">Entry level</button></div>' +
        '<p class="sub">' + d.total + (d.total === 1 ? " job" : " jobs") + (F.ai === "review" ? ". Their scores are guesses: the AI could not read the whole ad." : F.ai === "show" ? ", read in full by the AI, best match first" : "") + '</p><div class="split"><div class="split__list"><div id="list">' + list + '</div><div id="moreWrap">' + more + '</div></div><aside class="split__pane" id="pane" aria-label="Job details"></aside></div>';
      var q = document.getElementById("q"); if (F.q) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
      if (wide() && SEL) pick(SEL);
    }).catch(function (e) { view.innerHTML = '<h1>Jobs</h1><p class="empty">' + esc(e.message) + '</p><button class="btn" data-retry>Try again</button>'; });
  }
  function pick(id) {
    SEL = id;
    document.querySelectorAll("#list .job").forEach(function (a) { a.classList.toggle("is-sel", a.dataset.job === String(id)); });
    var pane = document.getElementById("pane"); if (!pane) return;
    pane.innerHTML = '<p class="empty">Loading…</p>';
    api("/api/job/" + id).then(function (d) { if (String(SEL) === String(id)) { pane.innerHTML = jobBody(d, true); pane.scrollTop = 0; if ((d.draft || {}).state === "running") setTimeout(function () { if (String(SEL) === String(id) && document.getElementById("pane")) pick(id); }, 5000); } }).catch(function (e) { pane.innerHTML = '<p class="empty">' + esc(e.message) + "</p>"; });
  }

  /* ---- one job ---- */
  function fold(title, body, open) { return '<details class="card fold"' + (open ? " open" : "") + "><summary>" + esc(title) + '</summary><div class="fold__b">' + body + "</div></details>"; }
  function adText(b) { return !b || !b.length ? "<p>No ad text was saved. Open the ad to read it.</p>" : b.map(function (x) { return x.ul ? "<ul>" + x.ul.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ul>" : x.h ? "<p><strong>" + esc(x.h) + "</strong></p>" : "<p>" + esc(x.p || "") + "</p>"; }).join(""); }
  function verdict(j) {
    var sc = j.score5 != null ? Number(j.score5).toFixed(1) : "", ai = j.ai || {};
    if (!j.ai) return ["", "Not read by the AI yet", "Only a keyword guess exists so far."];
    if (j.ai_state === "hide") return ["bad", "Hidden by the AI", (j.hide_sentence || "Not a fit").replace(/^./, function (c) { return c.toUpperCase(); }) + "."];
    if (j.ai_state === "show") return [j.score5 >= 4 ? "good" : "ok", j.score5 >= 4 ? "Strong match" : "Decent match", clean((ai.report && ai.report.tldr) || ai.reason)];
    return ["ok", "Held back: treat the score as a guess", "The AI could not read the whole ad, so it could not check everything. It will look again."];
  }
  function heads(j) {
    var ai = j.ai || {}, rep = ai.report || {}, role = rep.role || {}, h = [];
    if (j.ai && ai.text_source && ai.text_source !== "full") h.push("The AI only saw part of this ad.");
    if (role.hours && META.hours_text && ["casual", "part_time_ok", "full_time_only"].indexOf(role.hours) >= 0) h.push("Hours: " + META.hours_text[role.hours] + ".");
    if (role.location_fit && ["cbd_or_far_suburb", "outer", "out_of_scope"].indexOf(role.location_fit) >= 0) h.push("Location: " + META.location_text[role.location_fit] + ".");
    if (ai.rights && ["citizen_or_pr", "citizen_only", "clearance", "unrestricted_work_rights"].indexOf(ai.rights) >= 0 && META.rights_text) h.push(META.rights_text[ai.rights]);
    if (ai.legitimacy === "caution" || ai.legitimacy === "suspicious") h.push("Check this posting is real before applying.");
    if (ai.ad_kind && META.ad_kind_label && META.ad_kind_label[ai.ad_kind]) h.push("Posted by: " + META.ad_kind_label[ai.ad_kind] + ".");
    return h.length ? '<ul class="heads">' + h.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul>" : "";
  }
  function draftBox(d) {
    var dr = d.draft || {}, l = d.draft_links || {}, id = d.job.id;
    if (dr.state === "running") return '<div class="card draft"><p><strong>Writing your CV and letter…</strong></p><p>This takes a few minutes and updates by itself.</p></div>';
    if (dr.state === "ready") return '<div class="card draft"><p><strong>CV and letter are ready.</strong></p><div class="row">' + (l.cv ? '<a class="btn" target="_blank" rel="noopener" href="' + esc(l.cv) + '">CV (PDF)</a>' : "") + (l.letter ? '<a class="btn" target="_blank" rel="noopener" href="' + esc(l.letter) + '">Letter (PDF)</a>' : "") + '<a class="btn btn--main" href="/job/' + id + '/prepare">Fill the form</a></div></div>';
    return "";
  }
  function jobBody(d, pane) {
    var j = d.job, id = j.id, v = verdict(j), st = j.app_status || "", saved = st && st !== "skipped", dr = d.draft || {}, ai = j.ai || {}, rep = ai.report;
    var acts = "";
    if (!saved) acts += '<button class="btn btn--main" data-act="save" data-id="' + id + '">Save this job</button>';
    else if (dr.state !== "ready" && dr.state !== "running") acts += '<button class="btn btn--main" data-act="draft" data-id="' + id + '">Write my CV + letter</button>';
    if (/^https?:/i.test(j.url || "")) acts += '<a class="btn" target="_blank" rel="noopener" href="' + esc(j.url) + '">Open the ad</a>';
    if (saved && st !== "applied") acts += '<button class="btn" data-act="applied" data-id="' + id + '">I applied</button>';
    acts += st === "skipped" ? '<button class="btn btn--quiet" data-act="unhide" data-id="' + id + '">Unhide</button>' : st !== "applied" ? '<button class="btn btn--quiet" data-act="hide" data-id="' + id + '">Not for me</button>' : "";
    var dims = rep && rep.dimensions ? '<ul class="dims">' + (META.dim_label || []).map(function (x) { var s = rep.dimensions[x[0]]; return s == null ? "" : "<li><span>" + esc(x[1]) + "</span><strong>" + Number(s).toFixed(1) + '</strong><span class="bar5"><i style="width:' + Math.round(s * 20) + '%"></i></span></li>'; }).join("") + "</ul>" : "";
    var pc = (ai.pros || []).length || (ai.cons || []).length ? "<p><strong>For:</strong></p><ul>" + (ai.pros || []).slice(0, 4).map(function (t) { return "<li>" + esc(clean(t)) + "</li>"; }).join("") + "</ul><p><strong>Against:</strong></p><ul>" + (ai.cons || []).slice(0, 4).map(function (t) { return "<li>" + esc(clean(t)) + "</li>"; }).join("") + "</ul>" : "";
    var facts = [["Pay", j.salary || "Not stated"], ["Type", j.wt_label || "Not stated"], ["Where", j.where], ["Found on", (j.src_labels || []).join(", ")], ["Posted", j.posted_abs || j.posted_ago || ""]].filter(function (x) { return x[1]; });
    return (pane ? '' : '<a class="back" href="#jobs">← Jobs</a>') + '<h1>' + esc(j.title) + '</h1><p class="sub">' + esc(j.company || "Employer not stated") + " · " + esc(j.where) + (j.posted_ago ? " · Posted " + esc(j.posted_ago) : "") + "</p>" +
      '<div class="card verdict" data-b="' + v[0] + '">' + score(j, true) + '<div><p class="verdict__t">' + esc(v[1]) + '</p><p class="verdict__s">' + esc(v[2]) + "</p></div></div>" +
      heads(j) + '<div class="actions">' + acts + "</div>" + draftBox(d) +
      '<dl class="facts">' + facts.map(function (x) { return '<div class="card fact"><dt>' + esc(x[0]) + "</dt><dd>" + esc(x[1]) + "</dd></div>"; }).join("") + "</dl>" +
      fold("About the job", adText(j.blocks), true) + (dims || pc ? fold("How the AI scored it", (ai.reason ? "<p>" + esc(clean(ai.reason)) + "</p>" : "") + dims + pc, false) : "");
  }
  function job(id) {
    var g = GEN;
    api("/api/job/" + id).then(function (d) {
      if (g !== GEN) return;
      var j = d.job, dr = d.draft || {};
      view.innerHTML = jobBody(d, false);
      document.title = j.title + " – Jobwatch";
      if (dr.state === "running") setTimeout(function () { if (location.hash === "#job/" + id) job(id); }, 5000);
    }).catch(function (e) { view.innerHTML = '<a class="back" href="#jobs">← Jobs</a><p class="empty">' + esc(e.message) + "</p>"; });
  }

  /* ---- Applications ---- */
  function applications() {
    var g = GEN;
    api("/api/applications").then(function (d) {
      if (g !== GEN) return;
      var items = [];
      (d.cols || []).forEach(function (c) { c[2].forEach(function (a) { items.push([c, a]); }); });
      var h = "<h1>Applications</h1><p class=\"sub\">" + (items.length ? items.length + " tracked. Jobwatch writes the CV and letter; you check the form and press Submit." : "Nothing yet. Save a job and it shows up here.") + "</p>";
      h += items.map(function (x) {
        var c = x[0], a = x[1], f = a.files || {}, ready = String(a.draft || "").indexOf("ready") === 0;
        return '<div class="card app"><div class="app__main"><a href="#job/' + a.posting_id + '"><strong>' + esc(a.title) + '</strong></a><p class="job__m">' + esc(a.company || "") + "</p></div>" +
          '<span class="stage" data-s="' + esc(c[0]) + '">' + esc(c[1]) + "</span>" +
          (ready ? (f.cv ? '<a class="btn" target="_blank" rel="noopener" href="' + esc(f.cv) + '">CV</a>' : "") + (f.letter ? '<a class="btn" target="_blank" rel="noopener" href="' + esc(f.letter) + '">Letter</a>' : "") + '<a class="btn btn--main" href="/job/' + a.posting_id + '/prepare">Fill the form</a>' : "") + (c[0] === "applied" || c[0] === "interview" ? '<a class="btn" href="#followup/' + a.posting_id + '/email">Follow-up</a><a class="btn" href="#interview/' + a.posting_id + '">Interview prep</a>' : "") +
          (c[0] !== "applied" && c[0] !== "interview" && c[0] !== "offer" ? '<button class="btn btn--quiet" data-act="applied" data-id="' + a.posting_id + '">I applied</button>' : "") + "</div>";
      }).join("");
      if (d.closed && d.closed.length) h += "<h2>Closed</h2>" + d.closed.map(function (a) { return '<div class="card app"><div class="app__main"><a href="#job/' + a.posting_id + '">' + esc(a.title) + '</a><p class="job__m">' + esc(a.company || "") + '</p></div><span class="stage">' + esc((META.states || {})[a.status] || a.status) + "</span></div>"; }).join("");
      h += '<p><a class="btn btn--quiet" href="#interview">Prepare an interview from a job link</a></p>';
      view.innerHTML = h;
    }).catch(function (e) { view.innerHTML = '<h1>Applications</h1><p class="empty">' + esc(e.message) + '</p><button class="btn" data-retry>Try again</button>'; });
  }

  /* ---- More ---- */
  function more() {
    var L = [["Ask Jobwatch", "Chat about your jobs", "#chat"], ["Inbox", "Mail replies to confirm", "#inbox"], ["Job sources", "Which sites are working", "#sources"], ["Insights", "Numbers on how it is going", "#insights"], ["All jobs as a table", "Sort and export", "#table"],
      ["My profile", "Your CV facts", "/candidate"], ["Preferences", "Teach it what you like", "/preferences"], ["Form answers", "Answers used when filling forms", "/answers"], ["Accounts", "Logins for job sites", "/accounts"], ["AI models", "Which models do the work", "/models"]];
    view.innerHTML = '<h1>More</h1><p class="sub">Setup and less-used pages.</p><div class="links">' + L.map(function (l) { return '<a class="card link" href="' + l[2] + '"><span>' + l[0] + "<br><small>" + l[1] + "</small></span><span>→</span></a>"; }).join("") + "</div>";
  }

  /* ---- router + clicks ---- */
  function route() {
    GEN++;
    var h = location.hash.replace(/^#/, "") || "today", p = h.split("/"), cur = p[0] === "job" ? "jobs" : p[0];
    if (["today", "jobs", "job", "applications", "more"].indexOf(p[0]) < 0 && !PAGES[p[0]]) { location.replace("#today"); return; }
    if (PAGES[p[0]]) { drawTabs(["table", "insights", "sources", "chat", "inbox", "interview", "followup"].indexOf(p[0]) >= 0 ? "more" : p[0]); document.body.dataset.page = p[0]; view.innerHTML = '<p class="empty">Loading…</p>'; PAGES[p[0]](p[1], p[2]); window.scrollTo(0, 0); return; }
    drawTabs(cur); document.body.dataset.page = p[0]; document.title = "Jobwatch"; view.innerHTML = '<p class="empty">Loading…</p>';
    ({ today: today, jobs: function () { F.page = 1; jobs(false); }, job: function () { job(p[1]); }, applications: applications, more: more })[p[0]]();
    window.scrollTo(0, 0); view.focus({ preventScroll: true });
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("a.skip")) { e.preventDefault(); view.focus(); return; }
    var t = e.target.closest("a[data-job]"); if (t && wide() && document.getElementById("pane")) { e.preventDefault(); pick(t.dataset.job); return; }
    t = e.target.closest("[data-tog]"); if (t) { F[t.dataset.tog] = F[t.dataset.tog] ? "" : "1"; F.page = 1; jobs(false); return; }
    t = e.target.closest("[data-pill]"); if (t) { F.ai = t.dataset.pill; F.page = 1; jobs(false); return; }
    t = e.target.closest("[data-more]"); if (t) { F.page++; jobs(true); return; }
    t = e.target.closest("[data-retry]"); if (t) { route(); return; }
    t = e.target.closest("[data-act]");
    if (t) { t.disabled = true; api("/api/job/" + t.dataset.id + "/" + t.dataset.act, {}).then(function (d) { toast(d.toast || "Done"); api("/api/nav").then(function (n) { NAV = n; }).finally(function () { if (document.getElementById("pane")) { drawTabs("jobs"); jobs(false); } else route(); }); }).catch(function (err) { t.disabled = false; fail(err); }); }
  });
  var qt; document.addEventListener("input", function (e) { if (e.target.id === "q") { clearTimeout(qt); qt = setTimeout(function () { F.q = e.target.value.trim(); F.page = 1; jobs(false); }, 400); } });
  window.addEventListener("hashchange", route);
  Promise.all([api("/api/meta").then(function (m) { META = m; }), api("/api/nav").then(function (n) { NAV = n; })]).catch(function () { }).finally(route);
})();

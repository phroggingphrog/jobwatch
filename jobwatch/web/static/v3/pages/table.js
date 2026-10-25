/* Jobs table: sortable columns, a column picker, the same filters as before, paging, CSV link. */
(function () {
  "use strict";
  var V = window.V3, esc = V.esc, view = V.view, META = null;
  var MULTI = ["arm", "tier", "src", "sector", "arch", "wt", "arr", "hide"];
  var seq = 0, F = blank(), T = { sort: "listed", dir: "", page: 1, cols: null, lastCounts: null };
  var DESC_FIRST = ["fit", "ai_fit", "salary", "listed", "first_seen", "sources", "flags"];
  var NUMERIC = ["ai_fit", "fit", "salary", "listed", "first_seen"];
  var ROW_STATUS = { new: "New", seen: "Seen", saved: "Saved", applied: "Applied", closed: "Closed", hidden: "Hidden" };
  var VIEWS = [["worth", "Worth a look"], ["hide", "Hidden by AI"], ["pending", "Waiting for AI"]];
  var TIER = { core: "Core", fallback: "Fallback", other: "Not matched" }, ARR = { remote: "Remote", vic: "In Victoria" };
  var HIDE = { rights: "ask for specific work rights", fulltime: "are full-time only", experience: "want 2+ years of experience" };
  var GROUP_TITLE = { arm: "Job type", arr: "Where", tier: "Match type", src: "Found on", sector: "Sector", arch: "Kind of role", wt: "Work type", hide: "Leave out ads that…" };

  function blank() { var f = { ai: "worth", why: "", q: "", x: "", scope: "matches", st: "all", within: "", minscore: "", sal: "", salmin: "", entry: "" }; MULTI.forEach(function (k) { f[k] = []; }); return f; }
  function here() { return location.hash === "#table"; }
  function nice(s) { return String(s).replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }).replace(/^Ict /, "ICT "); }
  function labelOf(k, v) {
    if (k === "arm") return v === "none" ? "Not matched" : nice(v);
    if (k === "sector") return v === "unlisted" ? "Not in the registry" : nice(v);
    if (k === "src") return (META.source_label || {})[v] || nice(String(v).replace(/^ats_/, ""));
    if (k === "tier") return TIER[v] || v;
    if (k === "arr") return ARR[v] || v;
    if (k === "wt") return META.work_types[v] || v || "Not stated";
    if (k === "hide") return HIDE[v] || v;
    return v;
  }
  function qs(extra) {
    var p = new URLSearchParams();
    ["ai", "q", "x", "scope", "st", "within", "minscore", "salmin"].forEach(function (k) { if (F[k]) p.set(k, F[k]); });
    if (F.ai === "hide" && F.why) p.set("why", F.why);
    if (F.sal) p.set("sal", "1");
    if (F.entry) p.set("entry", "1");
    MULTI.forEach(function (k) { F[k].forEach(function (v) { p.append(k, v); }); });
    p.set("sort", T.sort); if (T.dir) p.set("dir", T.dir);
    Object.keys(extra || {}).forEach(function (k) { p.set(k, extra[k]); });
    return p;
  }
  function facetCount() {
    var n = 0; MULTI.forEach(function (k) { n += F[k].length; });
    return n + (F.minscore ? 1 : 0) + (F.within ? 1 : 0) + (F.sal || F.salmin ? 1 : 0) + (F.entry ? 1 : 0) + (F.st !== "all" ? 1 : 0) + (F.x ? 1 : 0) + (F.scope === "all" ? 1 : 0);
  }
  function clearFacets() { MULTI.forEach(function (k) { F[k] = []; }); F.minscore = F.within = F.sal = F.salmin = F.entry = F.x = ""; F.st = "all"; F.scope = "matches"; T.page = 1; }

  function cols() {
    if (T.cols) return T.cols;
    var ok = META.table_cols.map(function (c) { return c[0]; }), want = null;
    try { want = JSON.parse(localStorage.getItem("jw-cols") || "null"); } catch (e) { }
    T.cols = (want || []).filter(function (c) { return ok.indexOf(c) >= 0; });
    if (!T.cols.length) T.cols = META.default_cols.slice();
    return T.cols;
  }
  function saveCols() { try { localStorage.setItem("jw-cols", JSON.stringify(T.cols)); } catch (e) { } }
  function dash() { return '<span class="tmute">–</span>'; }
  function badge(t, kind) { return '<span class="tbadge' + (kind ? " tbadge--" + kind : "") + '">' + esc(t) + "</span>"; }
  function cell(key, r) {
    var ai = r.ai;
    if (key === "fit") return '<span title="' + (r.score_src === "ai" ? "AI score" : "Keyword score (the AI has not read it yet)") + '">' + esc(r.score) + "</span>";
    if (key === "ai_fit") return ai && r.score5 != null ? '<span class="tscore" data-b="' + (r.score5 >= 4 ? "good" : r.score5 >= 3 ? "ok" : "low") + '" title="' + esc(V.clean(ai.reason || "")) + '">' + esc(r.score_text) + "</span>" : '<span class="tmute" title="The AI has no score for this job yet">–</span>';
    if (key === "archetype") return r.archetype ? esc(r.archetype) : dash();
    if (key === "ai_view") return V.st(r.ai_text, r.ai_state === "show" ? "ok" : r.ai_state === "review" ? "warn" : "");
    if (key === "title") return esc(r.title);
    if (key === "company") return r.company ? esc(r.company) : dash();
    if (key === "location") return esc(r.where || "");
    if (key === "arm") return esc(r.arm_label);
    if (key === "tier") return esc(TIER[r.tier] || r.tier || "");
    if (key === "sector") return r.sector ? esc(r.sector_label) : dash();
    if (key === "sources") return (r.src_labels || []).map(function (s) { return badge(s); }).join(" ");
    if (key === "wt") return r.wt ? esc(META.work_types[r.wt] || r.wt) : dash();
    if (key === "salary") return r.salary ? esc(r.salary) : dash();
    if (key === "listed") return r.listed_dt ? esc(r.listed_ago) : dash();
    if (key === "first_seen") return esc(r.first_seen_ago);
    if (key === "flags") return ["rights", "fulltime", "experience"].filter(function (w) { return (r.warn || []).indexOf(w) >= 0; }).map(function (w) { return badge(META.warn[w], "ok"); }).join(" ") + (r.entry ? " " + badge("Entry level", "good") : "") + (r.is_remote ? " " + badge("Remote") : "");
    if (key === "status") return V.st(ROW_STATUS[r.status] || r.status, r.status === "applied" ? "ok" : r.status === "new" ? "accent" : "");
    return "";
  }

  /* ---- filters ---- */
  function opt(name, value, label, n, checked, kind) {
    return '<label class="topt"><input type="' + kind + '" name="' + name + '" value="' + esc(value) + '"' + (checked ? " checked" : "") + '><span class="topt__l">' + esc(label) + '</span><span class="topt__n">' + n + "</span></label>";
  }
  function group(title, body, open, val) {
    return '<details class="tgroup"' + (open ? " open" : "") + "><summary><span>" + esc(title) + "</span>" + (val ? '<span class="tgroup__v">' + esc(val) + "</span>" : "") + '</summary><div class="tgroup__b">' + body + "</div></details>";
  }
  function multi(name, counter, selected, order) {
    counter = counter || {};
    var items = [];
    if (order) order.forEach(function (v) { if ((counter[v] || 0) > 0 || selected.indexOf(v) >= 0) items.push(v); });
    else {
      Object.keys(counter).filter(function (v) { return counter[v] > 0; }).sort(function (a, b) { return counter[b] - counter[a]; }).forEach(function (v) { items.push(v); });
      selected.forEach(function (v) { if (items.indexOf(v) < 0) items.push(v); });
    }
    if (!items.length) return "";
    return group(GROUP_TITLE[name], items.map(function (v) { return opt(name, v, labelOf(name, v), counter[v] || 0, selected.indexOf(v) >= 0, "checkbox"); }).join(""), selected.length > 0, selected.length ? selected.length + " chosen" : "");
  }
  function facets(c) {
    var h = "", sn = c.minscore || {}, wn = c.within || {};
    h += group("Your list", META.status_rail.map(function (s) { return opt("st", s[0], s[1], (c.st || {})[s[0]] || 0, F.st === s[0], "radio"); }).join(""), true);
    if (META.score_floor_values.some(function (t) { return sn[t]; }) || F.minscore) {
      h += group("Score", '<label class="topt"><input type="radio" name="minscore" value=""' + (F.minscore ? "" : " checked") + '><span class="topt__l">Any score</span></label>' +
        META.score_floors.filter(function (t) { return (sn[t[0]] || 0) > 0 || Number(F.minscore) === t[0]; }).map(function (t) { return opt("minscore", Number(t[0]).toFixed(1), t[1], sn[t[0]] || 0, Number(F.minscore) === t[0], "radio"); }).join(""), !!F.minscore, F.minscore ? Number(F.minscore).toFixed(1) + " and up" : "");
    }
    if (META.within.some(function (w) { return wn[w[0]]; }) || F.within) {
      h += group("Posted", '<label class="topt"><input type="radio" name="within" value=""' + (F.within ? "" : " checked") + '><span class="topt__l">Any time</span></label>' +
        META.within.filter(function (w) { return (wn[w[0]] || 0) > 0 || String(F.within) === String(w[0]); }).map(function (w) { return opt("within", w[0], "Last " + w[1], wn[w[0]] || 0, String(F.within) === String(w[0]), "radio"); }).join(""), !!F.within, F.within ? "Last " + ((META.within.find(function (w) { return String(w[0]) === String(F.within); }) || [])[1] || F.within) : "");
    }
    h += multi("arr", c.arr, F.arr, ["remote", "vic"]);
    var en = (c.entry || {}).entry || 0, sl = (c.sal || {}).sal || 0, ks = [40, 60, 80, 100, 120, 150];
    if (en || F.entry || sl || F.sal || F.salmin) {
      h += group("Level and pay", (en || F.entry ? opt("entry", "1", "Entry level", en, !!F.entry, "checkbox") : "") + (sl || F.sal || F.salmin ? opt("sal", "1", "Pay shown", sl, !!F.sal, "checkbox") +
        '<label class="tfield"><span>Lowest pay a year</span><select class="wk-sel" name="salmin"><option value="">Any</option>' + ks.map(function (k) { return '<option value="' + k + '"' + (Number(F.salmin) === k ? " selected" : "") + ">$" + k + "k or more</option>"; }).join("") + "</select></label>" : ""), !!(F.entry || F.sal || F.salmin));
    }
    h += multi("arm", c.arm, F.arm); h += multi("tier", c.tier, F.tier, ["core", "fallback", "other"]); h += multi("src", c.src, F.src); h += multi("sector", c.sector, F.sector);
    h += multi("arch", c.arch, F.arch); h += multi("wt", c.wt, F.wt); h += multi("hide", c.hide, F.hide, ["rights", "fulltime", "experience"]);
    return h;
  }
  function chips() {
    var cs = [];
    MULTI.forEach(function (k) { F[k].forEach(function (v) { cs.push([k === "hide" ? "Leave out: " + (META.warn[v] || v) : labelOf(k, v), k, v]); }); });
    if (F.st !== "all") cs.push([(META.status_rail.find(function (s) { return s[0] === F.st; }) || [0, F.st])[1], "st", ""]);
    if (F.minscore) cs.push(["Score " + Number(F.minscore).toFixed(1) + " and up", "minscore", ""]);
    if (F.within) { var w = META.within.find(function (x) { return String(x[0]) === String(F.within); }); cs.push(["Last " + (w ? w[1] : F.within), "within", ""]); }
    if (F.salmin) cs.push(["Pay $" + F.salmin + "k or more", "salmin", ""]); else if (F.sal) cs.push(["Pay shown", "sal", ""]);
    if (F.entry) cs.push(["Entry level", "entry", ""]);
    if (F.x) cs.push(["Without: " + F.x, "x", ""]);
    if (F.scope === "all") cs.push(["Including unmatched jobs", "scope", ""]);
    if (!cs.length) return "";
    return '<div class="wk-chips tchips" role="group" aria-label="Active filters">' + cs.map(function (c) { return '<button type="button" class="chip" data-unchip="' + c[1] + '" data-v="' + esc(c[2]) + '">' + esc(c[0]) + ' <span aria-hidden="true">×</span><span class="sr"> (remove)</span></button>'; }).join("") + '<button type="button" class="btn ghost" data-clear>Clear all</button></div>';
  }
  function applyInput(el) {
    var n = el.name, v = el.value;
    if (MULTI.indexOf(n) >= 0) { var i = F[n].indexOf(v); if (el.checked && i < 0) F[n].push(v); if (!el.checked && i >= 0) F[n].splice(i, 1); }
    else if (n === "sal" || n === "entry") F[n] = el.checked ? "1" : "";
    else F[n] = v;
    T.page = 1;
  }

  /* ---- page ---- */
  function empty(d) {
    var c = d.counts.ai || {}, prog = d.progress || {}, t, sub = "";
    if (facetCount() || F.q) { t = "No jobs match"; sub = "Clear a filter or change the words to see more."; }
    else if (F.ai === "worth") { t = c.pending > 0 && prog.left > 0 ? "The AI is still reading ads (" + prog.read + " of " + prog.total + " read)" : "Nothing worth a look yet"; sub = (c.pending || 0) + " jobs are still waiting for the AI."; }
    else if (F.ai === "hide") { t = "Nothing hidden"; }
    else t = "No jobs here";
    return '<div class="wk-panel"><div class="wk-empty"><b>' + esc(t) + '</b><span>' + esc(sub) + "</span>" + (facetCount() || F.q ? '<button type="button" class="btn" data-clear data-clearq>Clear filters and search</button>' : "") + "</div></div>";
  }
  function pager(d) {
    if (d.pages <= 1) return "";
    return '<nav class="tpager wk-row" aria-label="Pages of results"><button type="button" class="btn" data-goto="' + (d.page - 1) + '"' + (d.page <= 1 ? " disabled" : "") + '>← Previous</button><span class="tmute">Page ' + d.page + " of " + d.pages + '</span><button type="button" class="btn" data-goto="' + (d.page + 1) + '"' + (d.page >= d.pages ? " disabled" : "") + ">Next →</button></nav>";
  }
  function table(d) {
    var cs = cols(), labels = {}; META.table_cols.forEach(function (c) { labels[c[0]] = c[1]; });
    return '<div class="wk-tablewrap" tabindex="0" role="region" aria-label="Jobs table. Scrolls sideways inside this box."><table class="wk-table"><thead><tr>' + cs.map(function (k) {
      var active = T.sort === k, cur = T.dir || (DESC_FIRST.indexOf(k) >= 0 ? "desc" : "asc");
      return '<th scope="col" class="' + (NUMERIC.indexOf(k) >= 0 ? "num" : "") + '" aria-sort="' + (active ? (cur === "asc" ? "ascending" : "descending") : "none") + '"><button type="button" class="tth" data-sortcol="' + k + '">' + esc(labels[k]) + '<span aria-hidden="true">' + (active ? (cur === "asc" ? " ▲" : " ▼") : "") + "</span></button></th>";
    }).join("") + "</tr></thead><tbody>" + d.rows.map(function (r) {
      return "<tr>" + cs.map(function (k, i) {
        var inner = cell(k, r), link = k === "title" || (i === 0 && cs.indexOf("title") < 0);
        return '<td class="' + (NUMERIC.indexOf(k) >= 0 ? "num" : "") + '">' + (link ? '<a class="t" href="#job/' + r.id + '">' + inner + "</a>" : inner) + "</td>";
      }).join("") + "</tr>";
    }).join("") + "</tbody></table></div>";
  }
  function list(d) {
    return '<div class="wk-rows">' + d.rows.map(function (r) {
      return '<a class="wk-prow" href="#job/' + r.id + '">' + V.ring(r, true) + '<div class="grow"><div class="wk-title">' + esc(r.title) + '</div><div class="wk-sub">' + esc(r.company || "Employer not stated") + (r.where ? " · " + esc(String(r.where).split(" · ")[0].split(",")[0]) : "") + (r.salary ? " · " + esc(r.salary) : "") + "</div></div></a>";
    }).join("") + "</div>";
  }
  function draw() {
    if (!here()) return;
    var cs = cols(), keepSearch = document.activeElement && document.activeElement.id === "tq";
    var mine = ++seq;
    V.api("/api/table?" + qs({ page: T.page })).then(function (d) {
      if (!here() || mine !== seq) return;
      var c = d.counts.ai || {}, prog = d.progress || {}, from = (d.page - 1) * d.size + 1;
      var tabs = VIEWS.map(function (v) { var n = v[0] === "worth" ? (c.show || 0) + (c.review || 0) : (c[v[0]] || 0); var cur = F.ai === "show" || F.ai === "review" ? "worth" : F.ai; return '<button type="button" class="chip" data-view="' + v[0] + '" aria-pressed="' + (cur === v[0]) + '">' + v[1] + " <small>" + n + "</small></button>"; }).join("");
      var picker = META.table_cols.map(function (cc) { var on = cs.indexOf(cc[0]) >= 0; return '<label class="topt"><input type="checkbox" data-col="' + cc[0] + '"' + (on ? " checked" : "") + (on && cs.length === 1 ? " disabled" : "") + '><span class="topt__l">' + esc(cc[1]) + "</span></label>"; }).join("");
      var sorts = META.sorts.map(function (s) { return '<option value="' + s[0] + '"' + (s[0] === T.sort ? " selected" : "") + ">" + esc(s[1]) + "</option>"; }).join("");
      if (!META.sorts.some(function (x) { return x[0] === T.sort; })) sorts = '<option value="" selected disabled>Sorted by ' + esc(((META.table_cols.find(function (x) { return x[0] === T.sort; }) || [0, T.sort])[1]).toLowerCase()) + "</option>" + sorts;
      var n = facetCount();
      V.draw(V.head("All jobs", (d.total ? "Showing " + from + " to " + (from + d.rows.length - 1) + " of " + d.total : "No jobs") + " · " + esc(d.summary) + (prog.left > 0 ? " · The AI has read " + prog.read + " of " + prog.total + " ads" : "")) +
        '<div class="ttools"><input class="wk-input ttools__q" id="tq" type="search" placeholder="Job title, company or skill" aria-label="Search jobs" autocomplete="off" value="' + esc(F.q) + '">' +
        '<div class="wk-row"><label class="sr" for="tsort">Sort by</label><select class="wk-sel" id="tsort" aria-label="Sort by">' + sorts + "</select>" +
        '<details class="tmenu"><summary class="btn">Columns ' + cs.length + '</summary><div class="tmenu__pop" role="group" aria-label="Choose columns">' + picker + '<button type="button" class="btn ghost" data-colreset>Back to the usual columns</button></div></details>' +
        '<a class="btn" href="/table.csv?' + esc(qs().toString()) + '" download>Download CSV</a></div></div>' +
        '<div class="wk-chips" role="group" aria-label="Which jobs">' + tabs + "</div>" +
        '<details class="wk-fold tfilters"' + (n ? " open" : "") + "><summary>Filters" + (n ? " (" + n + " on)" : "") + '</summary><div class="wk-fold-b"><label class="tfield"><span>Leave out these words</span><input class="wk-input" id="tx" type="text" placeholder="Words to leave out" autocomplete="off" value="' + esc(F.x) + '"></label>' +
        '<label class="topt"><input type="checkbox" id="tscope"' + (F.scope === "all" ? " checked" : "") + '><span class="topt__l">Include jobs that matched no target role</span></label><div class="tgroups">' + facets(d.counts) + "</div></div></details>" + chips() +
        (d.rows.length ? '<div class="tdesk">' + table(d) + '</div><div class="tphone">' + list(d) + "</div>" + pager(d) : empty(d)));
      if (keepSearch) { var q = document.getElementById("tq"); q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
    }).catch(function (e) { V.draw(V.head("All jobs") + '<div class="wk-err" role="alert"><span>' + esc(e.message) + '</span><button class="btn" type="button" data-tretry>Try again</button></div>'); });
  }

  document.addEventListener("click", function (e) {
    if (!here() || !META) return;
    var t = e.target.closest("[data-sortcol]");
    if (t) { var k = t.dataset.sortcol; if (T.sort === k) T.dir = (T.dir || (DESC_FIRST.indexOf(k) >= 0 ? "desc" : "asc")) === "asc" ? "desc" : "asc"; else { T.sort = k; T.dir = ""; } T.page = 1; draw(); return; }
    t = e.target.closest("[data-view]"); if (t) { F.ai = t.dataset.view; F.why = ""; T.page = 1; draw(); return; }
    t = e.target.closest("[data-goto]"); if (t && !t.disabled) { T.page = Number(t.dataset.goto); draw(); window.scrollTo(0, 0); return; }
    t = e.target.closest("[data-unchip]"); if (t) { var k2 = t.dataset.unchip, v = t.dataset.v; if (MULTI.indexOf(k2) >= 0) F[k2] = F[k2].filter(function (x) { return x !== v; }); else if (k2 === "st") F.st = "all"; else if (k2 === "scope") F.scope = "matches"; else { F[k2] = ""; if (k2 === "salmin") F.sal = ""; } T.page = 1; draw(); return; }
    t = e.target.closest("[data-clear]"); if (t) { clearFacets(); if (t.hasAttribute("data-clearq")) F.q = ""; draw(); return; }
    t = e.target.closest("[data-colreset]"); if (t) { T.cols = META.default_cols.slice(); saveCols(); draw(); return; }
    t = e.target.closest("[data-tretry]"); if (t) { draw(); return; }
    if (!e.target.closest(".tmenu")) { var m = document.querySelector(".tmenu[open]"); if (m) m.removeAttribute("open"); }
  });
  document.addEventListener("change", function (e) {
    if (!here() || !META) return;
    var el = e.target;
    if (el.dataset && el.dataset.col) {
      var cs = cols().slice(), i = cs.indexOf(el.dataset.col);
      if (el.checked && i < 0) cs.push(el.dataset.col); if (!el.checked && i >= 0 && cs.length > 1) cs.splice(i, 1);
      T.cols = cs; saveCols(); var open = document.querySelector(".tmenu"); draw(); setTimeout(function () { var m = document.querySelector(".tmenu"); if (m) m.setAttribute("open", ""); }, 0); return;
    }
    if (el.id === "tsort") { T.sort = el.value; T.dir = ""; T.page = 1; draw(); return; }
    if (el.id === "tscope") { F.scope = el.checked ? "all" : "matches"; T.page = 1; draw(); return; }
    if (el.id === "tx") { F.x = el.value.trim(); T.page = 1; draw(); return; }
    if (el.closest && el.closest(".tgroups") && el.name) { applyInput(el); draw(); }
  });
  var qt; document.addEventListener("input", function (e) { if (here() && e.target.id === "tq") { clearTimeout(qt); qt = setTimeout(function () { F.q = e.target.value.trim(); T.page = 1; draw(); }, 400); } });

  V.page("table", function () {
    (META ? Promise.resolve() : V.api("/api/meta").then(function (m) { META = m; })).then(draw).catch(function (e) { V.failPage("All jobs", e); });
  });
})();

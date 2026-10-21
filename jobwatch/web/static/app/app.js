/* Jobwatch app (owner 2026-10-18: "Rebuild new UI properly").
   Every page reads the real data from /api/*, which returns exactly what the classic pages render.
   There is no demo data, no synthetic fallback and no browser copy of server state in this file. */
"use strict";
(function () {
  var view = document.getElementById("view");
  var META = null, NAV = {};
  var PHONE_Q = matchMedia("(max-width: 600px)");
  function phone() { return PHONE_Q.matches; }

  /* ---------- small helpers ---------- */
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function icon(n) { return '<svg class="ph-icon" aria-hidden="true" focusable="false"><use href="#lucide-' + n + '"/></svg>'; }
  function api(path, body) {
    var opt = body === undefined ? { headers: { accept: "application/json" } }
      : { method: "POST", headers: { "content-type": "application/json", accept: "application/json" }, body: JSON.stringify(body) };
    return fetch(path, opt).then(function (r) {
      var json = (r.headers.get("content-type") || "").indexOf("json") >= 0;
      return r.json().catch(function () { return null; }).then(function (d) {
        if (!r.ok) throw new Error(r.status === 401 ? "Your session ended. Reload to sign in again." : (d && (d.error || d.detail)) || ("Request failed (" + r.status + ")"));
        /* a redirect to the login page (or any HTML) is not a success */
        if (r.redirected || !json || d === null) throw new Error("Your session ended. Reload to sign in again.");
        return d;
      });
    });
  }
  var toastTid = null;
  function toast(msg, bad) {
    var t = document.getElementById("toast");
    t.textContent = msg; t.dataset.bad = bad ? "1" : ""; t.hidden = false;
    clearTimeout(toastTid); toastTid = setTimeout(function () { t.hidden = true; }, 4000);
  }
  function fail(e) { toast(e.message || "Something went wrong. Nothing changed.", true); }
  function ago(iso) {
    if (!iso) return "";
    var d = (Date.now() - new Date(iso).getTime()) / 864e5;
    if (isNaN(d)) return "";
    if (d < 1 / 24) return "just now";
    if (d < 1) return Math.round(d * 24) + " hours ago";
    if (d < 2) return "yesterday";
    return Math.round(d) + " days ago";
  }
  function day(iso) { if (!iso) return ""; var d = new Date(iso); return isNaN(d) ? String(iso).slice(0, 10) : d.toLocaleDateString("en-AU", { day: "numeric", month: "short" }); }
  function loading(title) { view.innerHTML = head(title, "Loading…"); }
  function head(title, sub) { return '<header class="c-head"><h1 class="c-h1" tabindex="-1">' + esc(title) + '</h1>' + (sub ? '<p class="ph-meta">' + sub + '</p>' : "") + "</header>"; }
  function errorBox(e, retry) {
    return '<div class="ph-alert ph-alert--error" role="alert"><span>' + esc(e.message || "Could not load this page.") + '</span>' +
      (retry ? ' <button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-retry>Try again</button>' : "") + "</div>";
  }
  function prose(text) {   // the chat model writes short markdown: paragraphs, "- " / "1. " lists, **bold**, `code`, ## headings
    var out = [], list = null, kind = "";
    function flush() { if (list) { out.push("<" + kind + ">" + list.join("") + "</" + kind + ">"); list = null; } }
    String(text || "").split("\n").forEach(function (line) {
      var l = esc(line).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
      var ul = /^\s*[-*•] +/.test(line), ol = /^\s*\d+[.)] +/.test(line);
      if (ul || ol) { var k = ul ? "ul" : "ol"; if (list && kind !== k) flush(); if (!list) { list = []; kind = k; } list.push("<li>" + l.replace(/^\s*([-*•]|\d+[.)]) +/, "") + "</li>"); return; }
      flush();
      if (/^#{1,3} /.test(line)) out.push("<h3>" + l.replace(/^#{1,3} /, "") + "</h3>");
      else if (line.trim()) out.push("<p>" + l + "</p>");
    });
    flush();
    return out.join("");
  }
  function adText(blocks) {
    if (!blocks || !blocks.length) return '<p class="ph-meta">No ad text was captured for this job. Open the ad to read it.</p>';
    return blocks.map(function (b) {
      if (b.ul) return "<ul>" + b.ul.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ul>";
      if (b.h) return "<h3>" + esc(b.h) + "</h3>";
      return "<p>" + esc(b.p || "") + "</p>";
    }).join("");
  }
  function clean(t) {   // never show internal codes or file paths: say it in words
    return String(t == null ? "" : t).replace(/\bOpportunity\s*\/\s*archetype:\s*/gi, "").replace(/`([^`]+)`/g, function (m, a) { return a.replace(/_/g, " "); })
      .replace(/\s*~\/[\w.\/-]+/g, "").replace(/\b[a-z]{2,}(?:_[a-z]+)+\b/g, function (w) { return w.replace(/_/g, " "); });
  }
  var CODE_WORDS = { model_unavailable: "the AI model was busy", model_invalid_response: "the AI gave an unreadable answer", invalid_requirements: "the ad's requirements could not be read",
    posting_unavailable: "the ad is gone", invalid_citation: "the AI cited something it could not back up", invalid_tool_arguments: "the AI made a malformed request", insufficient_evidence: "the ad did not give enough to judge" };
  function chatWords(t) {   // stored chat text is left alone; this is only how it is shown
    return clean(String(t || "").replace(/`?\b([a-z]+(?:_[a-z]+)+)\b`?/g, function (m, c) { return CODE_WORDS[c] || c; })
      .replace(/\s*Claude Code needs to look[^.]*\./g, "").replace(/\bdlq\b/gi, "failed-jobs queue").replace(/\bREADY\b/g, "ready").replace(/\s*\(?\bT\d+\b\)?/g, ""));
  }
  function noticeWords(t) {
    var m = /stopped on "(.*)" \((\w+)\)/.exec(String(t));
    if (!m) return chatWords(String(t).replace(/^Error:\s*/, "").replace(/\s*Claude Code needs[^.]*\.?.*$/, ""));
    return "Couldn't finish reading \"" + m[1] + "\": " + (CODE_WORDS[m[2]] || m[2].replace(/_/g, " ")) + ". It will retry.";
  }
  function verdictLine(j) {
    var ai = j.ai || {}, sc = j.score5 != null ? Number(j.score5).toFixed(1) : "";
    var why = ai.text_source === "teaser" ? "it only saw a short teaser" : ai.text_source === "partial" ? "it only saw a cut copy of the ad" : ai.text_source && ai.text_source !== "full" ? "it could not confirm it read the whole ad" : "";
    if (!j.ai) return "Not read by the AI yet. The keyword match is all there is for now.";
    if (j.ai_state === "hide") return "Hidden by the AI: " + (j.hide_sentence || "not a fit") + ".";
    if (j.ai_state === "show") return "Good match" + (sc ? ", " + sc + " of 5" : "") + ".";
    return (sc && j.score5 >= 3 ? "Possible match, " + sc + " of 5" : sc ? "Weak match, " + sc + " of 5" : "Not rated") + "." + (why ? " The AI couldn't check everything: " + why + "." : " The AI couldn't give a clear answer.");
  }
  function splitPoints(list) {   // "CV match 3.3/5: text" items become a small dimension list; the rest stay as points
    var dims = [], pts = [];
    [].concat(list || []).forEach(function (t) { var m = /^(.{3,40}?)\s+(\d(?:\.\d)?)\/5\s*[:\-–]\s*(.*)$/.exec(String(t)); if (m) dims.push([m[1], m[2], m[3]]); else pts.push(t); });
    return { dims: dims, pts: pts };
  }
  function score(r) {
    if (r.score5 != null) {
      var band = r.score5 >= 4 ? "good" : r.score5 >= 3 ? "warn" : "bad";
      return '<span class="jx-score" data-band="' + band + '" title="Agent score out of 5">' + Number(r.score5).toFixed(1) + "</span>";
    }
    return '<span class="jx-score" title="The agent has not scored this job">–</span>';
  }
  function aiLabel(state) { var v = (META.ai_views || []).find(function (x) { return x[0] === state; }); return v ? v[1] : state; }
  function aiBadge(r) {
    var k = { show: "success", review: "warning", hide: "secondary", pending: "outline" }[r.ai_state] || "outline";
    return '<span class="ph-badge ph-badge--' + k + '">' + esc(aiLabel(r.ai_state)) + "</span>";
  }
  function appBadge(r) { var s = r.app_status; return s ? '<span class="ph-badge ph-badge--info">' + esc(META.states[s] || s) + "</span>" : ""; }
  function reasonOf(r) {
    var ai = r.ai || {};
    if (r.ai_state === "hide" && ai.hide_reason) { var h = (META.hide_reasons || []).find(function (x) { return x[0] === ai.hide_reason; }); return h ? h[1] : ai.hide_reason; }
    return clean(ai.reason || r.teaser || "");
  }

  /* ---------- navigation ---------- */
  var NAV_GROUPS = [
    ["", [["today", "Today", "house"], ["board", "Find jobs", "layout-dashboard"], ["applications", "Applications", "circle-check"]]],
    ["Help", [["inbox", "Inbox", "message-square-warning"], ["chat", "Ask Jobwatch", "message-circle"]]],
    ["Tools", [["table", "All jobs (table)", "briefcase"], ["insights", "Insights", "gauge"], ["sources", "Job sources", "database"]]],
    ["Setup", [["/candidate", "My profile", "user-round"], ["/preferences", "Preferences", "filter"], ["/answers", "Form answers", "list-checks"], ["/accounts", "Accounts", "key-round"], ["/models", "AI models", "bot"]]]];
  function drawNav(current) {
    var counts = { applications: NAV.applications, inbox: NAV.inbox, sources: NAV.sources_bad, chat: NAV.chat };
    document.getElementById("nav").innerHTML = NAV_GROUPS.map(function (g) {
      return (g[0] ? '<li class="c-navhead" aria-hidden="true">' + g[0] + "</li>" : "") + g[1].map(function (n) {
        var c = counts[n[0]], ext = n[0].charAt(0) === "/";
        return '<li><a class="ph-menu__item" href="' + (ext ? n[0] : "#" + n[0]) + '"' + (n[0] === current ? ' aria-current="page"' : "") + ">" + icon(n[2]) +
          "<span>" + n[1] + "</span>" + (c ? '<span class="ph-badge ph-badge--sm ph-badge--info">' + c + "</span>" : "") + "</a></li>";
      }).join("");
    }).join("");
    var TAB = [["today", "Today", "house"], ["board", "Find jobs", "layout-dashboard"], ["applications", "Applied", "circle-check"], ["inbox", "Inbox", "message-square-warning"], ["more", "More", "ellipsis"]];
    var cur = ["table", "insights", "sources", "chat", "more"].indexOf(current) >= 0 ? "more" : current;
    document.getElementById("tabbar").innerHTML = TAB.map(function (n) {
      var c = counts[n[0]];
      return '<a class="jx-tab" href="#' + n[0] + '"' + (n[0] === cur ? ' aria-current="page"' : "") + ">" + icon(n[2]) + "<span>" + n[1] + "</span>" + (c ? '<i class="jx-tab__n">' + c + "</i>" : "") + "</a>";
    }).join("");
  }
  function refreshNav(current) { return api("/api/nav").then(function (n) { NAV = n; drawNav(current); }).catch(function () { drawNav(current); }); }

  /* ---------- theme (Auto follows the device; the choice is a per-browser convenience) ---------- */
  var THEMES = [["auto", "Auto"], ["phrog-light", "Light"], ["phrog-dark", "Dark"]];
  function applyTheme(t) {
    var eff = t === "auto" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "phrog-dark" : "phrog-light") : t;
    document.documentElement.setAttribute("data-theme", eff);
    document.getElementById("themeName").textContent = "Theme: " + THEMES.find(function (x) { return x[0] === t; })[1];
  }
  var theme = "auto";
  try { theme = localStorage.getItem("jw-theme") || "auto"; } catch (e) { }
  applyTheme(theme);
  document.getElementById("themeBtn").addEventListener("click", function () {
    var i = THEMES.findIndex(function (x) { return x[0] === theme; });
    theme = THEMES[(i + 1) % THEMES.length][0];
    try { localStorage.setItem("jw-theme", theme); } catch (e) { }
    applyTheme(theme);
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { if (theme === "auto") applyTheme("auto"); });


  /* ---------- Filters: one state shared by the Board and the Jobs table, same names as the classic URL ---------- */
  var MULTI = ["arm", "tier", "src", "sector", "arch", "wt", "arr", "hide"];
  var F = { ai: "", why: "", q: "", x: "", sort: "fit", scope: "matches", st: "all", within: "", minscore: "", sal: "", salmin: "", entry: "", arm: [], tier: [], src: [], sector: [], arch: [], wt: [], arr: [], hide: [], page: 1 };
  var S = { sheet: false, saved: false };
  var LAST = { counts: {}, saved: [] };
  function fqs(extra) {
    var p = new URLSearchParams();
    ["ai", "q", "x", "sort", "scope", "st", "within", "minscore", "salmin"].forEach(function (k) { if (F[k]) p.set(k, F[k]); });
    if (F.ai === "hide" && F.why) p.set("why", F.why);
    if (F.sal) p.set("sal", "1");
    if (F.entry) p.set("entry", "1");
    MULTI.forEach(function (k) { F[k].forEach(function (v) { p.append(k, v); }); });
    Object.keys(extra || {}).forEach(function (k) { if (extra[k] === "") p.delete(k); else p.set(k, extra[k]); });
    return p;
  }
  function facetCount() {
    var n = 0;
    MULTI.forEach(function (k) { n += F[k].length; });
    return n + (F.minscore ? 1 : 0) + (F.within ? 1 : 0) + (F.sal || F.salmin ? 1 : 0) + (F.entry ? 1 : 0);
  }
  function clearFacets() { MULTI.forEach(function (k) { F[k] = []; }); F.minscore = F.within = F.sal = F.salmin = F.entry = ""; F.page = 1; }
  var TIER = { core: "Core", fallback: "Fallback", other: "Not matched" }, ARR = { remote: "Remote", vic: "In Victoria" };
  var HIDE = { rights: "ask for specific work rights", fulltime: "are full-time only", experience: "want 2+ years of experience" };
  function nice(s) { return String(s).replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }).replace(/^Ict /, "ICT "); }
  function labelOf(k, v) {
    if (k === "arm") return v === "none" ? "Not matched" : nice(v);
    if (k === "sector") return v === "unlisted" ? "Not in the registry" : nice(v);
    if (k === "src") return (META.source_label || {})[v] || nice(String(v).replace(/^ats_/, ""));
    if (k === "tier") return TIER[v] || v;
    if (k === "arr") return ARR[v] || v;
    if (k === "wt") return META.work_types[v] || v;
    if (k === "hide") return HIDE[v] || v;
    return v;
  }
  function chipsHtml() {
    var cs = [];
    MULTI.forEach(function (k) { F[k].forEach(function (v) { cs.push([(k === "hide" ? "Hide: " + (META.warn[v] || v) : labelOf(k, v)), k, v]); }); });
    if (F.minscore) cs.push(["Score " + Number(F.minscore).toFixed(1) + "+", "minscore", ""]);
    if (F.within) { var w = META.within.find(function (x) { return String(x[0]) === String(F.within); }); cs.push(["Last " + (w ? w[1] : F.within), "within", ""]); }
    if (F.salmin) cs.push(["Salary $" + F.salmin + "k+", "salmin", ""]); else if (F.sal) cs.push(["Salary listed", "sal", ""]);
    if (F.entry) cs.push(["Entry-level", "entry", ""]);
    if (!cs.length) return "";
    return '<div class="jx-chips" role="group" aria-label="Active filters">' + cs.map(function (c) {
      return '<button type="button" class="jx-chip" data-unchip="' + c[1] + '" data-v="' + esc(c[2]) + '"><span>' + esc(c[0]) + '</span><span aria-hidden="true">×</span><span class="ph-sr-only"> (remove this filter)</span></button>';
    }).join("") + '<button type="button" class="ph-btn ph-btn--ghost ph-btn--sm" data-clearfacets>Clear all</button></div>';
  }
  function unchip(k, v) {
    if (MULTI.indexOf(k) >= 0) F[k] = F[k].filter(function (x) { return x !== v; });
    else { F[k] = ""; if (k === "salmin") F.sal = ""; }
    F.page = 1;
  }
  function opt(name, value, label, n, checked, kind) {
    return '<label class="jx-opt"><input type="' + kind + '" name="' + name + '" value="' + esc(value) + '"' + (checked ? " checked" : "") + '><span class="jx-opt__l">' + esc(label) + '</span><span class="jx-opt__n">' + n + "</span></label>";
  }
  function group(title, nsel, body, open, val) {
    if (phone() && !nsel && !val) open = false;
    return '<details class="jx-facet"' + (open || (nsel && !phone()) ? " open" : "") + "><summary><span>" + esc(title) + "</span>" + (val ? '<span class="jx-facet__v">' + esc(val) + "</span>" : nsel ? '<span class="jx-facet__n">' + nsel + "</span>" : "") + '</summary><div class="jx-opts">' + body + "</div></details>";
  }
  function multi(name, title, counter, selected, order, keepOpen) {
    counter = counter || {};
    var items = [];
    if (order) order.forEach(function (v) { if ((counter[v] || 0) > 0 || selected.indexOf(v) >= 0) items.push(v); });
    else {
      Object.keys(counter).filter(function (v) { return v && counter[v] > 0; }).sort(function (a, b) { return counter[b] - counter[a]; }).forEach(function (v) { items.push(v); });
      selected.forEach(function (v) { if (items.indexOf(v) < 0) items.push(v); });
    }
    if (!items.length) return "";
    return group(title, selected.length, items.map(function (v) { return opt(name, v, labelOf(name, v), counter[v] || 0, selected.indexOf(v) >= 0, "checkbox"); }).join(""), keepOpen || items.length <= 7);
  }
  function facetsHtml(c, tbl, noAi) {
    var h = "", ai = c.ai || {}, why = c.why || {}, known = (META.hide_reasons || []).map(function (x) { return x[0]; });
    if (tbl && phone()) h += group("Your list", 0, META.status_rail.map(function (s_) { return opt("st", s_[0], s_[1], (c.st || {})[s_[0]] || 0, F.st === s_[0], "radio"); }).join(""), false, (META.status_rail.find(function (s_) { return s_[0] === F.st; }) || [])[1] || "");
    else if (tbl) h += '<fieldset class="jx-flat"><legend>Status</legend><div class="jx-opts">' + META.status_rail.map(function (s) { return opt("st", s[0], s[1], (c.st || {})[s[0]] || 0, F.st === s[0], "radio"); }).join("") + "</div></fieldset>";
    var extra = Object.keys(why).filter(function (r) { return known.indexOf(r) < 0; }).sort();
    if (!noAi && (!phone() || F.ai === "hide")) h += group("AI view", 0, opt("ai", "worth", "Worth a look", (ai.show || 0) + (ai.review || 0), F.ai === "worth" && !F.why, "radio") + META.ai_views.map(function (v) {
      var one = opt("ai", v[0], v[1], ai[v[0]] || 0, F.ai === v[0] && !F.why, "radio");
      if (v[0] === "hide") one += '<div class="jx-sub" role="group" aria-label="Hidden by AI, by reason">' + known.concat(extra).filter(function (r) { return (why[r] || 0) > 0 || F.why === r; }).map(function (r) { return opt("ai", "hide:" + r, (META.hide_labels || {})[r] || nice(r), why[r] || 0, F.why === r, "radio"); }).join("") + "</div>";
      return one;
    }).join(""), true);
    var sn = c.minscore || {};
    if (META.score_floor_values.some(function (t) { return sn[t]; }) || F.minscore) {
      h += group("Score", 0, '<label class="jx-opt"><input type="radio" name="minscore" value=""' + (F.minscore ? "" : " checked") + '><span class="jx-opt__l">Any score</span></label>' +
        META.score_floors.filter(function (t) { return (sn[t[0]] || 0) > 0 || Number(F.minscore) === t[0]; }).map(function (t) { return opt("minscore", Number(t[0]).toFixed(1), t[1], sn[t[0]] || 0, Number(F.minscore) === t[0], "radio"); }).join(""), true, F.minscore ? Number(F.minscore).toFixed(1) + "+" : "");
    }
    h += multi("arm", "Job type", c.arm, F.arm, null, true);
    var wn = c.within || {};
    if (META.within.some(function (w) { return wn[w[0]]; }) || F.within) {
      h += group("Posted", 0, '<label class="jx-opt"><input type="radio" name="within" value=""' + (F.within ? "" : " checked") + '><span class="jx-opt__l">Any time</span></label>' +
        META.within.filter(function (w) { return (wn[w[0]] || 0) > 0 || String(F.within) === String(w[0]); }).map(function (w) { return opt("within", w[0], "Last " + w[1], wn[w[0]] || 0, String(F.within) === String(w[0]), "radio"); }).join(""), true, F.within ? "Last " + ((META.within.find(function (w) { return String(w[0]) === String(F.within); }) || [])[1] || F.within) : "");
    }
    h += multi("arr", "Where", c.arr, F.arr, ["remote", "vic"]);
    var en = (c.entry || {}).entry || 0, sl = (c.sal || {}).sal || 0;
    if (en || F.entry || sl || F.sal || F.salmin) {
      var ks = [40, 60, 80, 100, 120, 150];
      h += group("Level and pay", (F.entry ? 1 : 0) + (F.sal || F.salmin ? 1 : 0),
        (en || F.entry ? opt("entry", "1", "Entry-level", en, !!F.entry, "checkbox") : "") +
        (sl || F.sal || F.salmin ? opt("sal", "1", "Salary listed", sl, !!F.sal, "checkbox") + '<label class="a-field"><span>Minimum salary (a year)</span><select class="ph-select" name="salmin"><option value="">Any</option>' +
          ks.map(function (k) { return '<option value="' + k + '"' + (Number(F.salmin) === k ? " selected" : "") + ">$" + k + "k or more</option>"; }).join("") + "</select></label>" : ""), true);
    }
    h += multi("tier", "Match tier", c.tier, F.tier, ["core", "fallback", "other"]);
    h += multi("src", "Source", c.src, F.src);
    h += multi("sector", "Sector", c.sector, F.sector);
    h += multi("arch", "Archetype", c.arch, F.arch);
    h += multi("wt", "Work type", c.wt, F.wt);
    h += multi("hide", "Hide ads that…", c.hide, F.hide, ["rights", "fulltime", "experience"]);
    return h;
  }
  function applyFacetInput(el) {
    var n = el.name, v = el.value;
    if (n === "ai") { if (v.indexOf("hide:") === 0) { F.ai = "hide"; F.why = v.slice(5); } else { F.ai = v; F.why = ""; } }
    else if (MULTI.indexOf(n) >= 0) { var i = F[n].indexOf(v); if (el.checked && i < 0) F[n].push(v); if (!el.checked && i >= 0) F[n].splice(i, 1); }
    else if (n === "sal" || n === "entry") F[n] = el.checked ? "1" : "";
    else F[n] = v;
    F.page = 1; T.page = 1;
  }
  function redraw() { if (document.body.dataset.page === "table") renderTable(); else renderBoard(); }

  /* ---------- Board: list + detail, tabs by the agent's verdict ---------- */
  var B = { sel: null, rows: [] };
  function savedHtml() {
    var list = LAST.saved || [];
    return '<div class="jx-pop" id="savedPop" role="group" aria-label="Saved searches"' + (S.saved ? "" : " hidden") + ">" +
      (list.length ? '<ul class="jx-saved">' + list.map(function (s) {
        return '<li><button type="button" class="jx-saved__link" data-opensaved="' + s.id + '" data-q="' + esc(s.query) + '" title="' + esc(s.summary) + '"><span>' + esc(s.name) + '</span><span class="ph-meta">' + s.total + (s.new ? " · " + s.new + " new" : "") +
          '</span></button><button type="button" class="ph-btn ph-btn--ghost ph-btn--icon ph-btn--sm" data-delsaved="' + s.id + '" aria-label="Delete saved search ' + esc(s.name) + '">' + icon("x") + "</button></li>"; }).join("") + "</ul>"
        : '<p class="ph-meta">None yet. Set some filters, then save them here.</p>') +
      '<form class="jx-savebox" id="saveForm"><label class="ph-label" for="saveName">Save these filters</label><input class="ph-input" id="saveName" maxlength="80" placeholder="Name this search" autocomplete="off">' +
      '<button type="submit" class="ph-btn ph-btn--outline ph-btn--sm">Save this search</button></form></div>';
  }
  function emptyHtml(d) {
    var c = d.counts.ai || {}, total = 0, prog = d.progress || {};
    Object.keys(c).forEach(function (k) { total += c[k]; });
    var t = "", sub = "";
    if (total > 0) {
      if (F.ai === "worth" && !(c.show || c.review)) { t = c.pending > 0 && prog.left > 0 ? "The AI is still reading ads (" + prog.read + " of " + prog.total + " read)" : "Nothing worth a look yet"; sub = "Jobs show up here once the AI has read them. " + (c.pending || 0) + " still waiting."; }
      else if (F.ai === "show" && c.pending > 0 && prog.left > 0) { t = "The AI is still reading ads (" + prog.read + " of " + prog.total + " read)"; sub = "Jobs show up here once the AI has read them and found them worth your time. " + c.pending + (c.pending === 1 ? " job here is" : " jobs here are") + " still waiting."; }
      else if (F.ai === "show") { t = "Nothing good in this list"; sub = "The AI did not find a job worth showing among these. The rest are in the other views."; }
      else if (F.ai === "review") { t = "Nothing is held back"; sub = "Every ad the AI read in full has an answer."; }
      else if (F.ai === "hide") { t = "Nothing hidden" + (F.why ? " for this reason (" + ((META.hide_labels || {})[F.why] || F.why).toLowerCase() + ")" : ""); }
      else { t = "The AI has read everything here"; }
    } else if (F.st === "saved" && !facetCount() && !F.q) { t = "Nothing saved yet"; sub = "Press Save on a job and it will wait for you here."; }
    else if (F.st === "applied" && !facetCount() && !F.q) { t = "No applications yet"; sub = "Jobs you mark as applied show up here, and on the Applications page."; }
    else if (F.st === "hidden" && !facetCount() && !F.q) { t = "Nothing hidden"; sub = "Jobs you hide with Hide are kept here, in case you change your mind."; }
    else { t = "No jobs match"; sub = facetCount() || F.q || F.x ? "Clear a filter or change the words to see more." : F.scope === "matches" ? "Nothing has matched your target roles yet. Try searching all jobs." : "Nothing has been collected yet. Check the Sources page."; }
    var acts = META.ai_views.filter(function (v) { return v[0] !== F.ai && c[v[0]] > 0; }).map(function (v) { return '<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-tab="' + v[0] + '">' + esc(v[1]) + " " + c[v[0]] + "</button>"; });
    if (F.ai === "hide" && F.why && c.hide > 0) acts.push('<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-tab="hide">All hidden by AI ' + c.hide + "</button>");
    if (facetCount()) acts.push('<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-clearfacets>Clear all filters</button>');
    if (F.q || F.x) acts.push('<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-clearq>Clear the search words</button>');
    if (F.st !== "all") acts.push('<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-st="all">Show all jobs</button>');
    if (F.scope === "matches") acts.push('<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-scope="all">Search all jobs, not only matches</button>');
    return '<div class="jx-empty"><p class="jx-empty__t">' + esc(t) + '</p><p class="ph-meta">' + esc(sub) + '</p><div class="ph-cluster">' + acts.join("") + "</div></div>";
  }
  function boardTools(d) {
    if (phone()) return '<div class="jx-tools"><div class="ph-input-group jx-search" role="search">' + icon("search") + '<input class="ph-input-group__field" type="search" id="bq" aria-label="Keywords" placeholder="Search" value="' + esc(F.q) + '" autocomplete="off"></div>' +
      '<button type="button" class="ph-btn ph-btn--outline ph-btn--icon jx-filterbtn" data-sheet="open" aria-label="Filters">' + icon("filter") + (facetCount() ? '<span class="jx-facet__n">' + facetCount() + "</span>" : "") + "</button></div>";
    var sorts = META.sorts.map(function (s) { return '<option value="' + s[0] + '"' + (F.sort === s[0] ? " selected" : "") + ">" + esc(s[1]) + "</option>"; }).join("");
    return '<div class="jx-tools"><div class="ph-input-group jx-search" role="search">' + icon("search") +
      '<input class="ph-input-group__field" type="search" id="bq" aria-label="Keywords" placeholder="Search title, company or skills" value="' + esc(F.q) + '" autocomplete="off"></div>' +
      '<label class="a-field"><span class="ph-sr-only">Sort</span><select class="ph-select" id="bsort" aria-label="Sort">' + sorts + "</select></label>" +
      '<button type="button" class="ph-btn ph-btn--outline" data-sheet="open">' + icon("filter") + "Filters" + (facetCount() ? ' <span class="jx-facet__n">' + facetCount() + "</span>" : "") + "</button>" +
      '<span class="jx-savedwrap"><button type="button" class="ph-btn ph-btn--outline" data-savedtoggle>' + icon("bookmark") + "Saved" + ((LAST.saved || []).length ? ' <span class="jx-facet__n">' + LAST.saved.length + "</span>" : "") + "</button>" + savedHtml() + "</span></div>";
  }
  function sheetHtml(d, tbl) {
    return '<div class="jx-sheet" id="sheet"' + (S.sheet ? "" : " hidden") + ' role="dialog" aria-modal="true" aria-label="All filters"><div class="jx-sheet__panel"><span class="jx-grabber" aria-hidden="true"></span><header class="jx-sheet__head"><h2>Filters</h2><span class="ph-cluster">' +
      '<button type="button" class="ph-btn ph-btn--ghost" data-reset>Reset</button><button type="button" class="ph-btn ph-btn--ghost" data-sheet="close">Close</button></span></header><div class="jx-sheet__body jx-facets" id="sheetBody">' + (phone() ? '<div class="jx-sortseg" role="radiogroup" aria-label="Sort">' + META.sorts.map(function (s_) { return '<label><input type="radio" name="sort" value="' + s_[0] + '"' + (F.sort === s_[0] ? " checked" : "") + "><span>" + esc(s_[1]) + "</span></label>"; }).join("") + "</div>" : "") +
        (tbl ? "" : '<div class="jx-rail__search"><label class="a-field"><span class="ph-label">Leave out these words</span><input class="ph-input" id="bx" type="text" placeholder="Words to leave out" value="' + esc(F.x) + '" autocomplete="off"></label><label class="jx-check"><input type="checkbox" id="bscope"' + (F.scope === "all" ? " checked" : "") + "><span>Include unmatched jobs</span></label></div>") + facetsHtml(d.counts, true) + (phone() ? group("Saved searches", 0, savedHtml().replace(" hidden>", ">").replace('class="jx-pop"', 'class="jx-pop jx-pop--inline"'), false, (LAST.saved || []).length ? String(LAST.saved.length) : "") : "") + '</div>' +
      '<footer class="jx-sheet__foot"><button type="button" class="ph-btn ph-btn--default" data-sheet="close">Show ' + d.total + " jobs</button></footer></div></div>";
  }
  var VIEWS = [["worth", "Worth a look"], ["hide", "Hidden by AI"], ["pending", "Waiting for AI"]];
  function viewCount(c, k) { return k === "worth" ? (c.show || 0) + (c.review || 0) : (c[k] || 0); }
  function renderBoard() {
    var keep = document.getElementById("sheetBody"), sc = keep ? keep.scrollTop : 0;
    if (!F.ai) F.ai = "worth";
    api("/api/board?" + fqs({ page: F.page })).then(function (d) {
      B.rows = d.rows; LAST = { counts: d.counts, saved: d.saved };
      var c = d.counts.ai || {}, prog = d.progress || {};
      var cur = F.ai === "show" || F.ai === "review" ? "worth" : F.ai;
      var tabs = VIEWS.map(function (v) {
        return '<button type="button" class="jx-seg__b" role="tab" data-tab="' + v[0] + '" aria-selected="' + (cur === v[0]) + '">' + esc(v[1]) + ' <span class="jx-seg__n">' + viewCount(c, v[0]) + "</span></button>";
      }).join("");
      var quiet = [d.total + (d.total === 1 ? " job" : " jobs"), F.ai === "worth" ? (c.show ? "best matches first" : "No job is rated Good yet; best matches first") : esc(d.ai_text)];
      if (d.summary && d.summary !== d.ai_text && d.summary !== "Worth a look") quiet.push(esc(d.summary));
      if (d.pages > 1) quiet.push("Page " + d.page + " of " + d.pages);
      if (prog.left > 0) quiet.push("The AI has read " + prog.read + " of " + prog.total + " matched ads");
      if (phone()) {
        quiet = [d.total + (d.total === 1 ? " job" : " jobs")]; if (prog.left > 0) quiet.push("AI read " + prog.read + " of " + prog.total);
        tabs = VIEWS.map(function (v) { return '<button type="button" class="jx-seg__b" role="tab" data-tab="' + v[0] + '" aria-selected="' + (cur === v[0]) + '">' + esc(({ worth: "Worth a look", hide: "Hidden", pending: "Waiting" })[v[0]]) + ' <span class="jx-seg__n">' + viewCount(c, v[0]) + "</span></button>"; }).join("");
      }
      view.innerHTML = '<header class="c-head jx-boardhead"><h1 class="c-h1" tabindex="-1">Find jobs</h1><p class="ph-meta" role="status">' + quiet.join(" · ") + "</p></header>" +
        '<div class="jx-seg" role="tablist" aria-label="Agent verdict">' + tabs + "</div>" +
        boardTools(d) + chipsHtml() +
        '<div class="ph-split c-split"><div class="ph-split__list"><ul class="jx-cards" id="cards" aria-label="Jobs">' + d.rows.map(cardHtml).join("") + "</ul>" +
        (d.rows.length ? "" : emptyHtml(d)) + pager(d) + '</div><article class="ph-split__detail jx-detail" id="detail" tabindex="-1"><div class="jx-detail__empty"><strong>Pick a job to read it here</strong><p class="ph-meta">Click a card to read it. Open job shows the whole page.</p></div></article></div>' +
        sheetHtml(d, true);
      var sb = document.getElementById("sheetBody"); if (sb) sb.scrollTop = sc;
      var pick = B.sel && d.rows.some(function (r) { return String(r.id) === String(B.sel); }) ? B.sel : (d.rows[0] && d.rows[0].id);
      if (pick && matchMedia("(min-width: 900px)").matches) showDetail(pick);
    }).catch(function (e) { view.innerHTML = head("Board") + errorBox(e, true); });
  }
  function cardPhone(r) {
    var ai = r.ai || {}, band = r.score5 == null ? "" : r.score5 >= 4 ? "good" : r.score5 >= 3 ? "warn" : "bad";
    var pill = r.score_src === "ai" ? '<span class="jx-pill-score" data-band="' + band + '" title="Agent score out of 5">' + esc(r.score_text) + '<span class="ph-sr-only"> out of 5, ' + esc(r.score_label) + "</span></span>" : '<span class="jx-pill-score">–</span>';
    var sub = ai.reason ? clean(ai.reason) : r.teaser ? clean(r.teaser) : r.ai_state === "hide" ? "Hidden: " + r.hide_sentence : "";
    var cat = ai.archetype || (r.arm ? r.arm_label : "");
    return '<li class="jx-card jx-card--phone' + (r.status === "new" ? " is-unread" : "") + '" data-id="' + r.id + '"><div class="jx-pc__top"><h2 class="jx-pc__title"><a href="#job/' + r.id + '">' + esc(r.title) + "</a></h2>" + pill + "</div>" +
      '<p class="jx-pc__line">' + esc(r.company || "Employer not stated") + " · " + esc(String(r.where || "").split(",")[0].split(" · ")[0]) + "</p>" +
      '<p class="jx-pc__meta">' + (r.salary ? esc(r.salary) : r.listed_ago ? "Listed " + esc(r.listed_ago) : "") + "</p>" +
      (cat ? '<span class="jx-pc__chip">' + esc(cat) + "</span>" : "") + "</li>";
  }
  function cardHtml(r) {
    if (phone()) return cardPhone(r);
    var ai = r.ai || {}, rep = ai.report, tags = [], warn = r.warn || [];
    if (rep && rep.role && ["casual", "part_time_ok", "full_time_only"].indexOf(rep.role.hours) >= 0) tags.push('<span class="ph-badge ph-badge--secondary" title="Hours the ad offers">' + esc(META.hours_text[rep.role.hours]) + "</span>");
    if (rep && rep.role && (["cbd_or_far_suburb", "outer", "out_of_scope"].indexOf(rep.role.location_fit) >= 0 || (rep.role.location_fit === "remote" && !r.is_remote))) tags.push('<span class="ph-badge ph-badge--secondary" title="Where the job is, from the ad">' + esc(META.location_text[rep.role.location_fit]) + "</span>");
    if (r.entry && !r.ai) tags.push('<span class="ph-badge ph-badge--success">Entry-level</span>');
    if (r.is_remote) tags.push('<span class="ph-badge ph-badge--info">Remote</span>');
    if (ai.ad_kind && META.ad_kind_label[ai.ad_kind]) tags.push('<span class="ph-badge ph-badge--' + (ai.ad_kind === "scam" ? "destructive" : "info") + '">' + esc(META.ad_kind_label[ai.ad_kind]) + "</span>");
    if (r.ai && ai.text_source !== "full") tags.push('<span class="ph-badge ph-badge--warning" title="The AI did not read the whole ad">Ad not fully read</span>');
    if (ai.rights === "valid_work_rights") tags.push('<span class="ph-badge ph-badge--secondary" title="' + esc(META.rights_text.valid_work_rights) + '">Work rights needed</span>');
    if (ai.legitimacy === "caution" || ai.legitimacy === "suspicious") tags.push('<span class="ph-badge ph-badge--' + (ai.legitimacy === "suspicious" ? "destructive" : "warning") + '" title="The AI noticed signals that are worth a quick look before you apply">Check this posting is real</span>');
    ["rights", "fulltime", "experience"].forEach(function (w) { if (warn.indexOf(w) >= 0 && !(w === "rights" && r.ai)) tags.push('<span class="ph-badge ph-badge--warning">' + esc(META.warn[w]) + "</span>"); });
    var kw = !r.ai && r.ai_state !== "hide" ? '<span class="jx-kwtag" title="The AI has not read this ad yet, so this is only a guess from the title and listing.">Keyword score ' + r.score + "</span>" : "";
    var reason = ai.reason ? '<p class="jx-reason" title="What the AI made of this ad">' + esc(clean(ai.reason)) + "</p>" : !r.ai && r.teaser ? '<p class="jx-reason"><span class="jx-reason__tag">Not read by the AI yet</span> ' + esc(r.teaser) + "</p>" : r.ai_state === "hide" ? '<p class="jx-reason">Hidden: ' + esc(r.hide_sentence) + "</p>" : "";
    var sc = r.score_src === "ai" ? '<span class="jx-bigscore" data-band="' + (r.score5 >= 4 ? "good" : r.score5 >= 3 ? "warn" : "bad") + '" title="Agent score out of 5">' + esc(r.score_text) + '<small>/5</small></span><span class="ph-sr-only">' + esc(r.score_text) + " out of 5, " + esc(r.score_label) + "</span>" : '<span class="jx-bigscore" title="The agent has not scored this job">–</span>';
    var stb = r.status === "applied" ? '<span class="ph-badge ph-badge--success">Applied</span>' : r.status === "closed" ? '<span class="ph-badge ph-badge--secondary">Closed</span>' : r.status === "hidden" ? '<span class="ph-badge ph-badge--secondary" title="You hid this job">Hidden by you</span>' : r.status === "saved" ? '<span class="ph-badge ph-badge--info">Saved</span>' : "";
    var quick = r.status === "hidden" ? '<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-act="unhide" data-id="' + r.id + '">Unhide</button>' :
      (r.status === "new" || r.status === "seen" ? '<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-act="save" data-id="' + r.id + '">Save</button>' : "") +
      (r.status === "new" || r.status === "seen" || r.status === "saved" ? '<button type="button" class="ph-btn ph-btn--ghost ph-btn--sm" data-act="hide" data-id="' + r.id + '">Hide</button>' : "");
    return '<li class="jx-card' + (r.status === "new" ? " is-unread" : "") + (r.status === "hidden" ? " is-muted" : "") + '" data-id="' + r.id + '"' + (String(r.id) === String(B.sel) ? ' aria-current="true"' : "") + ">" +
      '<div class="jx-card__score">' + sc + '</div><div class="jx-card__main"><h2 class="jx-card__title"><a href="#job/' + r.id + '" data-pick="' + r.id + '">' + esc(r.title) + "</a>" + stb + "</h2>" +
      '<p class="jx-card__meta">' + esc(r.company || "Employer not stated") + " · " + esc(r.where) + (r.salary ? ' · <span class="jx-salary">' + esc(r.salary) + "</span>" : "") + (r.listed_ago ? " · Listed " + esc(r.listed_ago) : "") + "</p>" +
      reason + (tags.length || kw ? '<div class="jx-tags">' + (kw ? kw : tags.slice(0, 2).join("")) + "</div>" : "") + "</div>" +
      '<div class="jx-card__acts">' + quick + "</div></li>";
  }
  function avatar(name) {
    var h = 0, letter = "";
    String(name || "").split("").forEach(function (ch, i) { if (!letter && /[A-Za-z0-9]/.test(ch)) letter = ch.toUpperCase(); h += ("abcdefghijklmnopqrstuvwxyz0123456789".indexOf(ch.toLowerCase()) + 2) * (i + 1); });
    return '<span class="jx-av jx-av--' + (h % 6) + '" aria-hidden="true">' + (letter || "?") + "</span>";
  }
  function pager(d, pre) {
    if (d.pages <= 1) return "";
    var k = pre || "pg";
    return '<nav class="a-pager" aria-label="Pages of results"><button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-' + k + '="' + (d.page - 1) + '"' + (d.page <= 1 ? " disabled" : "") + ">← Previous</button>" +
      '<span class="ph-meta">Page ' + d.page + " of " + d.pages + '</span><button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-' + k + '="' + (d.page + 1) + '"' + (d.page >= d.pages ? " disabled" : "") + ">Next →</button></nav>";
  }
  function showDetail(id) {
    B.sel = id;
    document.querySelectorAll("#cards .jx-card").forEach(function (li) { if (li.dataset.id === String(id)) li.setAttribute("aria-current", "true"); else li.removeAttribute("aria-current"); });
    var box = document.getElementById("detail");
    if (!box) return;
    box.innerHTML = '<p class="ph-meta">Loading…</p>';
    api("/api/job/" + id).then(function (d) {
      if (B.sel !== id) return;
      var j = d.job;
      box.innerHTML = '<div class="jx-detail__body">' + jobHeadHtml(j, d) + jobMainHtml(d) + jobSideHtml(j) + "</div>";
    }).catch(function (e) { box.innerHTML = errorBox(e); });
  }
  function factsHtml(j) {
    var wt = [].concat(j.wt || []).map(function (w) { return META.work_types[w] || w; }).filter(Boolean).join(", ");
    var rows = [["map-pin", j.location + (j.is_remote ? " · Remote" : "")], ["briefcase", wt], ["dollar-sign", j.salary], ["clock", j.listed_dt ? "Posted " + ago(j.listed_dt) : ""], ["database", j.srcs && j.srcs.length ? "Found on " + [].concat(j.srcs).join(", ") : ""]];
    return '<ul class="a-facts">' + rows.filter(function (r) { return r[1]; }).map(function (r) { return "<li>" + icon(r[0]) + "<span>" + esc(r[1]) + "</span></li>"; }).join("") + "</ul>";
  }
  function listHtml(title, items) { items = items == null ? [] : [].concat(items); return items.length ? "<h4>" + esc(title) + "</h4><ul>" + items.map(function (i) { return "<li>" + esc(i) + "</li>"; }).join("") + "</ul>" : ""; }
  function saveBtn(j) {
    var saved = j.app_status && j.app_status !== "skipped";
    return '<button type="button" class="ph-btn ph-btn--outline" data-act="save" data-id="' + j.id + '"' + (saved ? " disabled" : "") + ">" + icon("bookmark") + (saved ? (META.states[j.app_status] || "Saved") : "Save") + "</button>";
  }
  /* ---------- Job page: the same sections, in the same order, as the classic job page ---------- */
  var OPEN_SECS = { "What the AI read": 1, "At a glance": 1, "About the job": 1, "CV and cover letter": 1 };
  function sec(title, body, cls, summary) {
    return '<details class="ph-card jx-fold' + (cls ? " " + cls : "") + '"' + (OPEN_SECS[title] ? " open" : "") + "><summary>" + esc(summary || title) + '</summary><div class="ph-card__body">' + body + "</div></details>"; }
  function bar5(v) { return '<span class="a-bar5" data-band="' + (v == null ? "" : v >= 4 ? "good" : v >= 3 ? "warn" : "bad") + '"><span style="--w:' + Math.round((v || 0) * 20) + '%"></span></span>'; }
  function rightsFact(ai) {
    var M = META, t;
    if (ai.rights === "none_stated" && ai.text_source === "teaser") t = "Not checked, because only a short teaser was read";
    else if (ai.rights === "none_stated" && ai.text_source === "partial") t = "Not checked, because only a cut copy of the ad was read";
    else if (ai.rights === "none_stated" && ai.text_source !== "full") t = "Not checked, because the whole ad was not read";
    else t = M.rights_text[ai.rights] || String(ai.rights || "").replace(/_/g, " ");
    return "<div" + (M.blocking_rights.indexOf(ai.rights) >= 0 ? ' class="is-block"' : "") + "><dt>Work rights</dt><dd>" + esc(t) +
      (ai.rights_quote && ai.rights !== "none_stated" ? '<blockquote class="a-quote">' + esc(ai.rights_quote) + '<footer class="ph-meta">Exact words from the ad</footer></blockquote>' : "") + "</dd></div>";
  }
  function readFoot(ai) {
    var src = { teaser: "Read from a short teaser only", partial: "Read from a cut copy of the ad", full: "Read from the full ad" }[ai.text_source] || "Read by the AI, not confirmed as the whole ad";
    return '<p class="ph-meta">' + esc([src, ai.model, ai.reviewed_ago || ""].filter(Boolean).join(" · ")) + "</p>";
  }
  function reqSummary(rep) {
    var r = rep.requirements || [], m = r.filter(function (x) { return x.match === "strong"; }).length, p = r.filter(function (x) { return x.match === "partial"; }).length;
    return r.length ? "Requirements · Met " + m + " · Partly " + p : "Requirements";
  }
  function heroHtml(j) {
    var ai = j.ai, rep = ai && ai.report, h = "";
    if (!ai) return sec("What the AI read", '<p class="ph-alert ph-alert--soft"><span><strong>Not read yet.</strong> The AI has not read this ad, so there is no AI score to show. The keyword match below is all there is for now.</span></p>');
    if (j.ai_state === "hide") h += '<p class="ph-alert ph-alert--soft jx-dupverdict"><span><strong>Hidden by the AI:</strong> ' + esc(j.hide_sentence) + '. It stays out of the Good list, and you can still read it here.</span></p>';
    else if (j.ai_state === "review") {
      var why = ai.text_source === "teaser" ? "The AI only saw a short teaser, so it could not check work rights or the level." :
        ai.text_source === "partial" ? "The AI only saw a cut copy of the ad, so it could not check work rights or the level." :
        ai.text_source !== "full" ? "The AI did not confirm it read the whole ad, so it could not check work rights or the level." : "The AI could not give a clear answer.";
      h += '<p class="ph-alert ph-alert--warning jx-dupverdict"><span><strong>Held back.</strong> ' + why + " It will look again when it can read the whole ad.</span></p>";
    }
    if (j.score5 != null) h += '<div class="c-review__score jx-dupverdict"><span class="c-review__big" data-band="' + (j.score5 >= 4 ? "good" : j.score5 >= 3 ? "warn" : "bad") + '">' + esc(j.score_text || Number(j.score5).toFixed(1)) +
      '</span><span class="c-review__of">/ 5</span><span class="ph-badge ph-badge--outline">' + esc(j.score_label || "") + "</span>" + (j.rec_word ? '<span class="ph-badge ph-badge--info">' + esc(j.rec_word) + "</span>" : "") + "</div>" + bar5(j.score5).replace("class=\"a-bar5\"","class=\"a-bar5 jx-dupverdict\"");
    if (rep) {
      if (rep.tldr || ai.reason) h += '<p class="a-lead">' + esc(clean(rep.tldr || ai.reason)) + "</p>";
      if (ai.reason && rep.tldr && ai.reason !== rep.tldr) h += '<p class="ph-meta">' + esc(clean(ai.reason)) + "</p>";
      h += '<ul class="a-dims">' + META.dim_label.map(function (d) { var v = (rep.dimensions || {})[d[0]]; return "<li><span>" + esc(d[1]) + "</span><strong>" + (v != null ? Number(v).toFixed(1) : "—") + "</strong>" + bar5(v) + "</li>"; }).join("") + "</ul>";
      return sec("What the AI read", h);
    }
    if (ai.reason) h += "<p>" + esc(clean(ai.reason)) + "</p>";
    var P = splitPoints(ai.pros), Cn = splitPoints(ai.cons);
    if (P.dims.length || Cn.dims.length) h += '<ul class="a-dims">' + P.dims.concat(Cn.dims).map(function (d) { return "<li><span>" + esc(clean(d[0])) + " <small class=\"ph-meta\">" + esc(clean(d[2])) + "</small></span><strong>" + d[1] + "</strong>" + bar5(Number(d[1])) + "</li>"; }).join("") + "</ul>";
    if (P.pts.length || Cn.pts.length || (!P.dims.length && !Cn.dims.length && ((ai.pros && ai.pros.length) || (ai.cons && ai.cons.length)))) h += '<div class="a-grid2"><div><h3>Pros</h3>' + (P.pts.length ? "<ul>" + P.pts.slice(0, 4).map(function (t) { return "<li>" + esc(clean(t)) + "</li>"; }).join("") + "</ul>" : '<p class="ph-meta">None noted</p>') + "</div>" +
      "<div><h3>Cons</h3>" + (Cn.pts.length ? "<ul>" + Cn.pts.slice(0, 4).map(function (t) { return "<li>" + esc(clean(t)) + "</li>"; }).join("") + "</ul>" : '<p class="ph-meta">None noted</p>') + "</div></div>";
    var lvl = (META.seniority_text[ai.seniority] || "Not stated") + (ai.min_years ? " · asks for " + ai.min_years + "+ " + (ai.min_years == 1 ? "year" : "years") + " of experience" : ai.text_source === "full" ? " · no years of experience asked" : "");
    h += '<dl class="a-dl">' + rightsFact(ai) + "<div><dt>Level</dt><dd>" + esc(lvl) + "</dd></div>" + (ai.role_match ? "<div><dt>Role</dt><dd>" + esc(ai.role_match) + "</dd></div>" : "") +
      (META.ad_kind_label[ai.ad_kind] ? "<div><dt>Posted by</dt><dd>" + esc(META.ad_kind_label[ai.ad_kind]) + "</dd></div>" : "") + "</dl>" + readFoot(ai);
    return sec("What the AI read", h);
  }
  function jevHtml(jev) {
    if (!jev || !(jev.fit || jev.requirements)) return "";
    var h = "";
    if (jev.fit) {
      var lab = { role_match: "Role match", level_fit: "Level fit", skills_match: "Skills match", hours_fit: "Hours fit", growth: "Growth" };
      h += "<p><strong>" + Number(jev.fit.overall).toFixed(1) + "</strong> / 5 overall</p><ul class=\"a-dims\">" + Object.keys(lab).filter(function (k) { return jev.fit[k]; }).map(function (k) {
        return "<li><span>" + lab[k] + "</span><strong>" + Number(jev.fit[k].score).toFixed(1) + "</strong>" + bar5(jev.fit[k].score) + "</li>"; }).join("") + "</ul>";
    }
    if (jev.requirements && jev.requirements.length) h += "<h3>What the ad asks for, and your matching fact</h3><ul class=\"a-reqs\">" + jev.requirements.map(function (r) {
      var met = r.meets === "fully";
      return '<li><strong class="a-' + (met ? "met" : "partly") + '">' + (met ? "Met:" : "Partly:") + "</strong> " + esc(r.requirement) + ' <span class="ph-meta">→ ' + esc(r.evidence || "") + "</span></li>"; }).join("") + "</ul>";
    return sec("Second opinion (Jev)", h + '<p class="ph-meta">Jev saw the ad and your career facts only (no name, contact or visa details).</p>');
  }
  function reportHtml(j) {
    var ai = j.ai, rep = ai && ai.report, M = META;
    if (!rep) return "";
    var role = rep.role || {}, yrs = role.min_years ? role.min_years + "+ " + (role.min_years == 1 ? "year" : "years") : ai.text_source !== "full" ? "Not checked" : "None asked";
    var h = sec("The role", '<dl class="a-dl"><div><dt>Archetype</dt><dd>' + esc(ai.archetype || rep.archetype || "Other") + "</dd></div><div><dt>Level</dt><dd>" + esc(M.seniority_text[role.seniority] || "Not stated") +
      "</dd></div><div><dt>Work mode</dt><dd>" + esc(M.work_mode_text[role.work_mode] || "") + "</dd></div><div><dt>Hours</dt><dd>" + esc(M.hours_text[role.hours] || "") + "</dd></div><div><dt>Location fit</dt><dd>" +
      esc(M.location_text[role.location_fit] || "Not stated") + "</dd></div><div><dt>Years asked</dt><dd>" + esc(yrs) + "</dd></div></dl>");
    h += sec("Work authorization", '<dl class="a-dl">' + rightsFact(ai) + "</dl>");
    h += sec("What the ad asks for, and how you match", rep.requirements && rep.requirements.length ?
      '<div class="ph-table-wrap"><table class="ph-table"><thead><tr><th>Requirement</th><th>Match</th><th>In the ad</th><th>Your CV, or the gap</th></tr></thead><tbody>' + rep.requirements.map(function (r) {
        return "<tr><td>" + esc(r.requirement) + '<br><span class="ph-badge ph-badge--outline">' + esc(M.importance_text[r.importance] || "") + '</span> <span class="ph-badge ph-badge--outline" title="' + esc(M.tier_why[r.tier] || "") + '">' + esc(M.tier_text[r.tier] || "") +
          '</span></td><td><span class="ph-badge ph-badge--' + ({ strong: "success", partial: "warning", missing: "destructive" }[r.match] || "outline") + '">' + esc(M.match_text[r.match] || r.match) + "</span></td><td>" +
          (r.jd_signal ? "<q>" + esc(r.jd_signal) + "</q>" : '<span class="ph-meta">Not quoted</span>') + "</td><td>" + esc(r.evidence || "—") + "</td></tr>"; }).join("") + "</tbody></table></div>"
      : '<p class="ph-meta">The AI did not list any requirements for this ad.</p>', "", reqSummary(rep));
    h += sec("Gaps to be ready for", rep.gaps && rep.gaps.length ? "<ol>" + rep.gaps.map(function (g) { return "<li><strong>" + esc(g.gap) + '</strong><dl class="a-dl"><div><dt>Interview risk</dt><dd>' + esc(g.risk || "—") + "</dd></div><div><dt>Mitigation</dt><dd>" + esc(g.mitigation || "—") + "</dd></div></dl></li>"; }).join("") + "</ol>"
      : '<p class="ph-meta">No gaps flagged on the important requirements.</p>');
    var lt = (rep.legitimacy || {}).tier || ai.legitimacy, sig = (rep.legitimacy || {}).signals || [];
    h += sec("Posting check", '<p><span class="ph-badge ph-badge--outline">' + esc(M.legit_text[lt] || "Not assessed") + '</span> <span class="ph-meta">Is this a real, current vacancy? These are signals to look at, not a verdict.</span></p>' +
      (sig.length ? "<ul>" + sig.map(function (t) { return "<li>" + esc(t) + "</li>"; }).join("") + "</ul>" : lt === "high" ? '<p class="ph-meta">No warning signs found.</p>' : ""));
    var comp = rep.comp || {};
    h += sec("Pay", '<dl class="a-dl"><div><dt>In the ad</dt><dd>' + esc(j.salary || "Not stated") + "</dd></div><div><dt>Company type</dt><dd>" + esc(comp.company_type || "Not stated") + "</dd></div><div><dt>How reliable the pay data is</dt><dd>" + esc(comp.reliability || "") + "</dd></div></dl>" + readFoot(ai));
    return h;
  }
  function draftBox(j, dr, links) {
    var h;
    if (dr.state === "running") h = '<p aria-busy="true"><strong>Drafting your CV and letter…</strong> <span class="ph-meta">' + (dr.started_ago ? "Started " + esc(dr.started_ago) + ". " : "") + "This takes a few minutes and updates by itself.</span></p>";
    else if (dr.state === "ready") h = "<p><strong>Draft ready</strong>" + (dr.version ? ' <span class="ph-meta">(version ' + esc(dr.version) + ")</span>" : "") + "</p>" +
      (links.cv || links.letter || links.summary ? '<div class="ph-cluster">' + (links.cv ? '<a class="ph-btn ph-btn--default" href="' + esc(links.cv) + '" target="_blank" rel="noopener">CV (PDF)</a>' : "") +
        (links.letter ? '<a class="ph-btn ph-btn--default" href="' + esc(links.letter) + '" target="_blank" rel="noopener">Cover letter (PDF)</a>' : "") +
        (links.summary ? '<a class="ph-btn ph-btn--outline" href="' + esc(links.summary) + '" target="_blank" rel="noopener">Summary (notes)</a>' : "") + "</div>" : '<p class="ph-meta">The draft is done, but no files were found to link. Try Draft again.</p>') +
      '<p><a class="ph-btn ph-btn--default" href="/job/' + j.id + '/prepare">Prepare application in Jobwatch</a></p>';
    else if (dr.state === "failed" || dr.state === "error") h = '<p><strong>The draft did not finish.</strong></p><div class="ph-alert ph-alert--error"><span>' + esc(dr.error || "No reason was recorded.") + '</span></div><p class="ph-meta">Press Draft CV + letter to try again.</p>';
    else h = '<p><strong>No draft yet.</strong> <span class="ph-meta">Draft CV + letter makes a tailored CV and cover letter as PDFs.</span></p>';
    h += '<p><button type="button" class="ph-btn ph-btn--' + (dr.state === "ready" ? "outline" : "default") + '" data-act="draft" data-id="' + j.id + '"' + (dr.state === "running" ? " disabled" : "") + ">Draft CV + letter</button></p>" +
      '<p class="ph-meta">Jobwatch fills the application and attaches your documents. You review the filled page, then click Submit or confirm it and Jobwatch presses Submit.</p>';
    return sec("CV and cover letter", h);
  }
  function glanceHtml(j) {
    var badges = (j.tier === "core" ? '<span class="ph-badge ph-badge--info">Core</span>' : j.tier === "fallback" ? '<span class="ph-badge ph-badge--outline">Fallback</span>' : "") +
      (j.entry ? '<span class="ph-badge ph-badge--success">Entry-level</span>' : "") + (j.is_remote ? '<span class="ph-badge ph-badge--info">Remote</span>' : "") +
      ["rights", "fulltime", "experience"].filter(function (w) { return (j.warn || []).indexOf(w) >= 0 && !(w === "rights" && j.ai); }).map(function (w) { return '<span class="ph-badge ph-badge--warning">' + esc(META.warn[w]) + "</span>"; }).join("");
    return sec("At a glance", '<dl class="a-dl"><div><dt>Pay</dt><dd>' + esc(j.salary || "Not stated") + "</dd></div><div><dt>Work type</dt><dd>" + esc(j.wt_label || "") + "</dd></div><div><dt>Job type</dt><dd>" + esc(j.arm_label) +
      "</dd></div><div><dt>Found on</dt><dd>" + esc(j.src_labels.join(", ")) + "</dd></div>" + (j.posted_abs ? "<div><dt>Posted</dt><dd>" + esc(j.posted_abs) + "</dd></div>" : "") + "</dl>" + (badges ? '<div class="ph-cluster">' + badges + "</div>" : ""));
  }
  function seenHtml(j) {
    var s = j.sightings || [];
    return sec("Where else we saw it", s.length ? '<div class="ph-table-wrap"><table class="ph-table"><thead><tr><th>Source</th><th>First seen</th><th>Times seen</th><th></th></tr></thead><tbody>' + s.map(function (x) {
      var ok = x.url && /^https?:\/\//.test(x.url);
      return "<tr><td>" + esc(x.label) + "</td><td>" + esc(x.ago) + "</td><td>" + esc(x.times_seen) + "</td><td>" + (ok ? '<a href="' + esc(x.url) + '" target="_blank" rel="noopener noreferrer">Open</a>' : "") + "</td></tr>"; }).join("") + "</tbody></table></div>"
      : '<p class="ph-meta">No sightings recorded.</p>');
  }
  function keywordHtml(j) {
    var WHERE = { melbourne_vic: "Melbourne, Victoria", vic_locality: "A Victorian suburb or town", unknown_location_vic_employer: "A Victorian employer (the ad gives no location)" };
    var rules = j.rules || {}, items = [];
    if (j.arm_labels.length) items.push("<li><strong>Job type</strong> " + j.arm_labels.map(esc).join(", ") + (j.tier === "core" ? ' <span class="ph-meta">a core target</span>' : "") + "</li>");
    if (rules.title_keyword) items.push("<li><strong>Title</strong> contains <q>" + esc(rules.title_keyword) + "</q></li>");
    if (rules.location) items.push("<li><strong>Location</strong> " + esc(WHERE[rules.location] || String(rules.location).replace(/_/g, " ")) + "</li>");
    Object.keys(rules).filter(function (k) { return ["title_keyword", "location", "experience_years", "work_rights_pattern"].indexOf(k) < 0; }).forEach(function (k) {
      var v = rules[k]; items.push("<li><strong>" + esc(k.replace(/_/g, " ")) + "</strong> " + esc(typeof v === "string" ? v : JSON.stringify(v)) + "</li>"); });
    (j.flag_reasons || []).forEach(function (f) { items.push('<li><span class="ph-badge ph-badge--' + (f.kind === "warn" ? "warning" : f.kind === "good" ? "success" : "info") + '">' + esc(f.label) + "</span> " + esc(f.why || "") + (f.snippet ? " <mark>" + esc(f.snippet) + "</mark>" : "") + "</li>"); });
    var body = (items.length ? '<ul class="a-hist">' + items.join("") + "</ul>" : '<p class="ph-meta">This job is not one of your matches. It is shown because you searched all jobs.</p>') +
      "<h3>Keyword score</h3><p><strong>" + esc(j.rule_score) + '</strong> / 100</p><ul class="a-top">' + (j.rule_why || []).map(function (w) { var i = w.lastIndexOf(" "); return "<li><span>" + esc(w.slice(0, i)) + "</span><strong>" + esc(w.slice(i + 1)) + "</strong></li>"; }).join("") + "</ul>" +
      '<p class="ph-meta">A simple rule-based score with no AI in it: job type, entry-level, freshness, salary shown, no warning flags, and how many sources list the ad. It only ranks ads the AI has not read yet.</p>';
    return '<details class="ph-card c-block a-sec"' + (j.ai ? "" : " open") + '><summary class="ph-card__body"><strong>Keyword match</strong> <span class="ph-meta">Why the title and listing matched your search words' + (j.ai ? " (the AI fit above is what counts)" : "") + '</span></summary><div class="ph-card__body">' + body + "</div></details>";
  }
  function stateHtml(j) {
    var opts = (j.app_status ? "" : '<option value="" selected disabled>Not saved yet</option>') + META.app_states.map(function (s) { return '<option value="' + s + '"' + (j.app_status === s ? " selected" : "") + ">" + esc(META.states[s] || s) + "</option>"; }).join("");
    return sec("Your notes and status", (j.app_status ? '<label class="a-field"><span class="ph-label">Status</span><select class="ph-select" id="jstatus" data-id="' + j.id + '">' + opts + "</select></label>" : "") +
      '<label class="a-field"><span class="ph-label">Notes <span class="ph-meta">(saving a note also saves the job)</span></span><textarea class="ph-textarea" id="jnotes" rows="3" maxlength="4000" placeholder="Contacts, questions, what to mention">' + esc((j.app || {}).notes || "") + "</textarea></label>" +
      '<p><button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-act="notes" data-id="' + j.id + '">Save notes</button></p>');
  }
  function timelineHtml(j) {
    var ev = j.events || [];
    return sec("Application timeline", ev.length ? '<ol class="a-hist">' + ev.map(function (e) {
      var what = e.kind === "status" || e.kind === "outcome_decided" ? (e.kind === "outcome_decided" ? "Mail outcome: " : "") + (e.from_status ? (META.states[e.from_status] || e.from_status) + " → " : "") + (e.to_status ? (META.states[e.to_status] || e.to_status) : "Created")
        : e.kind === "command" ? "Draft requested" : e.kind === "draft" ? "Draft update" : e.kind === "outcome_proposed" ? "Outcome proposed from mail" : e.kind === "submit_unsure" ? "Submit pressed, no confirmation seen" : (e.kind || "Event");
      return "<li>" + esc(what) + ' <span class="ph-meta" title="' + esc(e.abs || "") + '">' + esc([e.ago, e.actor].filter(Boolean).join(" · ")) + (e.source ? " via " + esc(e.source) : "") + "</span></li>"; }).join("") + "</ol>"
      : '<p class="ph-meta">Nothing yet. Saving, hiding or marking this job applied starts the timeline.</p>');
  }
  function submitAsk(j) {
    var ev = (j.events || [])[0];
    if (!ev || ev.kind !== "submit_unsure" || j.app_status === "applied") return "";
    return '<p class="ph-alert">Did it go through? <button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-act="applied" data-id="' + j.id + '">Mark applied</button></p>';
  }
  function jobHeadHtml(j, d) {
    var status = j.app_status || "", saved = status && status !== "skipped", dr = (d && d.draft) || {};
    var primary = !saved && status !== "skipped" ? '<button type="button" class="ph-btn ph-btn--default" data-act="save" data-id="' + j.id + '">' + icon("bookmark") + "Save</button>" :
      saved && dr.state !== "ready" && dr.state !== "running" ? '<button type="button" class="ph-btn ph-btn--default" data-act="draft" data-id="' + j.id + '">Draft CV + letter</button>' : "";
    var sec_ = [];
    if (/^https?:\/\//i.test(j.url || "")) sec_.push('<a class="ph-btn ph-btn--outline" href="' + esc(j.url) + '" target="_blank" rel="noopener noreferrer">Open the ad</a>');
    if (saved && !primary) sec_.push('<button type="button" class="ph-btn ph-btn--outline" disabled>' + icon("bookmark") + esc(META.states[status] || "Saved") + "</button>");
    if (status === "skipped") sec_.push('<button type="button" class="ph-btn ph-btn--outline" data-act="unhide" data-id="' + j.id + '">Unhide</button>');
    else if (status !== "applied") sec_.push('<button type="button" class="ph-btn ph-btn--outline" data-act="hide" data-id="' + j.id + '">Hide</button>');
    if (status !== "applied" && saved) sec_.push('<button type="button" class="ph-btn ph-btn--outline" data-act="applied" data-id="' + j.id + '">Mark applied</button>');
    if (status === "applied" || status === "interview" || status === "assessment" || status === "offer") sec_.push('<a class="ph-btn ph-btn--outline" href="#interview/' + j.id + '">Interview preparation</a>');
    return '<header class="c-jobhead"><h1 class="c-h1" tabindex="-1">' + esc(j.title) + '</h1><p class="ph-meta"><strong>' + esc(j.company || "Employer not stated") + "</strong> · " + esc(j.where) +
      (j.posted_ago ? " · Posted " + esc(j.posted_ago) : "") + " · " + j.src_labels.length + (j.src_labels.length === 1 ? " source" : " sources") + "</p>" +
      '<p class="jx-verdict">' + esc(verdictLine(j)) + '</p><div class="ph-cluster">' + aiBadge(j) + appBadge(j) + '</div>' + submitAsk(j) + '<div class="ph-cluster a-actions">' + primary + sec_.join("") + "</div></header>";
  }
  function jobMainHtml(d) {
    var j = d.job;
    return heroHtml(j) + jevHtml(d.jev) + draftBox(j, d.draft || {}, d.draft_links || {}) + reportHtml(j) + sec("About the job", adText(j.blocks) + (j.desc_truncated ? '<p class="ph-meta">Description is shortened; open the original for the full text.</p>' : ""));
  }
  function jobSideHtml(j) { return glanceHtml(j) + stateHtml(j) + timelineHtml(j) + seenHtml(j) + keywordHtml(j); }
  function verdictBlock(j) {
    var band = j.score5 == null ? "" : j.score5 >= 4 ? "good" : j.score5 >= 3 ? "warn" : "bad";
    return '<section class="jx-verdictblock"><span class="jx-bigscore" data-band="' + band + '">' + (j.score5 != null ? Number(j.score5).toFixed(1) + "<small>/5</small>" : "–") + '</span><p class="jx-verdict">' + esc(verdictLine(j)) + "</p></section>";
  }
  function actionBar(j, d) {
    var status = j.app_status || "", saved = status && status !== "skipped", dr = (d && d.draft) || {};
    var main = !saved && status !== "skipped" ? '<button type="button" class="ph-btn ph-btn--default" data-act="save" data-id="' + j.id + '">' + icon("bookmark") + "Save</button>" :
      saved && dr.state !== "ready" && dr.state !== "running" ? '<button type="button" class="ph-btn ph-btn--default" data-act="draft" data-id="' + j.id + '">Draft CV + letter</button>' :
      '<button type="button" class="ph-btn ph-btn--default" disabled>' + icon("bookmark") + esc(META.states[status] || "Saved") + "</button>";
    var more = [];
    if (status === "skipped") more.push('<button type="button" data-act="unhide" data-id="' + j.id + '">Unhide</button>'); else if (status !== "applied") more.push('<button type="button" data-act="hide" data-id="' + j.id + '">Hide</button>');
    if (saved && status !== "applied") more.push('<button type="button" data-act="applied" data-id="' + j.id + '">Mark applied</button>');
    if (["applied", "interview", "assessment", "offer"].indexOf(status) >= 0) more.push('<a href="#interview/' + j.id + '">Interview preparation</a>');
    return submitAsk(j) + '<div class="jx-actionbar">' + main + (/^https?:\/\//i.test(j.url || "") ? '<a class="ph-btn ph-btn--outline" href="' + esc(j.url) + '" target="_blank" rel="noopener noreferrer">Open the ad</a>' : "") +
      (more.length ? '<details class="jx-morebtn"><summary class="ph-btn ph-btn--outline" aria-label="More actions">' + icon("ellipsis") + '</summary><div class="jx-morebtn__pop">' + more.join("") + "</div></details>" : "") + "</div>";
  }
  function renderJob(id) {
    api("/api/job/" + id).then(function (d) {
      var j = d.job, dr = d.draft || {};
      if (phone()) {
        setNavbar("Board", "#board", j.title, true);
        view.innerHTML = '<header class="c-jobhead jx-phonehead"><h1 class="c-h1" tabindex="-1">' + esc(j.title) + '</h1><p class="ph-meta"><strong>' + esc(j.company || "Employer not stated") + "</strong> · " + esc(j.where) + (j.posted_ago ? " · Posted " + esc(j.posted_ago) : "") + "</p></header>" +
          verdictBlock(j) + glanceHtml(j) + heroHtml(j) + jevHtml(d.jev) + reportHtml(j) + draftBox(j, dr, d.draft_links || {}) +
          sec("About the job", adText(j.blocks) + (j.desc_truncated ? '<p class="ph-meta">Description is shortened; open the original for the full text.</p>' : "")) + stateHtml(j) + timelineHtml(j) + seenHtml(j) + keywordHtml(j) + actionBar(j, d);
      } else {
        view.innerHTML = '<p><a class="ph-btn ph-btn--ghost ph-btn--sm" href="#board">' + icon("arrow-left") + "Back to Board</a></p>" + jobHeadHtml(j, d) +
          '<div class="a-jobcols"><div>' + jobMainHtml(d) + "</div><div>" + jobSideHtml(j) + "</div></div>";
      }
      document.title = j.title + " - Jobwatch";
      if (dr.state === "running") setTimeout(function () { if (location.hash === "#job/" + id) renderJob(id); }, 5000);
    }).catch(function (e) { view.innerHTML = head("Job") + errorBox(e, true); });
  }

  /* ---------- Jobs table: columns you choose, sortable headers, the same filters, CSV ---------- */
  var T = { sort: "listed", dir: "", page: 1, cols: null };
  var DESC_FIRST = ["fit", "ai_fit", "salary", "listed", "first_seen", "sources", "flags"];
  var ROW_STATUS = { new: "New", seen: "Seen", saved: "Saved", applied: "Applied", closed: "Closed", hidden: "Hidden" };
  function tableCols() {
    if (T.cols) return T.cols;
    var ok = META.table_cols.map(function (c) { return c[0]; }), want = null;
    try { want = JSON.parse(localStorage.getItem("jw-cols") || "null"); } catch (e) { }
    T.cols = (want || []).filter(function (c) { return ok.indexOf(c) >= 0; });
    if (!T.cols.length) T.cols = ["ai_fit", "title", "company", "location", "salary", "listed", "status"];
    return T.cols;
  }
  function saveCols() { try { localStorage.setItem("jw-cols", JSON.stringify(T.cols)); } catch (e) { } }
  function dash() { return '<span class="ph-meta">—</span>'; }
  function cell(key, r) {
    var ai = r.ai;
    if (key === "fit") return '<span title="' + (r.score_src === "ai" ? "AI fit" : "Keyword score (not read by the AI yet)") + ": " + esc((r.score_why || []).join("; ")) + '">' + r.score + "</span>";
    if (key === "ai_fit") return ai && r.score5 != null ? '<span class="jx-fit" title="' + esc(r.score_label) + ". " + esc(ai.reason || "") + '">' + esc(r.score_text) + "</span>" : '<span class="ph-meta" title="The AI has no score for this job yet">—</span>';
    if (key === "archetype") return r.archetype ? esc(r.archetype) : dash();
    if (key === "ai_view") return '<span class="ph-badge ph-badge--' + ({ show: "success", review: "warning", hide: "secondary", pending: "outline" }[r.ai_state] || "outline") + '" title="' + esc(ai ? ai.reason || "" : "The AI has not read this ad yet") + '">' + esc(r.ai_text) + "</span>";
    if (key === "title") return esc(r.title);
    if (key === "company") return esc(r.company || "—");
    if (key === "location") return esc(r.where);
    if (key === "arm") return esc(r.arm_label);
    if (key === "tier") return r.tier === "core" ? '<span class="ph-badge ph-badge--info">Core</span>' : r.tier === "fallback" ? '<span class="ph-badge ph-badge--outline">Fallback</span>' : '<span class="ph-meta">' + esc(TIER[r.tier] || r.tier || "") + "</span>";
    if (key === "sector") return r.sector ? esc(r.sector_label) : dash();
    if (key === "sources") return r.src_labels.map(function (s) { return '<span class="ph-badge ph-badge--outline">' + esc(s) + "</span>"; }).join(" ");
    if (key === "wt") return esc(r.wt ? META.work_types[r.wt] || r.wt : "—");
    if (key === "salary") return r.salary ? esc(r.salary) : dash();
    if (key === "listed") return r.listed_dt ? esc(r.listed_ago) : "—";
    if (key === "first_seen") return esc(r.first_seen_ago);
    if (key === "flags") return ["rights", "fulltime", "experience"].filter(function (w) { return (r.warn || []).indexOf(w) >= 0; }).map(function (w) { return '<span class="ph-badge ph-badge--warning">' + esc(META.warn[w]) + "</span>"; }).join(" ") + (r.entry ? ' <span class="ph-badge ph-badge--success">Entry-level</span>' : "") + (r.is_remote ? ' <span class="ph-badge ph-badge--info">Remote</span>' : "");
    if (key === "status") return '<span class="ph-badge ph-badge--' + (r.status === "saved" || r.status === "applied" ? "success" : r.status === "new" ? "info" : "secondary") + '">' + esc(ROW_STATUS[r.status] || r.status) + "</span>";
    return "";
  }
  function renderTable() {
    var cols = tableCols(), sc = document.getElementById("railBody") ? document.getElementById("railBody").scrollTop : 0;
    if (!F.ai) F.ai = "worth";
    api("/api/table?" + fqs({ sort: T.sort, dir: T.dir, page: T.page })).then(function (d) {
      LAST = { counts: d.counts, saved: d.saved };
      var c = d.counts.ai || {}, prog = d.progress || {}, from = (d.page - 1) * d.size + 1;
      var cur = F.ai === "show" || F.ai === "review" ? "worth" : F.ai;
      var tabs = VIEWS.map(function (v) { return '<button type="button" class="jx-seg__b" role="tab" data-tab="' + v[0] + '" aria-selected="' + (cur === v[0]) + '">' + esc(phone() ? ({ worth: "Worth a look", hide: "Hidden", pending: "Waiting" })[v[0]] : v[1]) + ' <span class="jx-seg__n">' + viewCount(c, v[0]) + "</span></button>"; }).join("");
      var colmenu = META.table_cols.map(function (cc) {
        var on = cols.indexOf(cc[0]) >= 0;
        return '<label class="jx-opt"><input type="checkbox" data-col="' + cc[0] + '"' + (on ? " checked" : "") + (on && cols.length === 1 ? " disabled" : "") + '><span class="jx-opt__l">' + esc(cc[1]) + "</span></label>";
      }).join("");
      var csv = "/table.csv?" + fqs({ sort: T.sort, dir: T.dir });
      var head_ = '<header class="c-head jx-headrow"><div><h1 class="c-h1" tabindex="-1">Jobs</h1><p class="ph-meta" role="status">' + (d.total ? "Showing " + from + "–" + (from + d.rows.length - 1) + " of " + d.total : "0 jobs") + " · " + esc(d.summary) + "</p>" +
        (prog.left > 0 ? '<p class="ph-meta">The AI has read ' + prog.read + " of " + prog.total + " matched ads</p>" : "") + '</div><div class="ph-cluster">' +
        '<details class="jx-menu"><summary class="ph-btn ph-btn--outline">Columns <span class="jx-facet__n">' + cols.length + '</span></summary><div class="jx-menu__pop" role="group" aria-label="Choose columns">' + colmenu + "</div></details>" +
        '<a class="ph-btn ph-btn--outline" href="' + esc(csv) + '" download>' + icon("download") + "Export CSV</a></div></header>";
      var body;
      if (d.rows.length && phone()) {
        body = '<ul class="jx-rowlist">' + d.rows.map(function (r) {
          return '<li><a class="jx-rowlist__row" href="#job/' + r.id + '"><span class="jx-rowlist__main"><strong>' + esc(r.title) + "</strong><span>" + esc(r.company || "—") + (r.where ? " · " + esc(String(r.where).split(",")[0].split(" · ")[0]) : "") + '</span></span><span class="jx-pill-score"' + (r.score5 != null ? ' data-band="' + (r.score5 >= 4 ? "good" : r.score5 >= 3 ? "warn" : "bad") + '"' : "") + ">" + (r.score5 != null ? esc(r.score_text) : "–") + "</span></a></li>"; }).join("") + "</ul>" + pager(d, "tpage");
      } else if (d.rows.length) {
        body = '<div class="ph-table-wrap jx-tablewrap" tabindex="0" role="region" aria-label="Jobs, scrolls sideways on small screens"><table class="ph-table jx-table"><thead><tr>' + cols.map(function (k) {
          var label = META.table_cols.find(function (x) { return x[0] === k; })[1], active = T.sort === k, cur = T.dir || (DESC_FIRST.indexOf(k) >= 0 ? "desc" : "asc");
          return '<th scope="col" aria-sort="' + (active ? (cur === "asc" ? "ascending" : "descending") : "none") + '"><button type="button" class="jx-th" data-sortcol="' + k + '">' + esc(label) + '<span aria-hidden="true">' + (active ? (cur === "asc" ? " ▲" : " ▼") : "") + "</span></button></th>";
        }).join("") + "</tr></thead><tbody>" + d.rows.map(function (r) {
          return "<tr>" + cols.map(function (k, i) {
            var inner = cell(k, r);
            return "<td>" + (k === "title" || (i === 0 && cols.indexOf("title") < 0) ? '<a href="#job/' + r.id + '">' + inner + "</a>" : inner) + "</td>";
          }).join("") + "</tr>";
        }).join("") + "</tbody></table></div>" + pager(d, "tpage");
      } else {
        body = emptyHtml(d);
      }
      var rail = '<details class="jx-rail"' + (matchMedia("(min-width: 900px)").matches ? " open" : "") + '><summary class="jx-rail__sum">Filters' + (facetCount() ? ' <span class="jx-facet__n">' + facetCount() + "</span>" : "") + '</summary><div class="jx-rail__body" id="railBody">' +
        '<div class="jx-rail__search"><label class="a-field"><span class="ph-label">Keywords</span><input class="ph-input" id="bq" type="search" placeholder="Title, company, skills" value="' + esc(F.q) + '" autocomplete="off"></label>' +
        '<label class="a-field"><span class="ph-label">Exclude words</span><input class="ph-input" id="bx" type="text" placeholder="Words to leave out" value="' + esc(F.x) + '" autocomplete="off"></label>' +
        '<label class="jx-check"><input type="checkbox" id="bscope"' + (F.scope === "all" ? " checked" : "") + "><span>Include unmatched jobs</span></label></div>" +
        '<div class="jx-facets">' + facetsHtml(d.counts, true, true) + "</div></div></details>";
      view.innerHTML = head_ + '<div class="jx-seg" role="tablist" aria-label="Agent verdict">' + tabs + "</div>" + chipsHtml() + '<div class="jx-tablegrid"><aside class="jx-tablerail" aria-label="Filters">' + rail + '</aside><section class="jx-tablemain" aria-label="Jobs table">' + body + "</section></div>";
      var rb = document.getElementById("railBody"); if (rb) rb.scrollTop = sc;
    }).catch(function (e) { view.innerHTML = head("Jobs") + errorBox(e, true); });
  }

  /* ---------- Applications ---------- */
  function appliedText(n) { return n == null ? "" : n === 0 ? "Applied today" : n === 1 ? "Applied yesterday" : "Applied " + n + " days ago"; }
  function statusSelect(a) {
    return '<label class="a-field"><span class="ph-sr-only">Change status of ' + esc(a.title) + '</span><select class="ph-select ph-select--sm" data-appstatus="' + a.posting_id + '" aria-label="Change status of ' + esc(a.title) + '">' +
      META.app_states.filter(function (s) { return s !== "drafting" || a.status === "drafting"; }).map(function (s) { return '<option value="' + s + '"' + (s === a.status ? " selected" : "") + ">" + esc(META.states[s] || s) + "</option>"; }).join("") + "</select></label>";
  }
  function followupHtml(a, enabled) {
    var f = a.followup || {};
    if (!f.state || f.state === "inactive") return "";
    var lab = { overdue: "Due", urgent: "Reply due", waiting: "Scheduled", cold: "Consider next steps", unknown: "Check dates" }[f.state] || "Check dates", hist = a.followup_history || { total: 0, items: [] };
    var msg = f.state === "cold" ? "Two follow-ups without a recorded reply. Consider another contact or leave this application waiting. Silence does not mean rejection." :
      f.state === "unknown" ? "Confirm the actual application or communication dates below before scheduling a follow-up. An interview invitation does not confirm that the interview happened." :
      (f.kind === "interview_thankyou" ? "Interview thank-you" : f.kind === "reply" ? "Reply follow-up" : "Application follow-up") + (f.due_on ? " due " + f.due_on : "") + ".";
    var op = a.followup_operation, pid = a.posting_id;
    return '<details class="jx-follow"><summary>Follow-up · ' + lab + (f.due_on ? " · " + esc(f.due_on) : "") + "</summary><p>" + esc(msg) + "</p>" +
      (f.sent_count != null ? "<p>" + f.sent_count + " confirmed follow-ups sent.</p>" : "") +
      (enabled ? '<p><a class="ph-btn ph-btn--outline ph-btn--sm" href="#followup/' + pid + '">Review follow-up draft</a></p>' : "") +
      (hist.items && hist.items.length ? "<details><summary>Recent history (" + hist.total + ")</summary><ul>" + hist.items.map(function (e) { return "<li>" + esc(e.label) + " · " + esc(e.at) + (e.channel ? " · " + esc(e.channel) : "") + "</li>"; }).join("") + "</ul>" + (hist.total > 10 ? "<p>Showing the latest 10 events. Earlier events remain in your application history.</p>" : "") + "</details>" : "") +
      '<div class="jx-form" data-fu="event" data-pid="' + pid + '" data-op="' + esc(op) + '-event"><label class="a-field"><span class="ph-label">What happened?</span><select class="ph-select" data-f="action"><option value="sent">I sent a follow-up</option><option value="response">I received a reply</option><option value="interview_completed">I completed an interview</option><option value="applied_confirmed">I submitted the application</option></select></label>' +
      '<label class="a-field"><span class="ph-label">When (Melbourne time)</span><input class="ph-input" type="datetime-local" data-f="occurred_at"></label>' +
      '<label class="a-field"><span class="ph-label">Channel, if sent</span><select class="ph-select" data-f="channel"><option value="email">Email</option><option value="linkedin">LinkedIn</option><option value="phone">Phone</option><option value="other">Other</option></select></label>' +
      '<label class="jx-check"><input type="checkbox" data-f="owner_confirmed"><span>I confirm this already happened.</span></label><button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-fusave>Record event</button></div>' +
      '<div class="jx-form" data-fu="pin" data-pid="' + pid + '" data-op="' + esc(op) + '-pin"><label class="a-field"><span class="ph-label">Next follow-up date</span><input class="ph-input" type="date" data-f="due_on"></label><button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-fusave>Set reminder date</button></div>' +
      '<div class="jx-form" data-fu="clear_pin" data-pid="' + pid + '" data-op="' + esc(op) + '-clear"><button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-fusave>Use standard timing</button></div></details>';
  }
  function agenticHtml(item, a, inCard) {
    if (!item) return "";
    var st = item.status === "ready" ? "Documents ready" : nice(String(item.status || ""));
    st = st.charAt(0).toUpperCase() + st.slice(1);
    var dims = item.dimensions ? Object.keys(item.dimensions).map(function (n) { return "<div><dt>" + esc(nice(n)) + "</dt><dd>" + esc(item.dimensions[n]) + "/5</dd></div>"; }).join("") : "";
    return '<article class="jx-agentic" aria-label="Agent progress for ' + esc(a.title) + '">' + (inCard ? "" : '<h3><a href="#job/' + a.posting_id + '">' + esc(a.title) + "</a></h3>") + "<p><span class=\"ph-badge ph-badge--" + (item.status === "ready" ? "success" : item.status === "held" ? "warning" : "info") + '">' + esc(st) + "</span>" + (item.global_score ? " <strong>" + esc(item.global_score) + "/5</strong>" : "") + "</p>" +
      (item.reason || dims ? '<details class="jx-agentic__more"><summary>Why</summary>' + (item.reason ? "<p>" + esc(item.reason) + "</p>" : "") + (dims ? '<dl class="a-dl">' + dims + "</dl>" : "") + "</details>" : "") +
      (item.claim_count ? "<p><strong>" + item.verified_claims + " verified claim" + (item.verified_claims !== 1 ? "s" : "") + "</strong> of " + item.claim_count + "</p>" : "") +
      (item.hold || item.hold_count ? '<p><span class="ph-badge ph-badge--warning">Hold</span> ' + (item.hold ? esc(item.hold) : item.hold_count + " item" + (item.hold_count !== 1 ? "s" : "") + " need your answer.") + "</p>" : "") +
      (item.has_evaluation ? '<p><a href="/job/' + a.posting_id + '/evaluation">Read the full evaluation</a></p>' : "") + "</article>";
  }
  function appCard(a, enabled) {
    var f = a.files;
    return '<li class="jx-app' + '"><h3 class="jx-app__t"><a href="#job/' + a.posting_id + '">' + esc(a.title) + "</a></h3>" +
      '<p class="ph-meta">' + esc(a.company || "") + (a.where ? " · " + esc(a.where) : "") + "</p>" +
      (a.days_applied != null ? '<p class="ph-meta">' + appliedText(a.days_applied) + "</p>" : "") +
      (a.event_text ? '<p title="' + esc(a.last_abs) + '">' + esc(a.event_text) + ' <span class="ph-meta">· ' + esc(a.last_ago) + "</span></p>" : "") +
      agenticHtml(a.agentic, a, true) +
      '<p class="ph-cluster"><a class="ph-btn ph-btn--outline ph-btn--sm" href="#interview/' + a.posting_id + '">Interview prep</a>' +
      (a.draft_state === "drafting" ? '<span class="ph-badge ph-badge--info">Drafting…</span>' : f && (f.cv || f.letter || f.summary) ? (f.cv ? '<a class="ph-btn ph-btn--outline ph-btn--sm" href="' + esc(f.cv) + '" target="_blank" rel="noopener">CV</a>' : "") + (f.letter ? '<a class="ph-btn ph-btn--outline ph-btn--sm" href="' + esc(f.letter) + '" target="_blank" rel="noopener">Letter</a>' : "") + (f.summary ? '<a class="ph-btn ph-btn--outline ph-btn--sm" href="' + esc(f.summary) + '" target="_blank" rel="noopener">Summary</a>' : "") : a.draft_state === "failed" ? '<span class="ph-badge ph-badge--warning">Draft failed</span>' : "") + "</p>" +
      followupHtml(a, enabled) + statusSelect(a) + "</li>";
  }
  function emptyState(ic, title, line, buttons) {
    return '<div class="jx-emptystate"><span class="jx-emptystate__ic">' + icon(ic) + '</span><h2>' + esc(title) + '</h2><p class="ph-meta">' + esc(line) + '</p><div class="ph-cluster">' + buttons + "</div></div>";
  }
  function drawApplications(d) {
    if (phone() && !d.total) { view.innerHTML = head("Applications") + emptyState("circle-check", "No applications yet", "Save a job on the Board and it shows up here. Jobwatch fills the form and stops at Submit for you.", '<a class="ph-btn ph-btn--default" href="#board">Browse the board</a><a class="ph-btn ph-btn--outline" href="#interview">Prepare an interview from a job URL</a>'); return; }
    var cols = d.cols.map(function (c) {
      return '<section class="jx-col" aria-label="' + esc(c[1]) + '"><header class="jx-col__h"><h2>' + esc(c[1]) + '</h2><span class="jx-col__n">' + c[2].length + "</span></header>" +
        (c[2].length ? '<ul class="jx-applist">' + c[2].map(function (a) { return appCard(a, d.followup_drafting_enabled); }).join("") + "</ul>" : '<p class="ph-meta">Nothing here yet</p>') + "</section>";
    }).join("");
    view.innerHTML = '<header class="c-head"><h1 class="c-h1" tabindex="-1">Applications</h1><p class="ph-meta">' + (d.total ? d.total + " tracked" : "Nothing tracked yet") + "</p></header>" +
      '<p class="jx-note">Jobwatch writes your CV and letter and fills in the application form for you. It stops at the Submit button: check the form, then press Submit yourself or choose Submit this application. Jobwatch sees the confirmation page and moves the job to Applied on its own; if it is not sure, the job asks "Did it go through?".</p><p><a class="ph-btn ph-btn--outline ph-btn--sm" href="#interview">Prepare an interview from a job URL</a></p>' +
      (d.total ? '<div class="jx-kanban">' + cols + "</div>" : '<div class="jx-empty"><p class="jx-empty__t">No applications yet</p><p class="ph-meta">Save or draft a job on the board and it will appear here, ready to move along as things happen.</p><p><a class="ph-btn ph-btn--default" href="#board">Browse the board</a></p></div>') +
      (d.closed.length ? '<details class="jx-closed"><summary>Closed (' + d.closed.length + ')</summary><p class="ph-meta">Rejected, withdrawn and hidden. Change the status to bring one back.</p><ul class="jx-closedlist">' + d.closed.map(function (a) {
        return '<li><span class="ph-badge ph-badge--' + (a.status === "rejected" ? "destructive" : "secondary") + '">' + esc(META.states[a.status] || a.status) + '</span><span class="jx-closedlist__main"><a href="#job/' + a.posting_id + '">' + esc(a.title) + '</a> <span class="ph-meta">' + esc(a.company || "") + '</span></span><span class="ph-meta" title="' + esc(a.updated_abs) + '">' + esc(a.updated_ago) + "</span>" + statusSelect(a) + "</li>"; }).join("") + "</ul></details>" : "");
  }
  function renderApplications() { api("/api/applications").then(drawApplications).catch(function (e) { view.innerHTML = head("Applications") + errorBox(e, true); }); }

  /* ---------- Inbox ---------- */
  var TONE = { offer: "success", interview: "info", assessment: "warning", rejected: "destructive", applied: "secondary" };
  function renderInbox() { api("/api/inbox").then(drawInbox).catch(function (e) { view.innerHTML = head("Inbox") + errorBox(e, true); }); }
  function drawInbox(d, flash) {
    if (phone() && !d.open.length && !d.closed.length) { view.innerHTML = head("Inbox") + emptyState("message-square-warning", "Nothing to review", "Jobwatch reads your mail every 2 hours after you mark a job applied, and suggestions show up here.", ""); return; }
    view.innerHTML = '<header class="c-head"><h1 class="c-h1" tabindex="-1">Inbox</h1><p class="ph-meta">' + (d.open.length ? d.open.length + " waiting for you" : "All caught up") + "</p></header>" +
      '<p class="jx-note">jobwatch reads your mail (read-only) and suggests what each reply means, but nothing changes on your applications until you approve it here.</p>' +
      (flash ? '<p class="ph-alert ph-alert--success" role="status"><span>' + esc(String(flash).replace(/^#\d+ /, "")) + "</span></p>" : "") +
      (d.open.length ? '<ul class="a-list" aria-label="Suggestions waiting for review">' + d.open.map(function (p) {
        var shown = (p.proposed_status === "offer" ? p.flags_list.filter(function (x) { return x !== "offer_review"; }) : p.flags_list), lab = p.ev_flag_labels;
        return '<li class="ph-card"><div class="ph-card__body"><div class="ph-cluster"><span class="ph-badge ph-badge--' + (TONE[p.proposed_status] || "secondary") + '">' + esc(META.states[p.proposed_status] || nice(p.proposed_status)) + "</span></div>" +
          '<h2 class="jx-ib__job">' + (p.posting_id ? '<a href="#job/' + p.posting_id + '">' + esc(p.title || "Unknown job") + "</a>" : esc(p.title || "Unknown job")) + (p.company ? ' <span class="ph-meta">· ' + esc(p.company) + "</span>" : "") + "</h2>" +
          (p.proposed_status === "offer" ? '<p class="ph-alert ph-alert--warning"><span><strong>This looks like an offer: please review it yourself</strong> before approving. jobwatch only records the status; it never replies.</span></p>' : "") +
          "<p><strong>Subject</strong> " + esc(p.subject || "(no subject)") + "</p>" +
          '<p class="ph-meta">' + [p.from_addr ? "From " + esc(p.from_addr) : "", p.mailbox ? "Mailbox " + esc(p.mailbox) : "", p.received_at ? "Received " + esc(p.received_ago) : "", p.confidence != null ? Math.round(p.confidence * 100) + "% sure" : "", p.method ? (p.method === "llm" ? "read by AI" : p.method === "rules" ? "matched by rules" : esc(p.method)) : ""].filter(Boolean).join(" · ") + "</p>" +
          (p.evidence ? '<blockquote class="a-quote">' + esc(p.evidence) + "</blockquote>" : "") +
          (shown.length ? '<p class="ph-cluster">' + shown.map(function (f) { return '<span class="ph-badge ph-badge--warning">' + esc(META.flag_text[f] || lab[p.flags_list.indexOf(f)] || nice(f)) + "</span>"; }).join("") + "</p>" : "") +
          (p.app_status ? "<p>Approve moves it from <strong>" + esc(META.states[p.app_status] || p.app_status) + "</strong> to <strong>" + esc(META.states[p.proposed_status] || p.proposed_status) + "</strong>.</p>" : "") +
          '<div class="ph-cluster"><button type="button" class="ph-btn ph-btn--default" data-decide="approve" data-pid="' + p.id + '">Approve</button><button type="button" class="ph-btn ph-btn--outline" data-decide="reject" data-pid="' + p.id + '">Reject</button></div></div></li>';
      }).join("") + "</ul>" : '<div class="jx-empty"><p class="jx-empty__t">Nothing to review.</p><p class="ph-meta">jobwatch reads your mail every 2 hours, 7am to 9pm, after you mark a job applied.</p></div>') +
      (d.closed.length ? '<details class="jx-closed"><summary>History (' + d.closed.length + ')</summary><ul class="jx-closedlist">' + d.closed.map(function (p) {
        return '<li><span class="ph-badge ph-badge--' + (p.status === "approved" ? "success" : "secondary") + '">' + esc(nice(p.status)) + '</span><span class="ph-badge ph-badge--' + (TONE[p.proposed_status] || "secondary") + '">' + esc(META.states[p.proposed_status] || nice(p.proposed_status)) + '</span><span class="jx-closedlist__main">' +
          (p.posting_id ? '<a href="#job/' + p.posting_id + '">' + esc(p.title || "Unknown job") + "</a>" : esc(p.title || "Unknown job")) + (p.company ? ' <span class="ph-meta">· ' + esc(p.company) + "</span>" : "") + (p.subject ? ' <span class="ph-meta">' + esc(p.subject) + "</span>" : "") + '</span><span class="ph-meta">' + esc(p.when_ago) + "</span></li>"; }).join("") + "</ul></details>" : "");
  }
  /* ---------- Chat: one centred column on the page, like a reading app ---------- */
  var C = { busy: false, skip: [], change: "" };
  function askHtml(a) {
    if (!a) return "";
    var opts = a.verify
      ? '<button type="button" class="ph-btn ph-btn--default ph-btn--sm" data-qa="keep">Yes, that\'s right</button><button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-qa="change">Change it</button>'
      : (a.options || []).map(function (o, i) { return '<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-qa="' + i + '">' + esc(o[0]) + "</button>"; }).join("") +
        '<button type="button" class="ph-btn ph-btn--ghost ph-btn--sm" data-qa="skip">Not now</button>';
    return '<section class="ph-card jx-ask" data-field="' + esc(a.id) + '"><div class="ph-card__body"><p class="ph-meta">Quick question' + (a.left ? " · " + a.left + " left" : "") + '</p><p class="jx-ask__q">' + esc(a.question) + "</p>" +
      '<div class="ph-cluster">' + opts + "</div>" +
      (a.verify ? "" : '<div class="jx-ask__other"><label class="ph-sr-only" for="qaother">Your answer</label><input class="ph-input" id="qaother" maxlength="300" placeholder="' + ((a.options || []).length ? "Other: type your own answer" : "Type your answer") + '"><button type="button" class="ph-btn ph-btn--default ph-btn--sm" data-qa="other">Save</button></div>') +
      "</div></section>";
  }
  function answerAsk(choice) {
    var box = document.querySelector(".jx-ask"); if (!box) return;
    var other = document.getElementById("qaother");
    api("/api/chat/ask", { field: box.dataset.field, choice: choice, other: other && choice === "other" ? other.value : "", skip: C.skip })
      .then(function (r) { C.skip = r.skip || C.skip; C.change = r.change || ""; renderChat(); }).catch(fail);
  }
  function renderChat() {
    api("/api/chat?skip=" + encodeURIComponent(C.skip.join(",")) + (C.change ? "&change=" + encodeURIComponent(C.change) : "")).then(function (d) {
      var msgs = (d.messages || []).filter(function (m) { return String(m.text || "").trim(); });
      var notices = msgs.filter(function (m) { return m.notice === "error"; }), talk = msgs.filter(function (m) { return m.notice !== "error"; });
      var nHtml = notices.length ? '<details class="jx-notices"><summary class="ph-btn ph-btn--outline ph-btn--sm">' + icon("circle-alert") + notices.length + " pipeline notice" + (notices.length > 1 ? "s" : "") + "</summary><ul>" +
          notices.map(function (m) { return "<li>" + esc(noticeWords(m.text)) + "</li>"; }).join("") + "</ul></details>" : "";
      view.innerHTML = '<div class="jx-chat"><div class="jx-chat__headrow"><h1 class="c-h1 jx-chat__title" tabindex="-1">Chat</h1>' + (phone() ? nHtml : "") + "</div>" +
        '<div class="jx-chat__log" id="clog" role="log" aria-live="polite"><ul class="a-msgs" id="cmsgs">' + talk.map(msgHtml).join("") + "</ul>" +
        (talk.length ? "" : '<p class="jx-chat__greet">Ask about your jobs.</p>') + "</div>" +
        '<div class="jx-chat__foot">' + (phone() ? "" : nHtml) + askHtml(d.ask) +
        (talk.length ? "" : '<div class="ph-cluster a-chips">' + d.suggestions.map(function (s) { return '<button type="button" class="ph-btn ph-btn--outline ph-btn--sm" data-ask="' + esc(s) + '">' + esc(s) + "</button>"; }).join("") + "</div>") +
        '<form class="a-compose" id="cform"><label class="ph-sr-only" for="cin">Message</label><textarea class="ph-textarea" id="cin" rows="1" placeholder="Ask about a job"></textarea>' +
        '<button type="submit" class="ph-btn ph-btn--default ph-btn--icon" aria-label="Send">' + icon("send") + "</button></form>" +
        '<p class="jx-chat__hint">Enter to send, Shift and Enter for a new line. Nothing is sent to an employer from here.</p></div></div>';
      window.scrollTo(0, document.body.scrollHeight);
      refreshNav("chat");
    }).catch(function (e) { view.innerHTML = head("Chat") + errorBox(e, true); });
  }
  function msgHtml(m) {
    if (m.role === "user") return '<li class="jx-msg jx-msg--me"><p>' + esc(m.text) + "</p></li>";
    if (m.notice === "ready") return '<li class="ph-alert ph-alert--success"><span>' + esc(m.text) + "</span>" + (m.job ? ' <a class="ph-btn ph-btn--outline ph-btn--sm" href="#job/' + esc(m.job) + '">Open job</a>' : "") + "</li>";
    return '<li class="jx-msg jx-msg--bot"><div class="a-prose">' + prose(chatWords(m.text)) + '</div><p class="ph-meta">' + esc(m.time || "") + "</p></li>";
  }
  function send(text) {
    text = String(text || "").trim();
    if (!text || C.busy) return;
    C.busy = true;
    var list = document.getElementById("cmsgs");
    list.insertAdjacentHTML("beforeend", msgHtml({ role: "user", text: text }) + '<li class="jx-msg jx-msg--bot" id="cwait"><p class="ph-meta" aria-busy="true">Thinking…</p></li>');
    window.scrollTo(0, document.body.scrollHeight);
    api("/api/chat", { text: text }).then(function (d) {
      var w = document.getElementById("cwait"); if (w) w.outerHTML = msgHtml({ role: "assistant", text: d.reply, time: "now" });
    }).catch(function (e) {
      var w = document.getElementById("cwait"); if (w) w.outerHTML = '<li class="ph-alert ph-alert--error"><span>' + esc(e.message) + " Your message is saved.</span></li>";
    }).then(function () { C.busy = false; window.scrollTo(0, document.body.scrollHeight); });
  }

  /* ---------- Insights ---------- */
  function num(n) { return Number(n || 0).toLocaleString("en-US"); }
  function pctOf(a, b) { return b ? Math.round(100 * a / b) : 0; }
  function pctNum(x, d) {   // same half-to-even rounding as the classic page (6.25 -> 6.2)
    var v = x * 100 * (d ? 10 : 1), f = Math.floor(v), r = Math.abs(v - f - .5) < 1e-9 ? (f % 2 === 0 ? f : f + 1) : Math.round(v);
    return (d ? (r / 10).toFixed(1) : String(r)) + "%";
  }
  function barRow(label, value, pct, tier) {
    return '<li class="jx-bar"><span class="jx-bar__l">' + esc(label) + (tier ? ' <span class="ph-badge ph-badge--' + (tier === "core" ? "info" : "outline") + '">' + esc(tier) + "</span>" : "") + '</span><span class="jx-bar__v">' + value + '</span><span class="jx-bar__t" aria-hidden="true"><span style="width:' + pct + '%"></span></span></li>';
  }
  function insCard(id, title, sub, body, wide) {
    return '<section class="ph-card jx-ins' + (wide ? " jx-ins--wide" : "") + '" aria-labelledby="' + id + '"><div class="ph-card__body"><h2 id="' + id + '">' + esc(title) + "</h2>" + (sub ? '<p class="ph-meta">' + sub + "</p>" : "") + body + "</div></section>";
  }
  function dayLabel(iso, withWeek) {
    var p = String(iso).split("-"), d = new Date(+p[0], +p[1] - 1, +p[2]);
    return d.toLocaleDateString("en-AU", withWeek ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short" });
  }
  function renderInsights() {
    Promise.all([api("/api/insights"), api("/api/board?ai=hide").catch(function () { return null; })]).then(function (both) {
      var ins = both[0], rd = both[1];
      var t = ins.totals || {}, cap = 12, ser = (ins.series || []).slice(), count;
      while (ser.length > 7 && !ser[0][1]) ser.shift();
      count = ser.length;
      var mx = 1, peak = null, total = 0;
      ser.forEach(function (s) { total += s[1]; if (s[1] > mx || (peak === null && s[1] > 0)) { mx = s[1]; peak = s[0]; } });
      var kpi = [["Postings seen", t.postings], ["Matches, all time", t.matches]].concat(t.matches_30d !== t.matches ? [["Matches, 30 days", t.matches_30d]] : []).concat([["Matches, 7 days", t.matches_7d], ["Employers hiring now", t.employers_live]]);
      var chart = total ? '<figure class="jx-fig"><svg class="jx-chart" viewBox="0 0 ' + count * 20 + ' 100" preserveAspectRatio="none" role="img" aria-label="Bar chart of new matches per day over the last ' + count + " days. " + total + " in total, busiest day " + esc(dayLabel(peak)) + " with " + mx + '."><title>New matches per day, last ' + count + " days</title>" +
        ser.map(function (s, i) { var h = s[1] ? Math.round(s[1] / mx * 96 * 10) / 10 : 1; return '<rect class="jx-col' + (i < count - 7 ? " is-old" : "") + (s[1] ? "" : " is-zero") + '" x="' + (i * 20 + 3) + '" y="' + (100 - h) + '" width="14" height="' + h + '"><title>' + esc(dayLabel(s[0], true)) + ": " + s[1] + " new " + (s[1] === 1 ? "match" : "matches") + "</title></rect>"; }).join("") + "</svg>" +
        '<div class="jx-axis" aria-hidden="true"><span>' + esc(dayLabel(ser[0][0])) + "</span><span>" + esc(dayLabel(ser[Math.floor(count / 2)][0])) + "</span><span>Today</span></div>" +
        '<figcaption class="ph-meta">' + total + " new " + (total === 1 ? "match" : "matches") + " in " + count + " days. Busiest day: " + esc(dayLabel(peak, true)) + " with " + mx + ".</figcaption></figure>" : '<p class="ph-meta">No new matches in the last ' + count + " days. The chart fills in as jobwatch finds them.</p>";
      var reading = "";
      if (rd && rd.progress && rd.progress.total) {
        var pg = rd.progress, hw = rd.counts.why || {};
        reading = insCard("i-read", "Is the AI getting through them?", "", '<p><strong>' + pg.read + " of " + pg.total + "</strong> matched ads read" + (pg.left ? ", " + pg.left + " still waiting" : "") + '.</p><ul class="jx-bars">' + barRow("Read", pg.read, pctOf(pg.read, pg.total)) + "</ul>" +
          (Object.keys(hw).length ? '<h3>Why the AI hid jobs</h3><ul class="jx-bars">' + Object.keys(hw).sort(function (a, b) { return hw[b] - hw[a]; }).slice(0, 8).map(function (k) { return barRow((META.hide_labels || {})[k] || nice(k), hw[k], pctOf(hw[k], hw[Object.keys(hw).sort(function (a, b) { return hw[b] - hw[a]; })[0]])); }).join("") + "</ul>" : ""), true);
      }
      function list(rows, fn, word) { return rows.length ? '<ul class="jx-bars">' + rows.slice(0, cap).map(fn).join("") + "</ul>" + (rows.length > cap ? '<p class="ph-meta">+ ' + (rows.length - cap) + " smaller " + word + "</p>" : "") : '<p class="ph-meta">No matches yet.</p>'; }
      var rm = (ins.remote || {}).matches || [0, 0], ra = (ins.remote || {}).all || [0, 0];
      function pd(a, b) { return b ? (100 * a / b).toFixed(1) : "0.0"; }
      var cb = ins.callbacks || {}, allp = cb._all, cbHtml;
      if (!allp || !allp.n) cbHtml = '<p class="ph-meta">No applications yet: callback rates appear after you have applied to at least 10 jobs. Until then the starting guess is ' + pctNum(ins.prior_mean, 1) + ".</p>";
      else {
        var hi = 0.2; Object.keys(cb).forEach(function (k) { if (cb[k].hdi[1] > hi) hi = cb[k].hdi[1]; });
        var axis = Math.ceil(hi * 10) / 10, order = ["_all"].concat(Object.keys(cb).filter(function (k) { return k !== "_all"; }));
        cbHtml = (allp.n < 10 ? '<p class="ph-meta">Only ' + allp.n + (allp.n === 1 ? " application" : " applications") + " so far, so these rates lean on the starting guess of " + pctNum(ins.prior_mean, 1) + " and will firm up as you apply to more jobs.</p>" : "") +
          '<div class="ph-table-wrap"><table class="ph-table"><thead><tr><th>Job type</th><th>Applied</th><th>Callbacks</th><th>Rate</th><th>Likely range (95%)</th></tr></thead><tbody>' + order.map(function (k) {
            var p = cb[k];
            return "<tr><th scope=\"row\">" + (k === "_all" ? "All job types" : esc(nice(k))) + (p.n < 10 && k !== "_all" ? ' <span class="ph-badge ph-badge--outline">small sample</span>' : "") + "</th><td>" + p.n + "</td><td>" + p.successes + "</td><td><strong>" + pctNum(p.mean, 1) + "</strong></td><td>" +
              '<span class="jx-range" aria-hidden="true"><span class="jx-range__prior" style="left:' + (ins.prior_mean / axis * 100).toFixed(1) + '%"></span><span class="jx-range__span" style="left:' + (p.hdi[0] / axis * 100).toFixed(1) + "%;width:" + ((p.hdi[1] - p.hdi[0]) / axis * 100).toFixed(1) + '%"></span><span class="jx-range__dot" style="left:' + (p.mean / axis * 100).toFixed(1) + '%"></span></span> ' + pctNum(p.hdi[0]) + " to " + pctNum(p.hdi[1]) + "</td></tr>"; }).join("") + "</tbody></table></div>" +
          '<p class="ph-meta">The dashed line marks the starting guess (' + pctNum(ins.prior_mean, 1) + "), the dot is the current estimate and the bar is the range it probably sits in. The scale runs from 0 to " + pctNum(axis) + ".</p>";
      }
      var reddit = ins.chatter_total ? '<p class="ph-meta">' + ins.chatter_total + (ins.chatter_total === 1 ? " post" : " posts") + " about the job market in the last 30 days" + (ins.hiring_posts ? ", plus " + ins.hiring_posts + " hiring " + (ins.hiring_posts === 1 ? "post" : "posts") : "") + '.</p><div class="a-grid2"><div><h3>Themes</h3>' +
        (ins.themes.length ? '<ul class="jx-bars">' + ins.themes.slice(0, cap).map(function (x) { return barRow(nice(x[0]).replace(/^Ai /, "AI "), x[1], pctOf(x[1], ins.themes[0][1])); }).join("") + "</ul>" : '<p class="ph-meta">No themes picked out yet.</p>') +
        (ins.by_subreddit.length ? '<p class="ph-cluster"><span class="ph-meta">From:</span>' + ins.by_subreddit.slice(0, 6).map(function (s) { return '<span class="ph-badge ph-badge--outline">r/' + esc(s[0]) + " " + s[1] + "</span>"; }).join("") + "</p>" : "") + "</div><div><h3>Top posts</h3>" +
        (ins.reddit_top.length ? "<ol>" + ins.reddit_top.map(function (r) { return "<li>" + (/^https?:\/\//.test(r.url || "") ? '<a href="' + esc(r.url) + '" target="_blank" rel="noopener noreferrer">' + esc(r.title) + "</a>" : esc(r.title)) + ' <span class="ph-meta">r/' + esc(r.subreddit) + (r.score != null ? " · " + r.score + " points" : "") + (r.comments != null ? " · " + r.comments + " comments" : "") + "</span></li>"; }).join("") + "</ol>" : '<p class="ph-meta">No standout posts yet.</p>') + "</div></div>"
        : '<p class="ph-meta">No Reddit chatter collected in the last 30 days. This section fills in when the Reddit collector has run.</p>';
      view.innerHTML = '<header class="c-head"><h1 class="c-h1" tabindex="-1">Insights</h1><p class="ph-meta">What jobwatch has found, and what is working.</p></header>' +
        '<ul class="jx-kpis" aria-label="Totals">' + kpi.map(function (k) { return '<li class="ph-card jx-kpi"><strong>' + num(k[1]) + '</strong><span class="ph-meta">' + k[0] + "</span></li>"; }).join("") + "</ul>" +
        reading + insCard("i-day", "New matches per day", "Last " + count + " days, Melbourne time. The darker bars are the last 7 days.", chart, true) +
        '<div class="jx-insgrid">' +
        insCard("i-arm", "By job type", "All matches. Core types are the ones you asked for; fallback types are backups.", list(ins.by_arm, function (x) { return barRow(x[3], x[2], pctOf(x[2], ins.by_arm[0][2]), x[1]); }, "job types")) +
        insCard("i-src", "By source", "Where each match was first found.", list(ins.by_src, function (x) { return barRow(x[2], x[1], pctOf(x[1], ins.by_src[0][1])); }, "sources")) +
        insCard("i-sec", "By sector", "Matches grouped by the employer's sector in the registry.", list(ins.by_sector, function (x) { return barRow(String(x[2]).replace(/^Not in registry$/i, "Outside the employer list"), x[1], pctOf(x[1], ins.by_sector[0][1])); }, "sectors")) +
        insCard("i-emp", "Busiest employers", "Postings seen in the last 30 days. The green part is how many matched you.", ins.top.length ? '<ul class="jx-bars">' + ins.top.slice(0, cap).map(function (x) {
          return '<li class="jx-bar"><span class="jx-bar__l">' + esc(x[0]) + '</span><span class="jx-bar__v">' + x[1] + ' <span class="ph-meta">· ' + x[2] + (x[2] === 1 ? " match" : " matches") + '</span></span><span class="jx-bar__t" aria-hidden="true"><span style="width:' + pctOf(x[1], ins.top[0][1]) + '%"></span><span class="jx-bar__m" style="width:' + pctOf(x[2], ins.top[0][1]) + '%"></span></span></li>'; }).join("") + "</ul>" : '<p class="ph-meta">No postings in the last 30 days.</p>') +
        insCard("i-rem", "Remote share", "How many jobs are remote, among your matches and among everything seen.", '<ul class="jx-bars">' + barRow("Your matches", pd(rm[0], rm[1]) + "% · " + rm[0] + " of " + num(rm[1]), pd(rm[0], rm[1])) + barRow("All postings", pd(ra[0], ra[1]) + "% · " + ra[0] + " of " + num(ra[1]), pd(ra[0], ra[1])) + "</ul>") +
        "</div>" + insCard("i-cb", "Callback rate", "A callback is an assessment, interview or offer after you applied. Estimated per job type, with the likely range.", cbHtml, true) +
        insCard("i-red", "Reddit chatter", "", reddit, true);
    }).catch(function (e) { view.innerHTML = head("Insights") + errorBox(e, true); });
  }

  /* ---------- Sources ---------- */
  var SR = { sector: "", enabled: "" };
  function renderSources() {
    var p = new URLSearchParams(); if (SR.sector) p.set("sector", SR.sector); if (SR.enabled) p.set("enabled", SR.enabled);
    api("/api/sources?" + p).then(function (d) {
      var rag = { ok: "success", warn: "warning", bad: "destructive" }, ragLabel = { ok: "OK", warn: "Check", bad: "Failing" };
      var n = { ok: 0, warn: 0, bad: 0 }; d.health.forEach(function (h) { n[h.rag] = (n[h.rag] || 0) + 1; });
      function trunc(s, k) { return s.length > k ? s.slice(0, k - 1) + "…" : s; }
      var dt = function (v) { return v == null ? "—" : v; };
      view.innerHTML = '<header class="c-head"><h1 class="c-h1" tabindex="-1">Sources</h1><p class="ph-meta">Where jobs come from, and whether each source is working.</p></header>' +
        '<section aria-labelledby="src-h"><div class="jx-sechead"><h2 id="src-h">Collector health</h2><p role="status"><strong>' + d.health.length + ' sources:</strong> <span class="ph-badge ph-badge--success">' + n.ok + ' ok</span> <span class="ph-badge ph-badge--warning">' + n.warn + ' warn</span> <span class="ph-badge ph-badge--destructive">' + n.bad + " bad</span></p></div>" +
        (d.health.length ? '<div class="ph-table-wrap jx-tablewrap"><table class="ph-table"><caption class="ph-sr-only">Health of each collector, failing ones first</caption><thead><tr><th scope="col">Source</th><th scope="col">State</th><th scope="col">Last run</th><th scope="col">Last ok</th><th scope="col">Found</th><th scope="col">Latency</th><th scope="col">Fails in a row</th><th scope="col">Last error</th></tr></thead><tbody>' + d.health.map(function (h) {
          return '<tr><th scope="row" title="' + esc(h.collector) + '">' + esc(h.label) + '</th><td><span class="ph-badge ph-badge--' + (rag[h.rag] || "outline") + '">' + ragLabel[h.rag] + "</span></td><td>" + esc(h.last_status || "—") + "</td><td>" + (h.last_ok_at ? esc(h.last_ok_ago) : '<span class="ph-meta">never</span>') + "</td><td>" + esc(dt(h.last_count)) + "</td><td>" +
            (h.last_latency_ms != null ? (h.last_latency_ms >= 1000 ? (h.last_latency_ms / 1000).toFixed(1) + " s" : h.last_latency_ms + " ms") : "—") + "</td><td>" + (h.consecutive_failures ? "<strong>" + h.consecutive_failures + "</strong>" : "0") + "</td><td>" +
            (h.last_error ? '<span title="' + esc(h.last_error) + '">' + esc(trunc(h.last_error, 90)) + "</span>" : '<span class="ph-meta">none</span>') + "</td></tr>"; }).join("") + "</tbody></table></div>"
          : '<div class="jx-empty"><p class="jx-empty__t">No collector has run yet.</p><p class="ph-meta">Health shows up after the first run.</p></div>') + "</section>" +
        '<section aria-labelledby="emp-h"><div class="jx-sechead"><h2 id="emp-h">Employers watched</h2><p class="ph-meta">Watched means jobwatch checks that employer\'s own careers system directly, not only the job boards. <strong>Live</strong> counts postings seen in the last 7 days and <strong>Matches</strong> those that fit your job types. Verified counts come from the last time the registry entry was checked.</p></div>' +
        '<div class="jx-tools"><label class="a-field"><span class="ph-label">Sector</span><select class="ph-select" id="srsector"><option value="">All sectors</option>' + d.sectors.map(function (s) { return '<option value="' + esc(s) + '"' + (s === SR.sector ? " selected" : "") + ">" + esc(nice(s)) + "</option>"; }).join("") + "</select></label>" +
        '<label class="a-field"><span class="ph-label">Checking</span><select class="ph-select" id="srenabled"><option value="">Enabled and disabled</option><option value="1"' + (SR.enabled === "1" ? " selected" : "") + '>Enabled only</option><option value="0"' + (SR.enabled === "0" ? " selected" : "") + ">Disabled only</option></select></label>" +
        (SR.sector || SR.enabled ? '<button type="button" class="ph-btn ph-btn--ghost" data-srclear>Clear</button>' : "") + '<span class="ph-meta" role="status">' + d.employers.length + (d.employers.length === 1 ? " employer" : " employers") + "</span></div>" +
        (d.employers.length ? '<div class="ph-table-wrap jx-tablewrap"><table class="ph-table"><caption class="ph-sr-only">Employer registry</caption><thead><tr><th scope="col">Employer</th><th scope="col">Sector</th><th scope="col">Provider</th><th scope="col">Checking</th><th scope="col">Live</th><th scope="col">Matches</th><th scope="col" title="Postings counted when the entry was verified">Verified</th><th scope="col" title="Verified postings in Australia">AU</th><th scope="col" title="Verified postings in Victoria">VIC</th><th scope="col">Verified on</th><th scope="col">Notes</th></tr></thead><tbody>' + d.employers.map(function (e) {
          return '<tr><th scope="row">' + esc(e.name) + "</th><td>" + esc(e.sector) + "</td><td>" + esc(e.provider) + '</td><td><span class="ph-badge ph-badge--' + (e.enabled ? "success" : "secondary") + '">' + (e.enabled ? "Enabled" : "Disabled") + "</span></td><td>" + esc(e.live) + "</td><td>" + (e.matches ? "<strong>" + e.matches + "</strong>" : '<span class="ph-meta">0</span>') + "</td><td>" + esc(dt(e.vc_total)) + "</td><td>" + esc(dt(e.vc_au)) + "</td><td>" + esc(dt(e.vc_vic)) + "</td><td>" + esc(e.verified_at || "—") + "</td><td>" + (e.notes ? '<span title="' + esc(e.notes) + '">' + esc(trunc(e.notes, 70)) + "</span>" : '<span class="ph-meta">—</span>') + "</td></tr>"; }).join("") + "</tbody></table></div>"
          : '<div class="jx-empty"><p class="jx-empty__t">No employers match.</p><p class="ph-meta">Try another sector or clear the filter.</p></div>') + "</section>";
    }).catch(function (e) { view.innerHTML = head("Sources") + errorBox(e, true); });
  }

  /* ---------- Interview preparation + follow-up drafts (same wording as the classic pages) ---------- */
  var polls = {};
  function pollLater(key, fn) { clearTimeout(polls[key]); polls[key] = setTimeout(function () { if (location.hash.indexOf(key) === 1) fn(); }, 3000); }
  function titleCase(t) { return String(t || "").replace(/[_-]/g, " ").replace(/\w\S*/g, function (w) { return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase(); }); }
  function citations(list) {
    return (list || []).map(function (c) { return '<details><summary>Evidence: ' + esc(c.source_id) + "</summary><blockquote class=\"a-quote\">" + esc(c.quote) + '</blockquote><p class="ph-meta">Source hash: ' + esc(c.content_hash) + "</p></details>"; }).join("");
  }
  function renderInterviewEntry(error, keep) {
    api("/api/interview").then(function (d) {
      keep = keep || {};
      view.innerHTML = '<header class="c-head"><h1 class="c-h1" tabindex="-1">Prepare for an interview</h1><p class="ph-meta">Use a job URL, including a role you have not evaluated or applied for.</p></header>' +
        (error ? '<div class="ph-alert ph-alert--error" role="alert"><span>' + esc(error) + "</span></div>" : "") +
        '<form class="ph-card jx-iform" id="iopen"><div class="ph-card__body"><label class="a-field"><span class="ph-label">Job posting URL</span><input class="ph-input" name="url" type="url" required maxlength="8192" placeholder="https://…" value="' + esc(keep.url || "") + '"></label>' +
        "<details" + (error ? " open" : "") + '><summary>Use a saved job description</summary><p>For a closed or inaccessible posting, paste the whole description. It will be labelled as supplied by you.</p>' +
        '<label class="a-field"><span class="ph-label">Role title</span><input class="ph-input" name="title" maxlength="500" value="' + esc(keep.title || "") + '"></label>' +
        '<label class="a-field"><span class="ph-label">Company</span><input class="ph-input" name="company" maxlength="500" value="' + esc(keep.company || "") + '"></label>' +
        '<label class="a-field"><span class="ph-label">Full job description</span><textarea class="ph-textarea" name="pasted_jd" rows="12" maxlength="100000">' + esc(keep.pasted_jd || "") + "</textarea></label></details>" +
        '<p>Next, review the source and add any interview notes before generating. This does not create an application or send anything.</p><button type="submit" class="ph-btn ph-btn--default">Open interview preparation</button></div></form>' +
        (d.subjects.length ? '<section class="ph-card"><div class="ph-card__body"><h2>Saved interview preparation</h2><ul>' + d.subjects.map(function (s) { return '<li><a href="#interview/' + esc(s.id) + '">' + esc(s.title) + "</a> · " + esc(s.company || "") + " · " + esc(s.at || "") + "</li>"; }).join("") + "</ul></div></section>" : "");
    }).catch(function (e) { view.innerHTML = head("Prepare for an interview") + errorBox(e, true); });
  }
  function prepReport(rep, ref, kinds) {
    var h = "<h2>Your reviewed interview preparation</h2><p>Prepared from the current job ad, profile and saved notes, with independent review. Check the evidence and unknowns before your interview. Nothing has been sent.</p>" +
      '<p><a class="ph-btn ph-btn--outline" href="' + (/^\d+$/.test(ref) ? "/jobs/" + ref + "/interview-prep/download" : "/interview-prep/subjects/" + esc(ref) + "/download") + '">' + icon("download") + "Download private report (.txt)</a></p>" +
      '<nav aria-label="Report sections"><ul class="a-hist">' + rep.proposal.sections.map(function (sec_, i) { return '<li><a href="#interview/' + esc(ref) + '" data-jump="prep-section-' + (i + 1) + '">' + esc(titleCase(sec_.title)) + "</a></li>"; }).join("") + "</ul></nav>";
    rep.proposal.sections.forEach(function (sec_, i) {
      h += '<section class="jx-prepsec" id="prep-section-' + (i + 1) + '"><h3>' + esc(titleCase(sec_.title)) + "</h3>" + sec_.items.map(function (it) {
        return "<article><h4>" + esc(nice(it.topic)) + "</h4><p><strong>" + esc(kinds[it.kind] || it.kind) + "</strong>" + (it.audience ? " · " + esc(it.audience) : "") + "</p><p>" + esc(it.text) + "</p>" +
          (it.question ? "<p><strong>Question:</strong> " + esc(it.question) + "</p>" : "") + citations(it.citations) +
          (it.answer ? "<p><strong>" + (it.answer_grounding === "owner_fact" ? "Owner-supplied fact" : "Primary candidate evidence") + '</strong></p><dl class="a-dl">' + Object.keys(it.answer).map(function (k) { return "<div><dt>" + esc(titleCase(k)) + "</dt><dd>" + esc(it.answer[k]) + "</dd></div>"; }).join("") + "</dl>" + citations(it.answer_citations) : "") + "</article>";
      }).join("") + "</section>";
    });
    return h + "<details><summary>Sources and report provenance (" + rep.sources.length + " sources)</summary><p>Writer: " + esc(rep.writer_model) + " · Reviewer: " + esc(rep.reviewer_model) + "</p><p>Snapshot: " + esc(rep.snapshot_hash) + "</p><p>Reviewed report: " + esc(rep.proposal.draft_hash) + "</p>" +
      rep.sources.map(function (s) { return "<p><strong>" + esc(s.source_id) + "</strong> · " + esc(s.kind) + " · Accessed: " + esc(s.accessed_at || "not recorded") + (s.url ? ' · <a href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">Open source</a>' : "") + '</p><p class="ph-meta">Hash: ' + esc(s.content_hash) + "</p>"; }).join("") + "</details>";
  }
  function renderInterview(ref) {
    api("/api/interview/" + encodeURIComponent(ref)).then(function (d) {
      var j = d.job, st = d.state, body;
      var startBtn = function (retry) { return '<button type="button" class="ph-btn ' + (retry ? "ph-btn--outline" : "ph-btn--default") + '" data-iprep="' + esc(ref) + '"' + (retry ? ' data-again="1"' : "") + ">" + (retry ? "Retry within remaining allowance" : "Generate interview preparation") + "</button>"; };
      if (st.status === "ready") body = prepReport(st.report, ref, d.kinds);
      else if (st.status === "running") body = "<h2>Researching, preparing and reviewing…</h2><p>This page updates when preparation finishes. You can leave and return.</p>";
      else if (st.status === "missing") body = "<h2>Prepare for this interview</h2><p>Save any optional context below, then generate preparation from the full job ad and your current profile. Missing sources will be labelled unknown.</p><p>" + startBtn(false) + "</p>";
      else if (st.status === "held") body = "<h2>Preparation held for verification</h2><p>A reviewed report is not available. Retry after the issue is resolved; previous usage and uncertain charges still count toward the same limits.</p><p>" + startBtn(true) + "</p>";
      else if (st.status === "disabled") body = "<p>Interview preparation is not enabled for this installation.</p>";
      else body = "<h2>Check interview readiness</h2><p>The full job ad, current profile or private notes need verification. A previously prepared report is hidden when its sources change.</p>";
      view.innerHTML = '<header class="c-head"><h1 class="c-h1" tabindex="-1">Interview preparation for ' + esc(j.title) + '</h1><p class="ph-meta">' + esc(j.company || "") + "</p></header>" +
        "<p>" + (j.standalone ? "" : '<a href="#job/' + esc(ref) + '">Back to job</a> · ') + '<a href="#interview">Prepare another interview</a> · <a href="#applications">Applications</a></p>' +
        (j.jd_source ? "<p><strong>JD source:</strong> " + esc(j.jd_source) + " · Saved " + esc(j.acquired_at || "") + '</p><details><summary>Review the saved job description</summary><p>' + (j.source_link ? '<a href="' + esc(j.source_link) + '" rel="noopener noreferrer" target="_blank">Open source</a>' : "") + '</p><pre class="jx-pre">' + esc(j.ad_text) + "</pre></details>" : "") +
        '<section class="ph-card"><div class="ph-card__body" id="iprep">' + body + "</div></section>" +
        '<section class="ph-card"><div class="ph-card__body"><h2>Your private interview context</h2><p>Optional notes help tailor the preparation. These notes are not used in public search queries. Save before generating; changing notes hides the previous report.</p>' +
        '<form id="iinputs" data-ref="' + esc(ref) + '" data-rev="' + d.revision + '">' + d.fields.map(function (f) { return '<label class="a-field"><span class="ph-label">' + esc(f[1]) + '</span><textarea class="ph-textarea" name="' + f[0] + '" rows="4" maxlength="' + (f[0] === "prior_compensation" ? 10000 : 20000) + '">' + esc(d.inputs[f[0]]) + "</textarea></label>"; }).join("") +
        '<p class="ph-meta">Up to 60,000 characters across all notes. Leave unavailable sources blank.</p><button type="submit" class="ph-btn ph-btn--outline">Save private context</button></form></div></section>';
      document.title = "Interview preparation - Jobwatch";
      if (st.status === "running") pollLater("interview/" + ref, function () { renderInterview(ref); });
    }).catch(function (e) { view.innerHTML = head("Interview preparation") + errorBox(e, true) + '<p><a href="#interview">Prepare another interview</a></p>'; });
  }
  function renderFollowDraft(pid, channel) {
    channel = channel === "linkedin" ? "linkedin" : "email";
    api("/api/followup-draft/" + pid + "?channel=" + channel).then(function (d) {
      var st = d.status, body, btn = function (retry) { return '<button type="button" class="ph-btn ph-btn--' + (retry ? "outline" : "default") + '" data-fdraft="' + pid + '" data-channel="' + channel + '"' + (retry ? ' data-again="1"' : "") + ">" + (retry ? "Retry within remaining allowance" : "Generate " + (channel === "linkedin" ? "LinkedIn" : "follow-up") + " draft") + "</button>"; };
      if (st === "ready") body = "<h2>Draft ready for your review</h2><p>The draft passed an independent review against the saved application and profile. Check it before you send it. Nothing has been sent.</p>" +
        (channel === "email" ? '<label class="a-field"><span class="ph-label">Subject</span><textarea class="ph-textarea" rows="2" readonly>' + esc(d.proposal.subject) + "</textarea></label>" : "") +
        '<label class="a-field"><span class="ph-label">Message</span><textarea class="ph-textarea" rows="12" readonly>' + esc(d.proposal.body) + "</textarea></label><p>Select and copy the text into your email or message app. After sending it yourself, record the sent event on Applications.</p>";
      else if (st === "running") body = "<h2>Writing and reviewing your follow-up…</h2><p>This page will update when the review finishes. Nothing is sent automatically.</p>";
      else if (st === "missing") body = "<h2>Prepare a tailored follow-up</h2><p>Your saved application history and profile will be used to write and independently review a draft.</p><p>" + btn(false) + "</p>";
      else if (st === "disabled") body = "<p>Follow-up drafting is not enabled for this installation.</p>";
      else if (st === "held") body = "<h2>Draft held for verification</h2><p>A verified draft is not available. No message has been sent.</p><p>You can retry after the issue is resolved. Previous usage still counts toward the same token and attempt limits.</p><p>" + btn(true) + "</p>";
      else body = "<h2>Check follow-up readiness</h2><p>The follow-up may not be due, or the application dates, job ad or profile need verification. A previously prepared draft is not shown if these inputs changed.</p>";
      view.innerHTML = '<header class="c-head"><h1 class="c-h1" tabindex="-1">Follow-up for ' + esc(d.job.title) + '</h1><p class="ph-meta">' + esc(d.job.company || "") + '</p></header><p><a href="#applications">Back to applications</a> · <a href="#followup/' + pid + '/email">Email draft</a> · <a href="#followup/' + pid + '/linkedin">LinkedIn draft</a></p>' +
        '<section class="ph-card"><div class="ph-card__body">' + body + "</div></section>";
      if (st === "running") pollLater("followup/" + pid + "/" + channel, function () { renderFollowDraft(pid, channel); });
    }).catch(function (e) { view.innerHTML = head("Follow-up draft") + errorBox(e, true) + '<p><a href="#applications">Back to applications</a></p>'; });
  }

  /* ---------- phone nav bar: small title that appears on scroll, or "‹ Board" on a pushed screen ---------- */
  var NB = { always: false, title: "" };
  function setNavbar(backLabel, backHref, title, always) {
    var nb = document.getElementById("navbar"); if (!nb) return;
    NB.always = !!always; NB.title = title || "";
    nb.innerHTML = (backLabel ? '<a class="jx-navbar__back" href="' + backHref + '">' + icon("chevron-left") + esc(backLabel) + "</a>" : "") + '<span class="jx-navbar__t">' + esc(NB.title) + "</span>";
    syncNavbar();
  }
  function syncNavbar() { var nb = document.getElementById("navbar"); if (nb) nb.classList.toggle("is-on", phone() && (NB.always || window.scrollY > 56)); }
  window.addEventListener("scroll", syncNavbar, { passive: true });
  PHONE_Q.addEventListener("change", function () { route(); });
  function renderMore() {
    view.innerHTML = head("More") + '<ul class="jx-morelist">' + [["chat", "Ask Jobwatch", "message-circle", "#chat"], ["table", "All jobs (table)", "briefcase", "#table"], ["insights", "Insights", "gauge", "#insights"], ["sources", "Job sources", "database", "#sources"], ["candidate", "My profile", "user-round", "/candidate"], ["preferences", "Preferences", "filter", "/preferences"], ["answers", "Form answers", "list-checks", "/answers"], ["accounts", "Accounts", "key-round", "/accounts"], ["models", "AI models", "bot", "/models"]].map(function (x) {
      return '<li><a class="jx-morelist__row" href="' + x[3] + '">' + icon(x[2]) + "<span>" + x[1] + "</span>" + icon("chevron-right") + "</a></li>"; }).join("") +
      '<li><button type="button" class="jx-morelist__row" id="themeBtn2">' + icon("palette") + '<span id="themeName2">Theme</span>' + icon("chevron-right") + "</button></li></ul>";
    var tb = document.getElementById("themeBtn2"); if (tb) { document.getElementById("themeName2").textContent = document.getElementById("themeName").textContent; tb.addEventListener("click", function () { document.getElementById("themeBtn").click(); document.getElementById("themeName2").textContent = document.getElementById("themeName").textContent; }); }
  }
  /* ---------- Today: what to do now, in one screen ---------- */
  function todayRow(r) {
    return '<li><a class="jx-trow" href="#job/' + r.id + '">' + score(r).replace("jx-score", "jx-score jx-score--big") + '<span class="jx-trow__main"><strong>' + esc(r.title) + '</strong><span class="ph-meta">' + esc(r.company || "Employer not stated") + " · " + esc(String(r.where || "").split(",")[0]) + (r.salary ? " · " + esc(r.salary) : "") + "</span></span>" + icon("chevron-right") + "</a></li>";
  }
  function renderToday() {
    Promise.all([api("/api/board?ai=show&page=1"), api("/api/board?ai=worth&page=1"), api("/api/applications"), api("/api/nav")]).then(function (r) {
      var good = r[0], worth = r[1], apps = r[2], nav = r[3], todo = [];
      var drafted = [];
      (apps.cols || []).forEach(function (c) { if (c[0] === "drafted") c[2].forEach(function (a) { if (String(a.draft || "").indexOf("ready") === 0) drafted.push(a); }); });
      drafted.forEach(function (a) { todo.push(["#applications", "Check and submit: " + a.title, (a.company || "") + ". Your CV and letter are ready; you press Submit."]); });
      if (nav.inbox) todo.push(["#inbox", nav.inbox + " email repl" + (nav.inbox === 1 ? "y" : "ies") + " to confirm", "Jobwatch read your mail and needs a yes or no."]);
      if (nav.sources_bad) todo.push(["#sources", nav.sources_bad + " job source" + (nav.sources_bad === 1 ? " is" : "s are") + " broken", "New jobs from it may be missing."]);
      var held = Math.max(0, (worth.total || 0) - (good.total || 0)), prog = worth.progress || {};
      var todoHtml = todo.length ? '<ul class="jx-todo">' + todo.map(function (t) { return '<li><a class="jx-todo__row" href="' + t[0] + '"><span><strong>' + esc(t[1]) + '</strong><span class="ph-meta">' + esc(t[2]) + "</span></span>" + icon("chevron-right") + "</a></li>"; }).join("") + "</ul>" : '<p class="jx-quiet">' + icon("check") + " Nothing needs you right now.</p>";
      var matches = good.rows.length ? '<ul class="jx-trows">' + good.rows.slice(0, 5).map(todayRow).join("") + "</ul>" : '<p class="jx-quiet">No job is rated Good yet.</p>';
      var heldHtml = held ? '<div class="jx-callout"><strong>' + held + " more jobs are held back.</strong><p class=\"ph-meta\">The AI could not read the whole ad for these, so their score is a guess" + (prog.left > 0 ? ". It has read " + prog.read + " of " + prog.total + " matched ads so far" : "") + '.</p><a class="ph-btn ph-btn--outline" href="#board">Browse them anyway</a></div>' : "";
      view.innerHTML = head("Today", new Date().toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long" })) +
        '<section class="jx-block"><h2 class="jx-block__h">Needs you</h2>' + todoHtml + "</section>" +
        '<section class="jx-block"><div class="jx-block__top"><h2 class="jx-block__h">Best matches</h2><a href="#board">See all ' + (worth.total || 0) + " →</a></div>" + matches + "</section>" + heldHtml +
        '<section class="jx-block"><h2 class="jx-block__h">Applications</h2><p>' + (apps.total ? apps.total + " tracked. " : "None yet. ") + '<a href="#applications">Open applications →</a></p></section>';
    }).catch(function (e) { view.innerHTML = head("Today") + errorBox(e, true); });
  }
  /* ---------- router ---------- */
  var ROUTES = { today: renderToday, more: renderMore, board: renderBoard, table: renderTable, applications: renderApplications, inbox: renderInbox, chat: renderChat, insights: renderInsights, sources: renderSources };
  var TITLES = { today: "Today", more: "More", board: "Find jobs", table: "Jobs", applications: "Applications", inbox: "Inbox", chat: "Chat", insights: "Insights", sources: "Sources" };
  function route() {
    var h = location.hash.replace(/^#/, "") || "today", parts = h.split("/");
    var page = parts[0];
    S.sheet = false; S.saved = false;
    setNavbar("", "", ({ interview: "Interview preparation", followup: "Follow-up draft" })[page] || TITLES[page] || "", false);
    if (page === "interview" || page === "followup") setNavbar("Applications", "#applications", ({ interview: "Interview preparation", followup: "Follow-up draft" })[page], true);
    if (page === "job" && /^\d+$/.test(parts[1] || "")) { drawNav("board"); loading("Job"); renderJob(parts[1]); }
    else if (page === "interview") { drawNav("applications"); loading("Interview preparation"); if (parts[1]) renderInterview(decodeURIComponent(parts[1])); else renderInterviewEntry(); }
    else if (page === "followup" && /^\d+$/.test(parts[1] || "")) { drawNav("applications"); loading("Follow-up draft"); renderFollowDraft(parts[1], parts[2]); }
    else if (ROUTES[page]) { drawNav(page); document.title = TITLES[page] + " - Jobwatch"; loading(TITLES[page]); ROUTES[page](); }
    else { location.replace("#today"); return; }
    document.body.dataset.page = page;
    document.getElementById("main").focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }

  /* ---------- one click handler for the whole app ---------- */
  function closePops(e) {
    if (S.saved && !e.target.closest(".jx-savedwrap")) { S.saved = false; var sp = document.getElementById("savedPop"); if (sp) sp.hidden = true; }
  }
  document.addEventListener("click", function (e) {
    closePops(e);
    var t = e.target.closest("[data-retry]"); if (t) { route(); return; }
    t = e.target.closest("[data-sheet]"); if (t) { S.sheet = t.dataset.sheet === "open"; var sh = document.getElementById("sheet"); if (sh) sh.hidden = !S.sheet; return; }
    t = e.target.closest("[data-reset]"); if (t) { clearFacets(); F.q = F.x = ""; F.st = "all"; F.ai = "worth"; F.why = ""; F.sort = "fit"; F.scope = "matches"; T.page = 1; redraw(); return; }
    t = e.target.closest("[data-savedtoggle]"); if (t) { S.saved = !S.saved; document.getElementById("savedPop").hidden = !S.saved; return; }
    t = e.target.closest("[data-tab]"); if (t) { F.ai = t.dataset.tab; F.why = ""; F.page = 1; T.page = 1; B.sel = null; redraw(); return; }
    t = e.target.closest("[data-st]"); if (t) { F.st = t.dataset.st; F.page = 1; T.page = 1; redraw(); return; }
    t = e.target.closest("[data-scope]"); if (t) { F.scope = t.dataset.scope; F.page = 1; T.page = 1; redraw(); return; }
    t = e.target.closest("[data-clearq]"); if (t) { F.q = F.x = ""; F.page = 1; T.page = 1; redraw(); return; }
    t = e.target.closest("[data-clearfacets]"); if (t) { clearFacets(); T.page = 1; redraw(); return; }
    t = e.target.closest("[data-unchip]"); if (t) { unchip(t.dataset.unchip, t.dataset.v); T.page = 1; redraw(); return; }
    t = e.target.closest("[data-pg]"); if (t) { F.page = +t.dataset.pg; renderBoard(); window.scrollTo(0, 0); return; }
    t = e.target.closest("[data-tpage]"); if (t) { T.page = +t.dataset.tpage; renderTable(); window.scrollTo(0, 0); return; }
    t = e.target.closest("[data-sortcol]");
    if (t) { var k = t.dataset.sortcol, cur = T.dir || (DESC_FIRST.indexOf(T.sort) >= 0 ? "desc" : "asc"); if (T.sort === k) T.dir = cur === "asc" ? "desc" : "asc"; else { T.sort = k; T.dir = ""; } T.page = 1; renderTable(); return; }
    t = e.target.closest("[data-opensaved]");
    if (t) {
      var sp = new URLSearchParams(t.dataset.q); clearFacets(); F.q = F.x = ""; F.scope = "matches"; F.st = "all"; F.ai = ""; F.why = "";
      sp.forEach(function (v, k) { if (MULTI.indexOf(k) >= 0) F[k].push(v); else if (k === "sal" || k === "entry") F[k] = "1"; else if (k === "ai" && v.indexOf(":") > 0) { F.ai = "hide"; F.why = v.split(":")[1]; } else if (k in F) F[k] = v; });
      api("/api/searches/" + t.dataset.opensaved + "/open", {}).catch(function () { }); S.saved = false; renderBoard(); return;
    }
    t = e.target.closest("[data-delsaved]");
    if (t) { api("/api/searches/" + t.dataset.delsaved + "/delete", {}).then(function (d) { toast(d.toast); LAST.saved = d.saved; renderBoard(); }).catch(fail); return; }
    t = e.target.closest("[data-srclear]"); if (t) { SR = { sector: "", enabled: "" }; renderSources(); return; }
    t = e.target.closest("#cards .jx-card");
    if (t && phone() && !e.target.closest("a") && !e.target.closest("[data-act]")) { location.hash = "#job/" + t.dataset.id; return; }
    if (t && !e.target.closest("[data-act]") && !e.target.closest("a") && matchMedia("(min-width: 900px)").matches) { showDetail(t.dataset.id); return; }
    t = e.target.closest("#cards [data-pick]");
    if (t && matchMedia("(min-width: 900px)").matches) { e.preventDefault(); showDetail(t.dataset.pick); return; }
    t = e.target.closest("[data-act]");
    if (t) {
      var act = t.dataset.act, id = t.dataset.id, body = {};
      if (act === "notes") body.notes = document.getElementById("jnotes").value;
      t.disabled = true;
      api("/api/job/" + id + "/" + act, body).then(function (d) {
        toast(d.toast || "Done");
        refreshNav(document.body.dataset.page);
        if (document.body.dataset.page === "job") renderJob(id); else renderBoard();
      }).catch(function (err) { t.disabled = false; fail(err); });
      return;
    }
    t = e.target.closest("[data-decide]");
    if (t) {
      if (t.dataset.decide === "reject" && !confirm("Reject this suggestion? Your application keeps its current status.")) return;
      t.disabled = true;
      api("/api/inbox/" + t.dataset.pid + "/" + t.dataset.decide, {}).then(function (d) { toast(d.toast || "Done"); drawInbox(d, d.toast); refreshNav("inbox"); }).catch(function (err) { t.disabled = false; fail(err); });
      return;
    }
    t = e.target.closest("[data-fusave]");
    if (t) {
      var box = t.closest(".jx-form"), b = { action: box.dataset.fu, operation_id: box.dataset.op };
      box.querySelectorAll("[data-f]").forEach(function (el) { b[el.dataset.f] = el.type === "checkbox" ? el.checked : el.value; });
      if (box.dataset.fu === "pin" || box.dataset.fu === "clear_pin") b.owner_confirmed = true;
      if (box.dataset.fu !== "event") b.action = box.dataset.fu; else b.action = b.action;
      t.disabled = true;
      api("/api/applications/" + box.dataset.pid + "/followup", b).then(function (d) { toast(d.toast); drawApplications(d); }).catch(function (err) { t.disabled = false; fail(err); });
      return;
    }
    t = e.target.closest("[data-ask]"); if (t) { send(t.dataset.ask); return; }
    t = e.target.closest("[data-qa]"); if (t) { answerAsk(t.dataset.qa); return; }
    t = e.target.closest("[data-jump]"); if (t) { e.preventDefault(); var tg = document.getElementById(t.dataset.jump); if (tg) tg.scrollIntoView(); return; }
    t = e.target.closest("[data-iprep]");
    if (t) { t.disabled = true; api("/api/interview/" + encodeURIComponent(t.dataset.iprep) + "/start", { retry: !!t.dataset.again }).then(function (d) { toast(d.toast); renderInterview(t.dataset.iprep); }).catch(function (err) { t.disabled = false; fail(err); }); return; }
    t = e.target.closest("[data-fdraft]");
    if (t) { t.disabled = true; api("/api/followup-draft/" + t.dataset.fdraft, { channel: t.dataset.channel, retry: !!t.dataset.again }).then(function (d) { toast(d.toast); renderFollowDraft(t.dataset.fdraft, t.dataset.channel); }).catch(function (err) { t.disabled = false; fail(err); }); return; }
  });
  document.addEventListener("change", function (e) {
    var el = e.target;
    if (el.id === "bsort") { F.sort = el.value; F.page = 1; renderBoard(); return; }
    if (el.id === "bscope") { F.scope = el.checked ? "all" : "matches"; F.page = 1; T.page = 1; redraw(); return; }
    if (el.dataset && el.dataset.col) { var cols = tableCols(), i = cols.indexOf(el.dataset.col); if (el.checked && i < 0) { var order = META.table_cols.map(function (c) { return c[0]; }); cols.push(el.dataset.col); cols.sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); }); } else if (!el.checked && i >= 0 && cols.length > 1) cols.splice(i, 1); saveCols(); var d_ = document.querySelector("details.jx-menu"); renderTable(); return; }
    if (el.closest && el.closest(".jx-facets") && el.name) { applyFacetInput(el); redraw(); return; }
    if (el.dataset && el.dataset.appstatus) { api("/api/job/" + el.dataset.appstatus + "/status", { status: el.value }).then(function (d) { toast(d.toast || "Saved"); refreshNav("applications"); renderApplications(); }).catch(function (err) { fail(err); renderApplications(); }); return; }
    if (el.id === "srsector") { SR.sector = el.value; renderSources(); return; }
    if (el.id === "srenabled") { SR.enabled = el.value; renderSources(); return; }
    if (el.id === "jstatus") {
      var id = el.dataset.id;
      api("/api/job/" + id + "/status", { status: el.value }).then(function (d) { toast(d.toast || "Saved"); refreshNav("board"); }).catch(fail);
    }
  });
  var qTid = null;
  document.addEventListener("input", function (e) {
    var id = e.target.id;
    if (id === "bq" || id === "bx") {
      clearTimeout(qTid); var v = e.target.value;
      qTid = setTimeout(function () {
        if (id === "bq") F.q = v; else F.x = v; F.page = 1; T.page = 1; redraw();
        setTimeout(function () { var i = document.getElementById(id); if (i) { i.focus(); i.setSelectionRange(v.length, v.length); } }, 80);
      }, 450);
    }
  });
  document.addEventListener("submit", function (e) {
    if (e.target.id === "cform") { e.preventDefault(); var i = document.getElementById("cin"); var v = i.value; i.value = ""; send(v); }
    if (e.target.id === "iopen") {
      e.preventDefault(); var fd = new FormData(e.target), body = {}; fd.forEach(function (v, k) { body[k] = v; });
      var btn = e.target.querySelector("button[type=submit]"); btn.disabled = true; btn.textContent = "Checking the ad…";
      api("/api/interview/open", body).then(function (d) { location.hash = "#interview/" + d.ref; }).catch(function (err) { renderInterviewEntry(err.message, body); });
      return;
    }
    if (e.target.id === "iinputs") {
      e.preventDefault(); var f2 = e.target, b2 = { revision: +f2.dataset.rev };
      f2.querySelectorAll("textarea").forEach(function (el) { b2[el.name] = el.value; });
      api("/api/interview/" + encodeURIComponent(f2.dataset.ref) + "/inputs", b2).then(function (d) { toast(d.toast); renderInterview(f2.dataset.ref); }).catch(fail);
      return;
    }
    if (e.target.id === "saveForm") {
      e.preventDefault();
      api("/api/searches", { name: document.getElementById("saveName").value, qs: fqs().toString() }).then(function (d) { toast(d.toast); LAST.saved = d.saved; S.saved = true; renderBoard(); }).catch(fail);
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.target.id === "cin" && e.key === "Enter" && !e.shiftKey) { e.preventDefault(); document.getElementById("cform").requestSubmit(); }
    if (e.key === "Escape" && S.sheet) { S.sheet = false; var sh = document.getElementById("sheet"); if (sh) sh.hidden = true; }
  });

  window.addEventListener("hashchange", route);
  api("/api/meta").then(function (m) { META = m; return refreshNav("board"); }).then(route)
    .catch(function (e) { view.innerHTML = head("Jobwatch") + errorBox(e, true); });
})();

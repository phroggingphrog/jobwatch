(function () {
  "use strict";
  var V = window.V3, SR = { sector: "", enabled: "" }, SHOW = 20;
  function nice(s) { return String(s || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function trunc(s, k) { s = String(s || ""); return s.length > k ? s.slice(0, k - 1) + "…" : s; }
  var WORD = { ok: "Working", warn: "Check", bad: "Failing" }, TONE = { ok: "ok", warn: "warn", bad: "bad" };
  function health(h) {
    var lat = h.last_latency_ms != null ? (h.last_latency_ms >= 1000 ? (h.last_latency_ms / 1000).toFixed(1) + " s" : h.last_latency_ms + " ms") : "";
    var bits = [h.last_ok_at ? "Last worked " + h.last_ok_ago : "Has never worked", h.last_count != null ? "found " + h.last_count : "", lat, h.consecutive_failures ? h.consecutive_failures + " fails in a row" : ""].filter(Boolean);
    return '<div class="wk-prow"><div class="grow"><div class="wk-title" title="' + V.esc(h.collector) + '">' + V.esc(h.label) + '</div><div class="wk-sub">' + V.esc(bits.join(" · ")) + "</div>" + (h.last_error ? '<div class="wk-sub" style="color:var(--bad)" title="' + V.esc(h.last_error) + '">' + V.esc(trunc(h.last_error, 140)) + "</div>" : "") + "</div>" + V.st(WORD[h.rag] || "Unknown", TONE[h.rag] || "") + "</div>";
  }
  function emp(e) {
    var vc = [e.vc_total != null ? e.vc_total + " verified" : "", e.vc_au != null ? e.vc_au + " in Australia" : "", e.vc_vic != null ? e.vc_vic + " in Victoria" : ""].filter(Boolean);
    return '<div class="wk-prow"><div class="grow"><div class="wk-title">' + V.esc(e.name) + '</div><div class="wk-sub">' + V.esc([nice(e.sector), e.provider, e.live + " live", e.matches ? e.matches + " match" + (e.matches === 1 ? "" : "es") : "no matches"].filter(Boolean).join(" · ")) + "</div>" +
      (vc.length || e.verified_at ? '<div class="wk-sub">' + V.esc(vc.join(" · ") + (e.verified_at ? (vc.length ? " · " : "") + "checked " + e.verified_at : "")) + "</div>" : "") +
      (e.notes ? '<div class="wk-sub" title="' + V.esc(e.notes) + '">' + V.esc(trunc(e.notes, 120)) + "</div>" : "") + "</div>" + V.st(e.enabled ? "Checked" : "Not checked", e.enabled ? "ok" : "") + "</div>";
  }
  function load(keepFocus) {
    var p = new URLSearchParams(); if (SR.sector) p.set("sector", SR.sector); if (SR.enabled) p.set("enabled", SR.enabled);
    V.api("/api/sources?" + p).then(function (d) {
      if (location.hash !== "#sources") return;
      var n = { ok: 0, warn: 0, bad: 0 }; d.health.forEach(function (h) { n[h.rag] = (n[h.rag] || 0) + 1; });
      var bad = d.health.filter(function (h) { return h.rag === "bad"; }), rest = d.health.filter(function (h) { return h.rag !== "bad"; });
      var line = d.health.length ? (n.bad ? n.bad + " of " + d.health.length + " sources are failing, so some new jobs may be missing." : n.warn ? n.warn + " of " + d.health.length + " sources need a look." : "All " + d.health.length + " sources are working.") : "No source has run yet. Health shows up after the first run.";
      V.draw(V.head("Sources", "Where jobs come from. Employers are also checked directly on their own careers systems, not only the job boards.") +
        '<div class="wk-panel wk-pad wk-row" style="gap:20px">' + V.st(n.bad ? "Needs attention" : d.health.length ? "Healthy" : "No run yet", n.bad ? "bad" : d.health.length ? "ok" : "warn") + '<span class="wk-body" style="flex:1">' + V.esc(line) + '</span><span class="wk-mono wk-sub">' + n.ok + " working · " + n.warn + " to check · " + n.bad + " failing</span></div>" +
        (d.health.length ? (bad.length ? '<div class="wk-sec"><h2 class="wk-h2">Failing<span class="n">' + bad.length + '</span></h2><div class="wk-rows">' + bad.map(health).join("") + "</div></div>" : "") +
          '<details class="wk-fold"' + (bad.length ? "" : " open") + "><summary>" + (bad.length ? "Other sources (" + rest.length + ")" : "All sources (" + rest.length + ")") + '</summary><div class="wk-rows" style="border:0;border-top:1px solid var(--line);border-radius:0">' + rest.map(health).join("") + "</div></details>" : "") +
        '<div class="wk-sec"><div class="wk-sechead"><h2 class="wk-h2">Employers watched<span class="n">' + d.employers.length + '</span></h2><div class="wk-row"><label class="sr" for="srsector">Sector</label><select class="wk-sel" id="srsector"><option value="">All sectors</option>' + d.sectors.map(function (s) { return '<option value="' + V.esc(s) + '"' + (s === SR.sector ? " selected" : "") + ">" + V.esc(nice(s)) + "</option>"; }).join("") + '</select><label class="sr" for="srenabled">Checking</label><select class="wk-sel" id="srenabled"><option value="">All</option><option value="1"' + (SR.enabled === "1" ? " selected" : "") + '>Checked only</option><option value="0"' + (SR.enabled === "0" ? " selected" : "") + ">Not checked only</option></select>" +
        (SR.sector || SR.enabled ? '<button class="btn" type="button" data-srclear>Clear</button>' : "") + "</div></div>" +
        '<p class="wk-sub">Live means seen in the last 7 days.</p>' +
        (d.employers.length ? '<div class="wk-rows">' + d.employers.slice(0, SHOW).map(emp).join("") + "</div>" + (d.employers.length > SHOW ? '<div><button class="btn" type="button" data-srmore>Show all ' + d.employers.length + " employers</button></div>" : "") : '<div class="wk-panel"><div class="wk-empty"><b>No employers match</b><span>Try another sector or clear the filter.</span></div></div>') + "</div>");
      if (keepFocus) { var f = document.getElementById(keepFocus); if (f) f.focus(); }
    }).catch(function (e) { V.failPage("Sources", e); });
  }
  V.page("sources", function () { SHOW = 20; SR = { sector: "", enabled: "" }; load(); });
  document.addEventListener("click", function (e) { if (location.hash !== "#sources") return; if (e.target.closest("[data-srclear]")) { SR = { sector: "", enabled: "" }; SHOW = 20; load(); } if (e.target.closest("[data-srmore]")) { SHOW = 100000; load(); } });
  document.addEventListener("change", function (e) {
    if (location.hash !== "#sources") return;
    if (e.target.id === "srsector") { SR.sector = e.target.value; SHOW = 20; load("srsector"); }
    if (e.target.id === "srenabled") { SR.enabled = e.target.value; SHOW = 20; load("srenabled"); }
  });
})();

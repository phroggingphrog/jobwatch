(function () {
  "use strict";
  var V = window.V3, SR = { sector: "", enabled: "" }, SHOW = 20;
  function nice(s) { return String(s || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function trunc(s, k) { s = String(s || ""); return s.length > k ? s.slice(0, k - 1) + "…" : s; }
  var WORD = { ok: "Working", warn: "Check", bad: "Failing" };
  function health(h) {
    var lat = h.last_latency_ms != null ? (h.last_latency_ms >= 1000 ? (h.last_latency_ms / 1000).toFixed(1) + " s" : h.last_latency_ms + " ms") : "";
    var bits = [h.last_ok_at ? "Last worked " + h.last_ok_ago : "Has never worked", h.last_count != null ? "found " + h.last_count : "", lat, h.consecutive_failures ? h.consecutive_failures + " fails in a row" : ""].filter(Boolean);
    return '<div class="card src src--' + h.rag + '"><div class="src__top"><strong class="src__n" title="' + V.esc(h.collector) + '">' + V.esc(h.label) + '</strong><span class="stage" data-rag="' + h.rag + '">' + (WORD[h.rag] || "Unknown") + "</span></div>" +
      '<p class="src__m">' + V.esc(bits.join(" · ")) + "</p>" + (h.last_error ? '<p class="src__err" title="' + V.esc(h.last_error) + '">' + V.esc(trunc(h.last_error, 140)) + "</p>" : "") + "</div>";
  }
  function emp(e) {
    var vc = [e.vc_total != null ? e.vc_total + " verified" : "", e.vc_au != null ? e.vc_au + " in Australia" : "", e.vc_vic != null ? e.vc_vic + " in Victoria" : ""].filter(Boolean);
    return '<div class="card src"><div class="src__top"><strong class="src__n">' + V.esc(e.name) + '</strong><span class="stage">' + (e.enabled ? "Checked" : "Not checked") + "</span></div>" +
      '<p class="src__m">' + V.esc([nice(e.sector), e.provider, e.live + " live", e.matches ? e.matches + " match" + (e.matches === 1 ? "" : "es") : "no matches"].filter(Boolean).join(" · ")) + "</p>" +
      (vc.length || e.verified_at ? '<p class="src__m">' + V.esc(vc.join(" · ") + (e.verified_at ? (vc.length ? " · " : "") + "checked " + e.verified_at : "")) + "</p>" : "") +
      (e.notes ? '<p class="src__m" title="' + V.esc(e.notes) + '">' + V.esc(trunc(e.notes, 120)) + "</p>" : "") + "</div>";
  }
  function load(keepFocus) {
    var p = new URLSearchParams(); if (SR.sector) p.set("sector", SR.sector); if (SR.enabled) p.set("enabled", SR.enabled);
    V.api("/api/sources?" + p).then(function (d) {
      if (location.hash !== "#sources") return;
      var n = { ok: 0, warn: 0, bad: 0 }; d.health.forEach(function (h) { n[h.rag] = (n[h.rag] || 0) + 1; });
      var bad = d.health.filter(function (h) { return h.rag === "bad"; }), rest = d.health.filter(function (h) { return h.rag !== "bad"; });
      V.view.innerHTML = '<h1>Job sources</h1><p class="sub">' + (d.health.length ? (n.bad ? n.bad + " of " + d.health.length + " sources are failing, so some new jobs may be missing." : n.warn ? n.warn + " of " + d.health.length + " sources need a look." : "All " + d.health.length + " sources are working.") : "Where jobs come from, and whether each source is working.") + "</p>" +
        (d.health.length ? '<div class="row src__sum"><span class="stage" data-rag="ok">' + n.ok + ' working</span><span class="stage" data-rag="warn">' + n.warn + ' to check</span><span class="stage" data-rag="bad">' + n.bad + " failing</span></div>" +
          (bad.length ? "<h2>Failing</h2>" + bad.map(health).join("") : "") +
          '<details class="card fold"' + (bad.length ? "" : " open") + "><summary>" + (bad.length ? "Other sources (" + rest.length + ")" : "All sources (" + rest.length + ")") + '</summary><div class="fold__b">' + rest.map(health).join("") + "</div></details>"
          : '<p class="empty">No source has run yet. Health shows up after the first run.</p>') +
        "<h2>Employers watched</h2><p class=\"sub\">Jobwatch checks these employers' own careers systems directly, not only the job boards. Live means seen in the last 7 days.</p>" +
        '<div class="row src__tools"><label class="src__f">Sector<select class="src__sel" id="srsector"><option value="">All sectors</option>' + d.sectors.map(function (s) { return '<option value="' + V.esc(s) + '"' + (s === SR.sector ? " selected" : "") + ">" + V.esc(nice(s)) + "</option>"; }).join("") + "</select></label>" +
        '<label class="src__f">Checking<select class="src__sel" id="srenabled"><option value="">All</option><option value="1"' + (SR.enabled === "1" ? " selected" : "") + '>Checked only</option><option value="0"' + (SR.enabled === "0" ? " selected" : "") + ">Not checked only</option></select></label>" +
        (SR.sector || SR.enabled ? '<button class="btn" data-srclear>Clear</button>' : "") + "</div>" +
        '<p class="src__m" role="status">' + d.employers.length + (d.employers.length === 1 ? " employer" : " employers") + "</p>" +
        (d.employers.length ? d.employers.slice(0, SHOW).map(emp).join("") + (d.employers.length > SHOW ? '<button class="btn" data-srmore>Show all ' + d.employers.length + " employers</button>" : "") : '<p class="empty">No employers match. Try another sector or clear the filter.</p>');
      if (keepFocus) { var f = document.getElementById(keepFocus); if (f) f.focus(); }
    }).catch(function (e) { V.view.innerHTML = '<h1>Job sources</h1><p class="empty">' + V.esc(e.message) + "</p>"; });
  }
  V.page("sources", function () { SHOW = 20; SR = { sector: "", enabled: "" }; load(); });
  document.addEventListener("click", function (e) { if (location.hash !== "#sources") return; if (e.target.closest("[data-srclear]")) { SR = { sector: "", enabled: "" }; SHOW = 20; load(); } if (e.target.closest("[data-srmore]")) { SHOW = 100000; load(); } });
  document.addEventListener("change", function (e) {
    if (location.hash !== "#sources") return;
    if (e.target.id === "srsector") { SR.sector = e.target.value; SHOW = 20; load("srsector"); }
    if (e.target.id === "srenabled") { SR.enabled = e.target.value; SHOW = 20; load("srenabled"); }
  });
})();

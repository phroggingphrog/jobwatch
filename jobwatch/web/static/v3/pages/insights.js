(function () {
  "use strict";
  var V = window.V3, META = null, CAP = 10;
  function nice(s) { return String(s || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function num(n) { return Number(n || 0).toLocaleString("en-US"); }
  function pctOf(a, b) { return b ? Math.round(100 * a / b) : 0; }
  function pct(x, d) { return (x * 100).toFixed(d ? 1 : 0) + "%"; }
  function day(iso, wk) { var p = String(iso).split("-"), d = new Date(+p[0], +p[1] - 1, +p[2]); return d.toLocaleDateString("en-AU", wk ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short" }); }
  function bar(label, value, w, extra) {
    return '<li><span>' + V.esc(label) + '</span><span class="wk-mono">' + V.esc(value) + '</span><span class="t" aria-hidden="true"><i style="width:' + w + '%"></i>' + (extra || "") + "</span></li>";
  }
  function m(t) { return '<p class="wk-sub">' + t + "</p>"; }
  function list(rows, fn, word) {
    return rows.length ? '<ul class="wk-bars">' + rows.slice(0, CAP).map(fn).join("") + "</ul>" + (rows.length > CAP ? m("+ " + (rows.length - CAP) + " smaller " + word) : "") : m("No matches yet.");
  }
  function sec(title, sub, body) { return '<div class="wk-sec"><h2 class="wk-h2">' + V.esc(title) + "</h2>" + (sub ? m(sub) : "") + '<div class="wk-panel wk-pad" style="display:flex;flex-direction:column;gap:12px">' + body + "</div></div>"; }
  function heat(ins) {
    var ser = (ins.series || []).slice(-14), mx = 0, total = 0;
    ser.forEach(function (s) { total += s[1]; if (s[1] > mx) mx = s[1]; });
    if (!total) return m("No new matches in the last " + ser.length + " days. This fills in as Jobwatch finds them.");
    return '<div class="wk-heat" role="img" aria-label="New matches per day, last ' + ser.length + " days: " + total + ' in total">' + ser.map(function (s) { return '<i class="' + (s[1] ? (s[1] >= mx * 0.6 ? "l2" : "l1") : "") + '" title="' + V.esc(day(s[0], true)) + ": " + s[1] + '"></i>'; }).join("") + "</div>" +
      '<div class="wk-row" style="justify-content:space-between"><span class="wk-sub">' + V.esc(day(ser[0][0])) + '</span><span class="wk-sub">Today</span></div>' + m(total + " new " + (total === 1 ? "match" : "matches") + " in " + ser.length + " days. Brighter means more.");
  }
  function callbacks(ins) {
    var cb = ins.callbacks || {}, all = cb._all;
    if (!all || !all.n) return m("No applications yet. Callback rates appear after you have applied to about 10 jobs. Until then the starting guess is " + pct(ins.prior_mean, 1) + ".");
    var order = ["_all"].concat(Object.keys(cb).filter(function (k) { return k !== "_all"; }));
    return (all.n < 10 ? m("Only " + all.n + (all.n === 1 ? " application" : " applications") + " so far, so these rates lean on a starting guess of " + pct(ins.prior_mean, 1) + " and firm up as you apply to more jobs.") : "") +
      '<div class="wk-rows" style="border:0">' + order.map(function (k) {
        var p = cb[k];
        return '<div class="wk-prow" style="padding-left:0;padding-right:0"><div class="grow"><div class="wk-title">' + (k === "_all" ? "All job types" : V.esc(nice(k))) + (p.n < 10 && k !== "_all" ? ' <span class="tag">small sample</span>' : "") + '</div><div class="wk-sub">' + p.successes + " callbacks from " + p.n + " applications. Likely range: " + pct(p.hdi[0]) + " to " + pct(p.hdi[1]) + '.</div></div><b class="wk-mono" style="font-size:18px">' + pct(p.mean, 1) + "</b></div>";
      }).join("") + "</div>";
  }
  function reading(rd) {
    if (!rd || !rd.progress || !rd.progress.total) return "";
    var pg = rd.progress, hw = rd.counts.why || {}, ks = Object.keys(hw).sort(function (a, b) { return hw[b] - hw[a]; });
    return sec("Is the AI getting through them?", "", "<p class=\"wk-body\"><b>" + pg.read + " of " + pg.total + "</b> matched ads read" + (pg.left ? ", " + pg.left + " still waiting" : "") + '.</p><ul class="wk-bars">' + bar("Read", pg.read + " of " + pg.total, pctOf(pg.read, pg.total)) + "</ul>" +
      (ks.length ? '<h3 class="wk-h3">Why the AI hid jobs</h3><ul class="wk-bars">' + ks.slice(0, 8).map(function (k) { return bar((META.hide_labels || {})[k] || nice(k), hw[k], pctOf(hw[k], hw[ks[0]])); }).join("") + "</ul>" : ""));
  }
  function reddit(ins) {
    if (!ins.chatter_total) return m("No Reddit posts collected in the last 30 days. This fills in when the Reddit collector has run.");
    return m(ins.chatter_total + (ins.chatter_total === 1 ? " post" : " posts") + " about the job market in the last 30 days" + (ins.hiring_posts ? ", plus " + ins.hiring_posts + " hiring " + (ins.hiring_posts === 1 ? "post" : "posts") : "") + ".") + '<h3 class="wk-h3">Themes</h3>' +
      (ins.themes.length ? '<ul class="wk-bars">' + ins.themes.slice(0, CAP).map(function (x) { return bar(nice(x[0]).replace(/^Ai /, "AI "), x[1], pctOf(x[1], ins.themes[0][1])); }).join("") + "</ul>" : m("No themes picked out yet.")) +
      (ins.by_subreddit.length ? '<div class="wk-chips">' + ins.by_subreddit.slice(0, 6).map(function (s) { return '<span class="tag">r/' + V.esc(s[0]) + " " + s[1] + "</span>"; }).join("") + "</div>" : "") + '<h3 class="wk-h3">Top posts</h3>' +
      (ins.reddit_top.length ? '<ol class="wk-prose">' + ins.reddit_top.map(function (r) { return "<li>" + (/^https?:\/\//.test(r.url || "") ? '<a href="' + V.esc(r.url) + '" target="_blank" rel="noopener noreferrer">' + V.esc(r.title) + "</a>" : V.esc(r.title)) + ' <span class="wk-sub">r/' + V.esc(r.subreddit) + (r.score != null ? " · " + r.score + " points" : "") + (r.comments != null ? " · " + r.comments + " comments" : "") + "</span></li>"; }).join("") + "</ol>" : m("No standout posts yet."));
  }
  V.page("insights", function () {
    Promise.all([META ? 0 : V.api("/api/meta").then(function (x) { META = x; }).catch(function () { META = {}; }), V.api("/api/insights"), V.api("/api/board?ai=hide").catch(function () { return null; }), V.api("/api/board?ai=show").catch(function () { return null; })]).then(function (r) {
      if (location.hash !== "#insights") return;
      var ins = r[1], rd = r[2], good = r[3], t = ins.totals || {}, cb = (ins.callbacks || {})._all || { n: 0, successes: 0 };
      var rm = (ins.remote || {}).matches || [0, 0], ra = (ins.remote || {}).all || [0, 0];
      function pd(a, b) { return b ? (100 * a / b).toFixed(1) : "0.0"; }
      var steps = [["Matched", t.matches || 0, ""], ["Rated Good", good ? good.total : 0, pctOf(good ? good.total : 0, t.matches) + "% of matched"], ["Applied", cb.n, ""], ["Callback", cb.successes, cb.n ? pctOf(cb.successes, cb.n) + "% of applied" : ""]], top = Math.max(1, steps[0][1]);
      var lede = '<b>' + num(t.matches) + "</b> jobs matched" + (good ? ", <b>" + num(good.total) + "</b> rated Good" : "") + ", you applied to <b>" + cb.n + "</b>, and <b>" + cb.successes + "</b> led to a callback." + (cb.n < 10 ? " " + (cb.n === 1 ? "One application is" : cb.n + " applications are") + " too few to show what works." : "");
      V.draw(V.head("Insights", "What Jobwatch has found, and what is working.") +
        '<div class="wk-panel wk-pad"><p class="wk-lede">' + lede + "</p></div>" +
        '<div class="wk-sec"><h2 class="wk-h2">Application funnel</h2><div class="wk-panel wk-pad" style="display:flex;flex-direction:column;gap:12px">' + steps.map(function (s, i) { return '<div class="wk-fstep' + (i >= 2 ? " g" : "") + '"><span>' + s[0] + '</span><div><div class="wk-fbar" style="width:' + Math.max(8, Math.round(100 * s[1] / top)) + '%">' + num(s[1]) + '</div></div><span class="wk-sub wk-fc">' + s[2] + "</span></div>"; }).join("") + "</div></div>" +
        sec("New matches, last 14 days", "", heat(ins)) + reading(rd) +
        sec("By job type", "All matches. Core types are the ones you asked for; fallback types are backups.", list(ins.by_arm, function (x) { return bar(x[3] + (x[1] === "core" ? "" : " (backup)"), x[2], pctOf(x[2], ins.by_arm[0][2])); }, "job types")) +
        sec("By source", "Where each match was first found.", list(ins.by_src, function (x) { return bar(x[2], x[1], pctOf(x[1], ins.by_src[0][1])); }, "sources")) +
        sec("By sector", "Matches grouped by the employer's sector.", list(ins.by_sector, function (x) { return bar(String(x[2]).replace(/^Not in registry$/i, "Outside the employer list"), x[1], pctOf(x[1], ins.by_sector[0][1])); }, "sectors")) +
        sec("Busiest employers", "Postings seen in the last 30 days. The green part is how many matched you.", ins.top.length ? '<ul class="wk-bars">' + ins.top.slice(0, CAP).map(function (x) { return bar(x[0], x[1] + " seen · " + x[2] + (x[2] === 1 ? " match" : " matches"), pctOf(x[1], ins.top[0][1]), '<b style="width:' + pctOf(x[2], ins.top[0][1]) + '%"></b>'); }).join("") + "</ul>" : m("No postings in the last 30 days.")) +
        sec("Remote jobs", "How many jobs are remote, among your matches and among everything seen.", '<ul class="wk-bars">' + bar("Your matches", pd(rm[0], rm[1]) + "% · " + rm[0] + " of " + num(rm[1]), pd(rm[0], rm[1])) + bar("All postings", pd(ra[0], ra[1]) + "% · " + ra[0] + " of " + num(ra[1]), pd(ra[0], ra[1])) + "</ul>") +
        sec("Callback rate", "A callback is an assessment, interview or offer after you applied.", callbacks(ins)) +
        '<details class="wk-fold"><summary>Reddit chatter</summary><div class="wk-fold-b" style="display:flex;flex-direction:column;gap:12px">' + reddit(ins) + "</div></details>");
    }).catch(function (e) { V.failPage("Insights", e); });
  });
})();

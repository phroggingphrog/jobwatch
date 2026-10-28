(function () {
  "use strict";
  var V = window.V3, META = null, CAP = 10;
  function nice(s) { return String(s || "").replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function num(n) { return Number(n || 0).toLocaleString("en-US"); }
  function pctOf(a, b) { return b ? Math.round(100 * a / b) : 0; }
  function pct(x, d) { return (x * 100).toFixed(d ? 1 : 0) + "%"; }
  function day(iso, wk) { var p = String(iso).split("-"), d = new Date(+p[0], +p[1] - 1, +p[2]); return d.toLocaleDateString("en-AU", wk ? { weekday: "short", day: "numeric", month: "short" } : { day: "numeric", month: "short" }); }
  function bar(label, value, w, extra) {
    return '<li class="ins__bar"><span class="ins__l">' + V.esc(label) + '</span><span class="ins__v">' + V.esc(value) + '</span><span class="ins__t" aria-hidden="true"><i style="width:' + w + '%"></i>' + (extra || "") + "</span></li>";
  }
  function list(rows, fn, word) {
    return rows.length ? '<ul class="ins__bars">' + rows.slice(0, CAP).map(fn).join("") + "</ul>" + (rows.length > CAP ? '<p class="ins__m">+ ' + (rows.length - CAP) + " smaller " + word + "</p>" : "") : '<p class="ins__m">No matches yet.</p>';
  }
  function sec(title, sub, body) { return '<section class="card ins"><h2>' + V.esc(title) + "</h2>" + (sub ? '<p class="ins__m">' + sub + "</p>" : "") + body + "</section>"; }
  function chart(ins) {
    var ser = (ins.series || []).slice(); while (ser.length > 7 && !ser[0][1]) ser.shift();
    var mx = 1, peak = null, total = 0, n = ser.length;
    ser.forEach(function (s) { total += s[1]; if (s[1] > mx || (peak === null && s[1] > 0)) { mx = s[1]; peak = s[0]; } });
    if (!total) return '<p class="ins__m">No new matches in the last ' + n + " days. This fills in as Jobwatch finds them.</p>";
    return '<svg class="ins__chart" viewBox="0 0 ' + n * 20 + ' 100" preserveAspectRatio="none" role="img" aria-label="New matches per day over the last ' + n + " days: " + total + " in total, busiest day " + V.esc(day(peak)) + " with " + mx + '.">' +
      ser.map(function (s, i) { var h = s[1] ? Math.round(s[1] / mx * 960) / 10 : 1; return '<rect class="' + (i < n - 7 ? "is-old" : "") + '" x="' + (i * 20 + 3) + '" y="' + (100 - h) + '" width="14" height="' + h + '"><title>' + V.esc(day(s[0], true)) + ": " + s[1] + "</title></rect>"; }).join("") + "</svg>" +
      '<div class="ins__axis" aria-hidden="true"><span>' + V.esc(day(ser[0][0])) + "</span><span>Today</span></div>" +
      '<p class="ins__m">' + total + " new " + (total === 1 ? "match" : "matches") + " in " + n + " days. Busiest day: " + V.esc(day(peak, true)) + " with " + mx + ". The darker bars are the last 7 days.</p>";
  }
  function callbacks(ins) {
    var cb = ins.callbacks || {}, all = cb._all;
    if (!all || !all.n) return '<p class="ins__m">No applications yet. Callback rates appear after you have applied to about 10 jobs. Until then the starting guess is ' + pct(ins.prior_mean, 1) + ".</p>";
    var order = ["_all"].concat(Object.keys(cb).filter(function (k) { return k !== "_all"; }));
    return (all.n < 10 ? '<p class="ins__m">Only ' + all.n + (all.n === 1 ? " application" : " applications") + " so far, so these rates lean on a starting guess of " + pct(ins.prior_mean, 1) + " and firm up as you apply to more jobs.</p>" : "") +
      order.map(function (k) {
        var p = cb[k];
        return '<div class="ins__cb"><div class="ins__cbh"><strong>' + (k === "_all" ? "All job types" : V.esc(nice(k))) + (p.n < 10 && k !== "_all" ? ' <span class="chip">small sample</span>' : "") + "</strong><strong>" + pct(p.mean, 1) + '</strong></div><p class="ins__m">' + p.successes + " callbacks from " + p.n + " applications. Likely range: " + pct(p.hdi[0]) + " to " + pct(p.hdi[1]) + ".</p></div>";
      }).join("");
  }
  function reading(rd) {
    if (!rd || !rd.progress || !rd.progress.total) return "";
    var pg = rd.progress, hw = rd.counts.why || {}, ks = Object.keys(hw).sort(function (a, b) { return hw[b] - hw[a]; });
    return sec("Is the AI getting through them?", "", "<p><strong>" + pg.read + " of " + pg.total + "</strong> matched ads read" + (pg.left ? ", " + pg.left + " still waiting" : "") + '.</p><ul class="ins__bars">' + bar("Read", pg.read + " of " + pg.total, pctOf(pg.read, pg.total)) + "</ul>" +
      (ks.length ? "<h3>Why the AI hid jobs</h3><ul class=\"ins__bars\">" + ks.slice(0, 8).map(function (k) { return bar((META.hide_labels || {})[k] || nice(k), hw[k], pctOf(hw[k], hw[ks[0]])); }).join("") + "</ul>" : ""));
  }
  function reddit(ins) {
    if (!ins.chatter_total) return '<p class="ins__m">No Reddit posts collected in the last 30 days. This fills in when the Reddit collector has run.</p>';
    return '<p class="ins__m">' + ins.chatter_total + (ins.chatter_total === 1 ? " post" : " posts") + " about the job market in the last 30 days" + (ins.hiring_posts ? ", plus " + ins.hiring_posts + " hiring " + (ins.hiring_posts === 1 ? "post" : "posts") : "") + ".</p><h3>Themes</h3>" +
      (ins.themes.length ? '<ul class="ins__bars">' + ins.themes.slice(0, CAP).map(function (x) { return bar(nice(x[0]).replace(/^Ai /, "AI "), x[1], pctOf(x[1], ins.themes[0][1])); }).join("") + "</ul>" : '<p class="ins__m">No themes picked out yet.</p>') +
      (ins.by_subreddit.length ? '<p class="row">' + ins.by_subreddit.slice(0, 6).map(function (s) { return '<span class="chip">r/' + V.esc(s[0]) + " " + s[1] + "</span>"; }).join("") + "</p>" : "") + "<h3>Top posts</h3>" +
      (ins.reddit_top.length ? '<ol class="ins__posts">' + ins.reddit_top.map(function (r) { return "<li>" + (/^https?:\/\//.test(r.url || "") ? '<a href="' + V.esc(r.url) + '" target="_blank" rel="noopener noreferrer">' + V.esc(r.title) + "</a>" : V.esc(r.title)) + ' <span class="ins__m">r/' + V.esc(r.subreddit) + (r.score != null ? " · " + r.score + " points" : "") + (r.comments != null ? " · " + r.comments + " comments" : "") + "</span></li>"; }).join("") + "</ol>" : '<p class="ins__m">No standout posts yet.</p>');
  }
  V.page("insights", function () {
    Promise.all([META ? 0 : V.api("/api/meta").then(function (m) { META = m; }).catch(function () { META = {}; }), V.api("/api/insights"), V.api("/api/board?ai=hide").catch(function () { return null; })]).then(function (r) {
      if (location.hash !== "#insights") return;
      var ins = r[1], rd = r[2], t = ins.totals || {};
      var rm = (ins.remote || {}).matches || [0, 0], ra = (ins.remote || {}).all || [0, 0];
      function pd(a, b) { return b ? (100 * a / b).toFixed(1) : "0.0"; }
      var kpi = [["Postings seen", t.postings], ["Matches, all time", t.matches]].concat(t.matches_30d !== t.matches ? [["Matches, 30 days", t.matches_30d]] : []).concat([["Matches, 7 days", t.matches_7d], ["Employers hiring now", t.employers_live]]);
      V.view.innerHTML = "<h1>Insights</h1><p class=\"sub\">What Jobwatch has found, and what is working.</p>" +
        '<div class="ins__kpis">' + kpi.map(function (k) { return '<div class="card ins__kpi"><strong>' + num(k[1]) + "</strong><span>" + k[0] + "</span></div>"; }).join("") + "</div>" +
        sec("New matches per day", "Last days, Melbourne time.", chart(ins)) + reading(rd) +
        sec("By job type", "All matches. Core types are the ones you asked for; fallback types are backups.", list(ins.by_arm, function (x) { return bar(x[3] + (x[1] === "core" ? "" : " (backup)"), x[2], pctOf(x[2], ins.by_arm[0][2])); }, "job types")) +
        sec("By source", "Where each match was first found.", list(ins.by_src, function (x) { return bar(x[2], x[1], pctOf(x[1], ins.by_src[0][1])); }, "sources")) +
        sec("By sector", "Matches grouped by the employer's sector.", list(ins.by_sector, function (x) { return bar(String(x[2]).replace(/^Not in registry$/i, "Outside the employer list"), x[1], pctOf(x[1], ins.by_sector[0][1])); }, "sectors")) +
        sec("Busiest employers", "Postings seen in the last 30 days. The dark part is how many matched you.", ins.top.length ? '<ul class="ins__bars">' + ins.top.slice(0, CAP).map(function (x) { return bar(x[0], x[1] + " seen · " + x[2] + (x[2] === 1 ? " match" : " matches"), pctOf(x[1], ins.top[0][1]), '<b style="width:' + pctOf(x[2], ins.top[0][1]) + '%"></b>'); }).join("") + "</ul>" : '<p class="ins__m">No postings in the last 30 days.</p>') +
        sec("Remote jobs", "How many jobs are remote, among your matches and among everything seen.", '<ul class="ins__bars">' + bar("Your matches", pd(rm[0], rm[1]) + "% · " + rm[0] + " of " + num(rm[1]), pd(rm[0], rm[1])) + bar("All postings", pd(ra[0], ra[1]) + "% · " + ra[0] + " of " + num(ra[1]), pd(ra[0], ra[1])) + "</ul>") +
        sec("Callback rate", "A callback is an assessment, interview or offer after you applied.", callbacks(ins)) +
        '<details class="card fold"><summary>Reddit chatter</summary><div class="fold__b">' + reddit(ins) + "</div></details>";
    }).catch(function (e) { V.view.innerHTML = '<h1>Insights</h1><p class="empty">' + V.esc(e.message) + "</p>"; });
  });
})();

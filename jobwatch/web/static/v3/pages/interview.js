/* Interview prep (#interview, #interview/<ref>) and follow-up drafts (#followup/<postingId>/<channel>) */
(function () {
  "use strict";
  var V = window.V3, esc = V.esc, view = V.view, timer = null;
  function stop() { clearTimeout(timer); timer = null; }
  function poll(hash, fn) { stop(); timer = setTimeout(function () { if (location.hash === hash) fn(); }, 3000); }
  window.addEventListener("hashchange", stop);
  function nice(t) { var s = String(t || "").replace(/[_-]/g, " ").trim().toLowerCase(); return s.charAt(0).toUpperCase() + s.slice(1); }
  function mine() { return /^#(interview|followup)(\/|$)/.test(location.hash); }
  function fold(title, body, open) { return '<details class="wk-fold"' + (open ? " open" : "") + "><summary>" + esc(title) + '</summary><div class="wk-fold-b wk-prose">' + body + "</div></details>"; }
  function back(href, text) { return '<a class="wk-link" href="' + href + '">← ' + esc(text) + "</a>"; }
  function field(label, name, val, o) {
    o = o || {};
    var id = "f-" + name;
    return '<div class="wk-field"><label for="' + id + '">' + esc(label) + "</label>" + (o.area ? '<textarea id="' + id + '" name="' + name + '" rows="' + (o.rows || 4) + '" maxlength="' + (o.max || 20000) + '"' + (o.ro ? " readonly" : "") + ">" + esc(val) + "</textarea>"
      : '<input id="' + id + '" name="' + name + '" type="' + (o.type || "text") + '" maxlength="' + (o.max || 500) + '" value="' + esc(val) + '"' + (o.req ? " required" : "") + (o.ph ? ' placeholder="' + esc(o.ph) + '"' : "") + ">") + "</div>";
  }
  function evidence(list) {
    return (list || []).map(function (c) { return '<details class="wk-fold ip-ev"><summary>Where this comes from: ' + esc(c.source_id) + '</summary><blockquote>' + esc(c.quote) + '</blockquote><p class="wk-sub">Source fingerprint: ' + esc(c.content_hash) + "</p></details>"; }).join("");
  }

  /* ---------- #interview : start a prep + list ---------- */
  function entry(keep, error) {
    stop();
    V.api("/api/interview").then(function (d) {
      keep = keep || {};
      V.draw(back("#applications", "Pipeline") + V.head("Prepare for an interview", "Use a job link, including a role you have not applied for. Jobwatch reads the ad and your profile and writes questions and answers to practise. This never creates an application or sends anything.") +
        '<div class="wk-steps3"><span class="wk-s on"><b>1</b>Choose the role</span><span class="wk-s"><b>2</b>Add your notes</span><span class="wk-s"><b>3</b>Get your prep</span></div>' +
        '<form class="wk-panel wk-pad wk-form" id="ip-open" novalidate>' + (error ? '<div class="wk-note bad" role="alert">' + esc(error) + "</div>" : "") +
        field("Link to the job ad", "url", keep.url, { type: "url", max: 8192, ph: "https://…" }) +
        '<details class="wk-fold"' + (error ? " open" : "") + "><summary>The ad is closed or the link does not work</summary><div class=\"wk-fold-b wk-form\"><p class=\"wk-sub\">Keep the link above and paste the whole job description here. It is marked as supplied by you.</p>" +
        field("Job title", "title", keep.title) + field("Company", "company", keep.company) + field("Full job description", "pasted_jd", keep.pasted_jd, { area: 1, rows: 10, max: 100000 }) + "</div></details>" +
        '<div class="wk-row"><button type="submit" class="btn primary">Continue</button><span class="wk-sub">Next you can add your own notes. Nothing is written until you ask.</span></div></form>' +
        '<div class="wk-sec"><h2 class="wk-h2">Your earlier prep</h2>' + (d.subjects.length ? '<div class="wk-rows">' + d.subjects.map(function (s) {
          return '<a class="wk-prow" href="#interview/' + esc(s.id) + '">' + V.co(s.company || s.title) + '<div class="grow"><div class="wk-title">' + esc(s.title) + '</div><div class="wk-sub">' + esc(s.company || "") + (s.at ? " · " + esc(s.at) : "") + '</div></div><span class="wk-sub">Open</span></a>';
        }).join("") + "</div>" : '<div class="wk-panel"><div class="wk-empty">Nothing yet. Your prep shows up here.</div></div>') + "</div>");
    }).catch(function (e) { V.failPage("Interview prep", e); });
  }

  /* ---------- #interview/<ref> : one prep ---------- */
  function report(rep, ref, kinds) {
    var dl = /^\d+$/.test(ref) ? "/jobs/" + ref + "/interview-prep/download" : "/interview-prep/subjects/" + encodeURIComponent(ref) + "/download";
    var h = '<h2 class="wk-h2">Your interview prep is ready</h2><p class="wk-body">Written from the job ad, your profile and your notes, then checked by a second model. Read the sources before you rely on anything. Nothing has been sent.</p>' +
      '<div class="wk-row"><a class="btn primary" href="' + dl + '">Download as text</a></div>';
    var head = h; h = '<div class="wk-chips" role="group" aria-label="Jump to a part">' + rep.proposal.sections.map(function (s, i) { return '<button type="button" class="chip" data-jump="ip-s' + i + '">' + esc(nice(s.title)) + "</button>"; }).join("") + "</div>";
    rep.proposal.sections.forEach(function (s, i) {
      h += '<section class="wk-sec" id="ip-s' + i + '"><h2 class="wk-h2">' + esc(nice(s.title)) + '</h2><div class="wk-rows">' + s.items.map(function (it) {
        return '<article class="wk-prose" style="padding:16px 20px"><h3 class="wk-h3">' + esc(nice(it.topic)) + '</h3><div class="wk-chips" style="margin:6px 0"><span class="tag">' + esc(kinds[it.kind] || it.kind) + "</span>" + (it.audience ? '<span class="tag">' + esc(it.audience) + "</span>" : "") + "</div><p>" + esc(it.text) + "</p>" +
          (it.question ? '<p><strong>Likely question:</strong> ' + esc(it.question) + "</p>" : "") + evidence(it.citations) +
          (it.answer ? '<p><strong>' + (it.answer_grounding === "owner_fact" ? "A fact you supplied" : "Your own record") + "</strong></p><dl>" + Object.keys(it.answer).map(function (k) { return "<div><dt>" + esc(nice(k)) + "</dt><dd>" + esc(it.answer[k]) + "</dd></div>"; }).join("") + "</dl>" + evidence(it.answer_citations) : "") + "</article>";
      }).join("") + "</div></section>";
    });
    return [head, h + fold("Sources and how this was made (" + rep.sources.length + ")", "<p>Written by " + esc(rep.writer_model) + ", checked by " + esc(rep.reviewer_model) + '.</p><p class="wk-sub">Snapshot ' + esc(rep.snapshot_hash) + " · Report " + esc(rep.proposal.draft_hash) + "</p>" +
      rep.sources.map(function (s) { return "<p><strong>" + esc(s.source_id) + "</strong> · " + esc(s.kind) + " · read " + esc(s.accessed_at || "date not recorded") + (s.url ? ' · <a class="wk-link" href="' + esc(s.url) + '" target="_blank" rel="noopener noreferrer">Open source</a>' : "") + '<br><span class="wk-sub">Fingerprint ' + esc(s.content_hash) + "</span></p>"; }).join(""))];
  }
  function prep(ref) {
    stop();
    V.api("/api/interview/" + encodeURIComponent(ref)).then(function (d) {
      if (location.hash !== "#interview/" + ref) return;
      var j = d.job, st = d.state, body;
      var go = function (retry) { return '<button type="button" class="btn ' + (retry ? "" : "primary") + '" data-start="1"' + (retry ? ' data-again="1"' : "") + ">" + (retry ? "Try again" : "Write my interview prep") + "</button>"; };
      var rest = "";
      if (st.status === "ready") { var r = report(st.report, ref, d.kinds); body = r[0]; rest = r[1]; }
      else if (st.status === "running") body = '<h2 class="wk-h2">Writing and checking your prep…</h2><p>This takes a few minutes and this page updates by itself. You can leave and come back.</p>';
      else if (st.status === "missing") body = '<h2 class="wk-h2">Ready to write</h2><p class="wk-body">Add any notes below first if you have them. Then Jobwatch writes the prep from the whole job ad and your profile. Anything it cannot find is marked unknown.</p><div class="wk-row">' + go(false) + "</div>";
      else if (st.status === "held") body = '<h2 class="wk-h2">Held back for checking</h2><p>No checked report is available yet. Try again once the problem is fixed. Earlier tries still count toward the same limits.</p><div class="wk-row">' + go(true) + "</div>";
      else if (st.status === "disabled") body = "<p>Interview prep is turned off on this install.</p>";
      else body = '<h2 class="wk-h2">Needs a check first</h2><p>The job ad, your profile or your private notes need checking. An earlier report is hidden when its sources change.</p>';
      var bk = j.standalone ? back("#interview", "Interview prep") : back("#job/" + esc(ref), "Back to the job");
      V.draw(bk + V.head(j.title, esc(j.company || "Interview prep"), j.standalone ? "" : '<a class="btn" href="#interview">Prep for another interview</a>') +
        '<div class="wk-panel wk-pad wk-prose" id="ip-status">' + body + "</div>" + rest +
        (j.jd_source ? fold("The job description Jobwatch used", "<p>Source: " + esc(j.jd_source) + (j.acquired_at ? " · saved " + esc(j.acquired_at) : "") + (j.source_link ? ' · <a class="wk-link" href="' + esc(j.source_link) + '" target="_blank" rel="noopener noreferrer">Open the original</a>' : "") + '</p><pre class="wk-evidence">' + esc(j.ad_text) + "</pre>") : "") +
        '<form id="ip-inputs" data-rev="' + d.revision + '"><details class="wk-fold"' + (st.status === "missing" ? " open" : "") + "><summary>Your private notes (optional)</summary><div class=\"wk-fold-b wk-form\"><p class=\"wk-sub\">Notes make the prep fit you. They are never used in web searches. Save before you write; changing notes hides the old report.</p>" +
        d.fields.map(function (f) { return field(f[1], f[0], d.inputs[f[0]], { area: 1, max: f[0] === "prior_compensation" ? 10000 : 20000 }); }).join("") +
        '<p class="wk-sub">Up to 60,000 characters in total. Leave blank what you do not have.</p><div class="wk-row"><button type="submit" class="btn">Save notes</button></div></div></details></form>');
      if (st.status === "running") poll("#interview/" + ref, function () { prep(ref); });
    }).catch(function (e) { V.failPage("Interview prep", e); });
  }

  /* ---------- #followup/<postingId>/<channel> ---------- */
  function follow(pid, channel) {
    stop();
    channel = channel === "linkedin" ? "linkedin" : "email";
    var hash = "#followup/" + pid + "/" + channel, name = channel === "linkedin" ? "LinkedIn message" : "email";
    V.api("/api/followup-draft/" + encodeURIComponent(pid) + "?channel=" + channel).then(function (d) {
      if (location.hash !== hash) return;
      var st = d.status, body;
      var go = function (retry) { return '<button type="button" class="btn ' + (retry ? "" : "primary") + '" data-draft="1"' + (retry ? ' data-again="1"' : "") + ">" + (retry ? "Try again" : "Write my " + name) + "</button>"; };
      if (st === "ready") body = '<h2 class="wk-h2">Your draft is ready</h2><p>A second model checked it against your application and profile. Read it before you send it. Nothing has been sent.</p>' +
        (channel === "email" ? field("Subject", "subject", d.proposal.subject, { area: 1, rows: 2, ro: 1 }) : "") + field("Message", "body", d.proposal.body, { area: 1, rows: 12, ro: 1 }) +
        '<div class="wk-row"><button type="button" class="btn primary" data-copy="1">Copy message</button></div><p class="wk-sub">Paste it into your ' + (channel === "linkedin" ? "LinkedIn chat" : "email") + " and send it yourself. Then record it under Applications.</p>";
      else if (st === "running") body = '<h2 class="wk-h2">Writing and checking your follow-up…</h2><p>This page updates by itself when it is done. Nothing is sent automatically.</p>';
      else if (st === "missing") body = '<h2 class="wk-h2">Ready to write</h2><p>Jobwatch uses your application history and profile to write a ' + name + ", then has a second model check it.</p><div class=\"wk-row\">" + go(false) + "</div>";
      else if (st === "disabled") body = "<p>Follow-up drafts are turned off on this install.</p>";
      else if (st === "held") body = '<h2 class="wk-h2">Held back for checking</h2><p>No checked draft is available. Nothing has been sent. Try again once the problem is fixed. Earlier tries still count toward the same limits.</p><div class="wk-row">' + go(true) + "</div>";
      else body = '<h2 class="wk-h2">Not ready yet</h2><p>It may not be time to follow up, or the application dates, job ad or profile need checking. An earlier draft is hidden when these change.</p>';
      V.draw(back("#applications", "Pipeline") + V.head("Follow up: " + d.job.title, esc(d.job.company || "")) +
        '<div class="wk-chips" role="group" aria-label="Where to send it">' + [["email", "Email"], ["linkedin", "LinkedIn"]].map(function (c) { return '<a class="chip" href="#followup/' + esc(pid) + "/" + c[0] + '" aria-pressed="' + (c[0] === channel) + '">' + c[1] + "</a>"; }).join("") + "</div>" +
        '<div class="wk-panel wk-pad wk-prose wk-form">' + body + "</div>");
      if (st === "running") poll(hash, function () { follow(pid, channel); });
    }).catch(function (e) { V.failPage("Follow-up draft", e); });
  }

  /* ---------- events (registered once, only act on these pages) ---------- */
  document.addEventListener("click", function (e) {
    if (!mine()) return;
    var t = e.target.closest("[data-jump]");
    if (t) { var el = document.getElementById(t.dataset.jump); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); return; }
    var p = location.hash.slice(1).split("/");
    t = e.target.closest("[data-start]");
    if (t && p[0] === "interview") { t.disabled = true; V.api("/api/interview/" + encodeURIComponent(p[1]) + "/start", { retry: !!t.dataset.again }).then(function (r) { V.toast(r.toast || "Started"); prep(p[1]); }).catch(function (err) { t.disabled = false; V.fail(err); }); return; }
    t = e.target.closest("[data-draft]");
    if (t && p[0] === "followup") { t.disabled = true; var ch = p[2] === "linkedin" ? "linkedin" : "email"; V.api("/api/followup-draft/" + encodeURIComponent(p[1]), { channel: ch, retry: !!t.dataset.again }).then(function (r) { V.toast(r.toast || "Started"); follow(p[1], ch); }).catch(function (err) { t.disabled = false; V.fail(err); }); return; }
    t = e.target.closest("[data-copy]");
    if (t) { var ta = document.getElementById("f-body"); ta.select(); (navigator.clipboard ? navigator.clipboard.writeText(ta.value) : Promise.reject()).then(function () { V.toast("Copied"); }, function () { try { document.execCommand("copy"); V.toast("Copied"); } catch (x) { V.toast("Select the text and copy it", true); } }); }
  });
  document.addEventListener("submit", function (e) {
    if (!mine()) return;
    var f = e.target, p = location.hash.slice(1).split("/");
    if (f.id === "ip-open") {
      e.preventDefault();
      var v = {}; ["url", "title", "company", "pasted_jd"].forEach(function (k) { v[k] = f.elements[k].value.trim(); });
      if (!v.url) { entry(v, "Add the link to the job ad first."); return; }
      f.querySelector("[type=submit]").disabled = true;
      V.api("/api/interview/open", v).then(function (r) { location.hash = "#interview/" + r.ref; }).catch(function (err) { entry(v, err.message); });
    } else if (f.id === "ip-inputs") {
      e.preventDefault();
      var b = { revision: Number(f.dataset.rev) || 0 }; Array.prototype.forEach.call(f.elements, function (el) { if (el.name) b[el.name] = el.value; });
      f.querySelector("[type=submit]").disabled = true;
      V.api("/api/interview/" + encodeURIComponent(p[1]) + "/inputs", b).then(function (r) { V.toast(r.toast || "Saved"); prep(p[1]); }).catch(function (err) { f.querySelector("[type=submit]").disabled = false; V.fail(err); });
    }
  });

  V.page("interview", function (ref) { if (ref) prep(ref); else entry(); });
  V.page("followup", function (pid, channel) { follow(pid, channel); });
})();

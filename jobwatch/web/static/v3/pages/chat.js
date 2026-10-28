/* Chat: a calm conversation column. Same data and POST calls as the old Chat page. */
(function () {
  "use strict";
  var V = window.V3, esc = V.esc, view = V.view;
  var C = { busy: false, skip: [], change: "" };
  var CODE_WORDS = { model_unavailable: "the AI model was busy", model_invalid_response: "the AI gave an unreadable answer", invalid_requirements: "the ad's requirements could not be read",
    posting_unavailable: "the ad is gone", invalid_citation: "the AI cited something it could not back up", invalid_tool_arguments: "the AI made a malformed request", insufficient_evidence: "the ad did not give enough to judge" };

  function prose(text) {
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
  function chatWords(t) {
    return V.clean(String(t || "").replace(/`?\b([a-z]+(?:_[a-z]+)+)\b`?/g, function (m, c) { return CODE_WORDS[c] || c; })
      .replace(/\s*Claude Code needs to look[^.]*\./g, "").replace(/\bdlq\b/gi, "failed-jobs queue").replace(/\bREADY\b/g, "ready").replace(/\s*\(?\bT\d+\b\)?/g, ""));
  }
  function noticeWords(t) {
    var m = /stopped on "(.*)" \((\w+)\)/.exec(String(t));
    if (!m) return chatWords(String(t).replace(/^Error:\s*/, "").replace(/\s*Claude Code needs[^.]*\.?.*$/, ""));
    return "Couldn't finish reading \"" + m[1] + "\": " + (CODE_WORDS[m[2]] || m[2].replace(/_/g, " ")) + ". It will retry.";
  }

  function msgHtml(m) {
    if (m.role === "user") return '<li class="cmsg cmsg--me"><p>' + esc(m.text) + "</p></li>";
    if (m.notice === "ready") return '<li class="cmsg cmsg--note card"><span>' + esc(m.text) + "</span>" + (m.job ? ' <a class="btn" href="#job/' + esc(m.job) + '">Open job</a>' : "") + "</li>";
    return '<li class="cmsg cmsg--bot"><div class="prose">' + prose(chatWords(m.text)) + '</div><p class="cmsg__t">' + esc(m.time || "") + "</p></li>";
  }
  function askHtml(a) {
    if (!a) return "";
    var opts = a.verify
      ? '<button type="button" class="btn btn--main" data-qa="keep">Yes, that\'s right</button><button type="button" class="btn" data-qa="change">Change it</button>'
      : (a.options || []).map(function (o, i) { return '<button type="button" class="btn" data-qa="' + i + '">' + esc(o[0]) + "</button>"; }).join("") + '<button type="button" class="btn btn--quiet" data-qa="skip">Not now</button>';
    return '<section class="card cask" data-field="' + esc(a.id) + '"><p class="cask__k">Quick question' + (a.left ? " · " + a.left + " left" : "") + '</p><p class="cask__q">' + esc(a.question) + '</p><div class="row">' + opts + "</div>" +
      (a.verify ? "" : '<div class="cask__other"><input class="cinput" id="qaother" maxlength="300" aria-label="Your answer" placeholder="' + ((a.options || []).length ? "Or type your own answer" : "Type your answer") + '"><button type="button" class="btn" data-qa="other">Save</button></div>') + "</section>";
  }
  function down() { window.scrollTo(0, document.body.scrollHeight); }
  function here() { return location.hash === "#chat"; }

  function render() {
    V.api("/api/chat?skip=" + encodeURIComponent(C.skip.join(",")) + (C.change ? "&change=" + encodeURIComponent(C.change) : "")).then(function (d) {
      if (!here()) return;
      var msgs = (d.messages || []).filter(function (m) { return String(m.text || "").trim(); });
      var notices = msgs.filter(function (m) { return m.notice === "error"; }), talk = msgs.filter(function (m) { return m.notice !== "error"; });
      var nHtml = notices.length ? '<details class="card fold cnotes"><summary>' + notices.length + " background problem" + (notices.length > 1 ? "s" : "") + '</summary><div class="fold__b"><ul>' + notices.map(function (m) { return "<li>" + esc(noticeWords(m.text)) + "</li>"; }).join("") + "</ul></div></details>" : "";
      view.innerHTML = '<div class="chat"><h1>Ask Jobwatch</h1><p class="sub">Ask about your jobs. Nothing is sent to an employer from here.</p>' + nHtml +
        '<ul class="clog" id="cmsgs" role="log" aria-live="polite">' + talk.map(msgHtml).join("") + "</ul>" +
        (talk.length ? "" : '<p class="empty">No messages yet. Try one of these, or type your own.</p>') +
        askHtml(d.ask) +
        '<div class="cdock">' + (talk.length ? "" : '<div class="row cchips">' + (d.suggestions || []).map(function (s) { return '<button type="button" class="chip chip--btn" data-ask="' + esc(s) + '">' + esc(s) + "</button>"; }).join("") + "</div>") +
        '<form class="cform" id="cform"><label class="sr" for="cin">Message</label><textarea class="cinput" id="cin" rows="1" placeholder="Ask about a job"></textarea><button type="submit" class="btn btn--main" id="csend">Send</button></form></div></div>';
      down();
      V.refreshNav();
    }).catch(function (e) { view.innerHTML = '<h1>Ask Jobwatch</h1><p class="empty">' + esc(e.message) + '</p><button class="btn" data-chatretry>Try again</button>'; });
  }
  function answerAsk(choice) {
    var box = document.querySelector(".cask"); if (!box) return;
    var other = document.getElementById("qaother");
    V.api("/api/chat/ask", { field: box.dataset.field, choice: choice, other: other && choice === "other" ? other.value : "", skip: C.skip })
      .then(function (r) { C.skip = r.skip || C.skip; C.change = r.change || ""; render(); }).catch(V.fail);
  }
  function send(text) {
    text = String(text || "").trim();
    if (!text || C.busy) return;
    var list = document.getElementById("cmsgs"); if (!list) return;
    C.busy = true;
    var btn = document.getElementById("csend"); if (btn) btn.disabled = true;
    var chips = document.querySelector(".cchips"); if (chips) chips.remove();
    var empty = document.querySelector(".chat > .empty"); if (empty) empty.remove();
    list.insertAdjacentHTML("beforeend", msgHtml({ role: "user", text: text }) + '<li class="cmsg cmsg--bot" id="cwait"><p class="cmsg__t" aria-busy="true">Thinking…</p></li>');
    down();
    V.api("/api/chat", { text: text }).then(function (d) {
      var w = document.getElementById("cwait"); if (w) w.outerHTML = msgHtml({ role: "assistant", text: d.reply, time: "now" });
    }).catch(function (e) {
      var w = document.getElementById("cwait"); if (w) w.outerHTML = '<li class="cmsg cmsg--note card"><span>' + esc(e.message) + " Your message is saved.</span></li>";
    }).then(function () { C.busy = false; var b = document.getElementById("csend"); if (b) b.disabled = false; down(); });
  }

  document.addEventListener("click", function (e) {
    if (!here()) return;
    var t = e.target.closest("[data-ask]"); if (t) { send(t.dataset.ask); return; }
    t = e.target.closest("[data-qa]"); if (t) { answerAsk(t.dataset.qa); return; }
    t = e.target.closest("[data-chatretry]"); if (t) render();
  });
  document.addEventListener("submit", function (e) {
    if (!here() || e.target.id !== "cform") return;
    e.preventDefault();
    var i = document.getElementById("cin"), v = i.value; if (C.busy || !v.trim()) return; i.value = ""; i.style.height = ""; send(v);
  });
  document.addEventListener("keydown", function (e) {
    if (!here() || e.target.id !== "cin" || e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    e.preventDefault(); document.getElementById("cform").requestSubmit();
  });
  document.addEventListener("input", function (e) {
    if (!here() || e.target.id !== "cin") return;
    e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
  });

  V.page("chat", function () { C.skip = []; C.change = ""; document.title = "Ask Jobwatch – Jobwatch"; render(); });
})();

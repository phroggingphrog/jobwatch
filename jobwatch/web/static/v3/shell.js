/* Shared shell behaviour for every page (SPA and server pages): theme, menu, counts, notifications.
   Loaded in <head> without defer so the saved theme is set before first paint. No inline script (CSP). */
(function () {
  "use strict";
  var KEY = "jw-theme", root = document.documentElement;
  function saved() { try { return localStorage.getItem(KEY) === "light" ? "light" : "dark"; } catch (e) { return "dark"; } }
  function apply(t) {
    root.setAttribute("data-theme", t);
    var b = document.getElementById("themeBtn");
    if (b) { b.setAttribute("aria-pressed", t === "light" ? "true" : "false"); }
    var m = document.querySelector('meta[name="theme-color"]');
    if (m) { m.setAttribute("content", t === "light" ? "#faf9f5" : "#0f1116"); }
  }
  apply(saved());

  var NAV = {};
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function counts() {
    document.querySelectorAll("[data-count]").forEach(function (el) {
      var n = NAV[el.getAttribute("data-count")] || 0;
      el.textContent = n > 99 ? "99+" : String(n);
      el.hidden = !n;
    });
    var items = [];
    if (NAV.inbox) { items.push(["/#inbox", "accent", NAV.inbox + " mail repl" + (NAV.inbox === 1 ? "y" : "ies") + " to confirm", "Jobwatch needs a yes or no."]); }
    if (NAV.sources_bad) { items.push(["/#sources", "warn", NAV.sources_bad + " job source" + (NAV.sources_bad === 1 ? " is" : "s are") + " failing", "New jobs from it may be missing."]); }
    if (NAV.chat) { items.push(["/#chat", "accent", NAV.chat + " new message" + (NAV.chat === 1 ? "" : "s") + " from Jobwatch", "Open the chat to read it."]); }
    var n = items.length, badge = document.getElementById("notifN"), list = document.getElementById("notifList");
    if (badge) { badge.textContent = String(n); badge.hidden = !n; }
    if (list) {
      list.innerHTML = n ? items.map(function (i) { return '<a class="wk-rc" href="' + i[0] + '"><span class="pip" data-t="' + i[1] + '" aria-hidden="true"></span><span><b>' + esc(i[2]) + "</b><i>" + esc(i[3]) + "</i></span></a>"; }).join("") : '<p class="wk-sub">Nothing needs you right now.</p>';
    }
    var h = document.getElementById("health");
    if (h && NAV.sources_bad !== undefined) {
      h.hidden = false;
      document.getElementById("healthPip").setAttribute("data-t", NAV.sources_bad ? "warn" : "ok");
      document.getElementById("healthT").textContent = NAV.sources_bad ? NAV.sources_bad + " source" + (NAV.sources_bad === 1 ? "" : "s") + " failing" : "Sources healthy";
    }
  }
  function refresh() {
    return fetch("/api/nav", { headers: { accept: "application/json" } }).then(function (r) { return r.ok ? r.json() : {}; }).then(function (n) { NAV = n || {}; counts(); }).catch(function () { });
  }

  /* The SPA calls JW.page(key, crumbHtml) on every route change; server pages set data-page in the markup. */
  function setActive(key, crumb) {
    document.body.setAttribute("data-page", key || "");
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      var on = a.getAttribute("data-nav") === key;
      a.classList.toggle("on", on);
      if (on) { a.setAttribute("aria-current", "page"); } else { a.removeAttribute("aria-current"); }
    });
    var c = document.getElementById("crumb");
    if (c && crumb !== undefined) { c.innerHTML = crumb; }
    document.body.classList.remove("nav-open");
    var mb = document.getElementById("menuBtn"); if (mb) { mb.setAttribute("aria-expanded", "false"); }
  }
  window.JW = { page: setActive, refreshNav: refresh, esc: esc, nav: function () { return NAV; } };

  document.addEventListener("click", function (e) {
    var t = e.target.closest("#themeBtn");
    if (t) {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      try { localStorage.setItem(KEY, next); } catch (x) { }
      apply(next);
      return;
    }
    if (e.target.closest("#menuBtn") || e.target.closest("#tabMenu")) {
      var open = !document.body.classList.contains("nav-open");
      document.body.classList.toggle("nav-open", open);
      var mb = document.getElementById("menuBtn"); if (mb) { mb.setAttribute("aria-expanded", open ? "true" : "false"); }
      return;
    }
    if (document.body.classList.contains("nav-open") && !e.target.closest("#rail")) { document.body.classList.remove("nav-open"); }
    var n = document.getElementById("notif");
    if (n && n.open && !e.target.closest("#notif")) { n.open = false; }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") { return; }
    document.body.classList.remove("nav-open");
    var n = document.getElementById("notif"); if (n) { n.open = false; }
  });
  var toastTimer = null;
  window.jwToast = function (msg, bad) {
    var t = document.getElementById("toast"); if (!t || !msg) { return; }
    t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, bad ? 6000 : 2800);
  };
  document.addEventListener("htmx:afterSwap", function (ev) {
    var n = ev.target && ev.target.querySelector ? ev.target.querySelector("[data-toast]") : null;
    if (n) { window.jwToast(n.getAttribute("data-toast"), n.hasAttribute("data-error")); n.removeAttribute("data-toast"); }
  });
  document.addEventListener("htmx:responseError", function (ev) {
    window.jwToast("That did not work (" + (ev.detail && ev.detail.xhr ? ev.detail.xhr.status : "") + ")", true);
  });
  document.addEventListener("DOMContentLoaded", function () { apply(saved()); refresh(); });
})();

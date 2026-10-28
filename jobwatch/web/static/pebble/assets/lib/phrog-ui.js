/* PhrogVPS UI behaviour. Vanilla, no dependencies, data-attribute driven.
   Everything is optional: CSS-only components work without this file.
   Hooks: data-ph-open="#dialogId", data-ph-close, data-ph-toggle (row expand), data-ph-copy="text|#id",
          data-ph-theme="auto|phrog-light|phrog-dark", data-ph-toast="message" [data-ph-toast-kind=error],
          [role=tablist] (auto), .ph-dropdown (auto), #nav-drawer drawer (auto).
   API: window.PhrogUI = { setTheme, toast, openDialog, closeDialog } */
(function () {
  "use strict";
  var doc = document, root = doc.documentElement;
  var FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';
  function qs(s, c) { return (c || doc).querySelector(s); }
  function qsa(s, c) { return Array.prototype.slice.call((c || doc).querySelectorAll(s)); }
  function visible(el) { return !el.hidden && el.offsetParent !== null || el === doc.activeElement; }
  function typing(t) { return t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) || t.isContentEditable); }

  /* ---- Theme helper (C49) ---- */
  function setTheme(name) {
    var KEY = "jobwatch-pebble-preview-theme-v1";
    if (name === "auto") {
      root.removeAttribute("data-theme");
      var dark = window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches;
      root.setAttribute("data-theme", dark ? "phrog-dark" : "phrog-light");
      root.setAttribute("data-theme-mode", "auto");
    } else {
      root.setAttribute("data-theme", name);
      root.setAttribute("data-theme-mode", name);
    }
    try { localStorage.setItem(KEY, name); } catch (e) {}
    qsa("[data-ph-theme]").forEach(function (b) { b.setAttribute("aria-checked", String(b.getAttribute("data-ph-theme") === name)); });
    var label = qs("#themeName");
    if (label) label.textContent = name === "auto" ? "Auto" : name === "phrog-dark" ? "House dark" : "House light";
  }

  /* ---- Dialog and sheet (C54, C55): native <dialog>, focus return, backdrop click ---- */
  var openers = new WeakMap();
  function openDialog(dlg, opener) {
    if (!dlg || dlg.open) return;
    openers.set(dlg, opener || doc.activeElement);
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    var first = qs("[autofocus]", dlg) || qs("input:not([type=hidden]),select,textarea", dlg) || qs(FOCUSABLE, dlg);
    if (first) first.focus();
  }
  function closeDialog(dlg) {
    if (!dlg) return;
    if (dlg.close) dlg.close(); else dlg.removeAttribute("open");
  }
  doc.addEventListener("close", function (e) {
    var dlg = e.target, op = openers.get(dlg);
    if (op && op.focus && doc.contains(op)) op.focus();
  }, true);
  doc.addEventListener("click", function (e) {
    var dlg = e.target;
    if (dlg && dlg.tagName === "DIALOG" && dlg.classList.contains("ph-dialog") || dlg.classList && dlg.classList.contains("ph-sheet")) {
      var r = dlg.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) closeDialog(dlg); // backdrop
    }
  });
  /* Fallback focus trap for browsers without showModal */
  doc.addEventListener("keydown", function (e) {
    var dlg = e.target.closest && e.target.closest("dialog[open]");
    if (!dlg) return;
    if (e.key === "Escape" && !dlg.showModal) { closeDialog(dlg); return; }
    if (e.key !== "Tab") return;
    var f = qsa(FOCUSABLE, dlg).filter(visible);
    if (!f.length) return;
    var a = f[0], z = f[f.length - 1];
    if (e.shiftKey && doc.activeElement === a) { e.preventDefault(); z.focus(); }
    else if (!e.shiftKey && doc.activeElement === z) { e.preventDefault(); a.focus(); }
  });

  /* ---- Tabs (C46): arrows, Home, End; selected tab is the only tab stop ---- */
  doc.addEventListener("keydown", function (e) {
    var tab = e.target.closest && e.target.closest('[role="tab"]');
    if (!tab) return;
    var list = tab.closest('[role="tablist"]'), tabs = qsa('[role="tab"]:not([disabled])', list), i = tabs.indexOf(tab), n = -1;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") n = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft" || e.key === "ArrowUp") n = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") n = 0; else if (e.key === "End") n = tabs.length - 1;
    if (n < 0) return;
    e.preventDefault(); selectTab(tabs[n]); tabs[n].focus();
  });
  function selectTab(tab) {
    var list = tab.closest('[role="tablist"]');
    qsa('[role="tab"]', list).forEach(function (t) {
      var on = t === tab, id = t.getAttribute("aria-controls"), p = id && doc.getElementById(id);
      t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1;
      if (p) p.hidden = !on;
    });
  }

  /* ---- Dropdown (C49) ---- */
  function menuOf(btn) { return doc.getElementById(btn.getAttribute("aria-controls")); }
  function setMenu(btn, open, focusBtn) {
    var m = menuOf(btn); if (!m) return;
    btn.setAttribute("aria-expanded", String(open)); m.hidden = !open;
    if (open) { var it = qs('[aria-checked="true"],[role^="menuitem"]', m); if (it) it.focus(); }
    else if (focusBtn) btn.focus();
  }
  doc.addEventListener("keydown", function (e) {
    var m = e.target.closest && e.target.closest(".ph-dropdown .ph-menu"), btn;
    if (m) {
      btn = qs('[aria-controls="' + m.id + '"]');
      var items = qsa('[role^="menuitem"]', m), i = items.indexOf(doc.activeElement);
      if (e.key === "Escape") { e.preventDefault(); setMenu(btn, false, true); }
      else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
      else if (e.key === "Tab") setMenu(btn, false, false);
    } else if ((e.key === "ArrowDown") && (btn = e.target.closest && e.target.closest('.ph-dropdown > [aria-haspopup]'))) {
      e.preventDefault(); setMenu(btn, true);
    }
  });

  /* ---- Toast (C22, C60) ---- */
  function toast(msg, kind, icon) {
    var box = qs(".ph-toasts");
    if (!box) { box = doc.createElement("div"); box.className = "ph-toasts"; box.setAttribute("role", "status"); box.setAttribute("aria-live", "polite"); doc.body.appendChild(box); }
    var err = kind === "error", el = doc.createElement("div");
    el.className = "ph-alert ph-alert--soft ph-alert--" + (err ? "error" : "success");
    if (err) el.setAttribute("role", "alert");
    var svg = doc.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ph-icon"); svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
    var use = doc.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#lucide-" + (icon || (err ? "circle-alert" : "check")));
    svg.appendChild(use);
    var sp = doc.createElement("span"); sp.textContent = msg; // textContent: never HTML
    el.appendChild(svg); el.appendChild(sp); box.appendChild(el);
    setTimeout(function () {
      el.classList.add("ph-toast--leaving");
      setTimeout(function () { el.remove(); }, 160);
    }, 2400);
    return el;
  }

  /* ---- Copy snippet ---- */
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) return navigator.clipboard.writeText(text);
    return new Promise(function (ok, no) {
      var t = doc.createElement("textarea"); t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
      doc.body.appendChild(t); t.select();
      try { doc.execCommand("copy") ? ok() : no(); } catch (x) { no(x); } t.remove();
    });
  }

  /* ---- Click delegation ---- */
  doc.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-ph-open],[data-ph-close],[data-ph-toggle],[data-ph-copy],[data-ph-theme],[data-ph-toast],[role=tab],.ph-dropdown > [aria-haspopup]");
    if (!t) { qsa('.ph-dropdown > [aria-expanded="true"]').forEach(function (b) { setMenu(b, false, false); }); return; }
    if (t.hasAttribute("data-ph-open")) { e.preventDefault(); openDialog(qs(t.getAttribute("data-ph-open")), t); }
    else if (t.hasAttribute("data-ph-close")) { var d = t.closest("dialog"); if (d) { e.preventDefault(); closeDialog(d); } }
    else if (t.hasAttribute("data-ph-toggle")) {
      var on = t.getAttribute("aria-expanded") !== "true", p = doc.getElementById(t.getAttribute("aria-controls"));
      t.setAttribute("aria-expanded", String(on)); if (p) p.hidden = !on; // row keeps its place: no focus move
    }
    else if (t.hasAttribute("data-ph-copy")) {
      var v = t.getAttribute("data-ph-copy"), src = v.charAt(0) === "#" && qs(v), text = src ? (src.value || src.textContent) : v;
      copyText(text).then(function () { toast(t.getAttribute("data-ph-copied") || "Copied"); }, function () { toast("Not copied. Select the text and copy it by hand.", "error"); });
    }
    else if (t.hasAttribute("data-ph-theme")) { setTheme(t.getAttribute("data-ph-theme")); var dd = t.closest(".ph-dropdown"); if (dd) setMenu(qs("[aria-haspopup]", dd), false, true); }
    else if (t.hasAttribute("data-ph-toast")) toast(t.getAttribute("data-ph-toast"), t.getAttribute("data-ph-toast-kind"));
    else if (t.getAttribute("role") === "tab") selectTab(t);
    else { var open = t.getAttribute("aria-expanded") !== "true"; qsa('.ph-dropdown > [aria-expanded="true"]').forEach(function (b) { if (b !== t) setMenu(b, false, false); }); setMenu(t, open, false); }
  });

  /* ---- Drawer (C39, C40, C44): Escape closes, focus returns to the menu button ---- */
  var toggle = qs("#nav-drawer.ph-drawer__toggle, #nav-drawer");
  if (toggle && toggle.type === "checkbox") {
    var btn = function () { return qs('label[for="nav-drawer"].ph-menu-button, label[for="nav-drawer"][role=button]'); };
    toggle.addEventListener("change", function () {
      var b = btn(); if (b) b.setAttribute("aria-expanded", String(toggle.checked));
      if (toggle.checked) { var a = qs(".ph-sidebar a[href], .ph-sidebar button"); if (a) a.focus(); }
    });
    doc.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && toggle.checked && !e.target.closest("dialog[open]")) { toggle.checked = false; toggle.dispatchEvent(new Event("change")); var b = btn(); if (b) b.focus(); }
      else if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches('label[for="nav-drawer"][role=button]')) { e.preventDefault(); toggle.click(); }
    });
  }

  /* ---- Search shortcut "/" and capture "c": never while typing or inside a dialog ---- */
  doc.addEventListener("keydown", function (e) {
    if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || typing(e.target) || e.target.closest("dialog[open]")) return;
    if (e.key === "/") { var q = qsa('[data-ph-search], input[type=search]').filter(visible)[0]; if (q) { e.preventDefault(); q.focus(); } }
    else if (e.key === "c") { var c = qs("[data-ph-capture]"); if (c) { e.preventDefault(); c.click(); } }
  });

  /* ---- Init: saved theme, tablist roving tabindex ---- */
  var saved = null; try { saved = localStorage.getItem("jobwatch-pebble-preview-theme-v1"); } catch (e) {}
  if (saved && /^(auto|phrog-light|phrog-dark)$/.test(saved)) setTheme(saved);
  qsa('[role="tablist"]').forEach(function (l) { var s = qs('[role="tab"][aria-selected="true"]', l); if (s) qsa('[role="tab"]', l).forEach(function (t) { t.tabIndex = t === s ? 0 : -1; }); });

  window.PhrogUI = { setTheme: setTheme, toast: toast, openDialog: openDialog, closeDialog: closeDialog };
})();

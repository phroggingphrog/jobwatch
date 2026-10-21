/* Server pages inside the app frame: theme button (same choice as the app) and toasts. No inline scripts (CSP). */
(function () {
  "use strict";
  var THEMES = [["auto", "Auto"], ["phrog-light", "Light"], ["phrog-dark", "Dark"]];
  var theme = "auto";
  try { theme = localStorage.getItem("jw-theme") || "auto"; } catch (e) { }
  if (!THEMES.some(function (x) { return x[0] === theme; })) { theme = "auto"; }
  function apply() {
    var dark = matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", theme === "auto" ? (dark ? "phrog-dark" : "phrog-light") : theme);
    var n = document.getElementById("themeName");
    if (n) { n.textContent = "Theme: " + THEMES.find(function (x) { return x[0] === theme; })[1]; }
  }
  apply();
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", function () { if (theme === "auto") { apply(); } });
  document.addEventListener("click", function (ev) {
    if (!ev.target.closest("#themeBtn")) { return; }
    var i = THEMES.findIndex(function (x) { return x[0] === theme; });
    theme = THEMES[(i + 1) % THEMES.length][0];
    try { localStorage.setItem("jw-theme", theme); } catch (e) { }
    apply();
  });

  var toast = null, timer = null;
  window.jwToast = function (msg, isError) {
    toast = toast || document.getElementById("toast");
    if (!toast || !msg) { return; }
    toast.textContent = msg;
    toast.classList.toggle("is-error", !!isError);
    toast.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(function () { toast.hidden = true; }, isError ? 6000 : 2800);
  };
  document.addEventListener("htmx:afterSwap", function (ev) {
    var n = ev.target && ev.target.querySelector ? ev.target.querySelector("[data-toast]") : null;
    if (n) { window.jwToast(n.getAttribute("data-toast"), n.hasAttribute("data-error")); n.removeAttribute("data-toast"); }
  });
  document.addEventListener("htmx:responseError", function (ev) {
    var s = ev.detail && ev.detail.xhr ? ev.detail.xhr.status : "";
    window.jwToast("That did not work (" + s + ")", true);
  });
})();

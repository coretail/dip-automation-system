/* Theme toggle: class "dark" on <html>, persisted in localStorage. */
(function () {
  var KEY = "heka-theme";
  var root = document.documentElement;
  if (root.classList.contains("force-light")) return;

  function isDark() {
    return root.classList.contains("dark");
  }

  function syncIcon() {
    var icon = document.getElementById("theme-toggle-icon");
    var btn = document.getElementById("theme-toggle");
    if (!icon) return;
    if (isDark()) {
      icon.classList.remove("fa-moon");
      icon.classList.add("fa-sun");
      if (btn) {
        btn.title = "Mode terang";
        btn.setAttribute("aria-label", "Aktifkan mode terang");
      }
    } else {
      icon.classList.remove("fa-sun");
      icon.classList.add("fa-moon");
      if (btn) {
        btn.title = "Mode gelap";
        btn.setAttribute("aria-label", "Aktifkan mode gelap");
      }
    }
  }

  function apply(theme, persist) {
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    if (persist) {
      try { localStorage.setItem(KEY, theme); } catch (e) {}
    }
    syncIcon();
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.addEventListener("click", function () {
        apply(isDark() ? "light" : "dark", true);
      });
    }
    syncIcon();
  });

  window.addEventListener("beforeprint", function () {
    if (isDark()) {
      root.setAttribute("data-theme-before-print", "dark");
      root.classList.remove("dark");
    }
  });
  window.addEventListener("afterprint", function () {
    if (root.getAttribute("data-theme-before-print") === "dark") {
      root.classList.add("dark");
      root.removeAttribute("data-theme-before-print");
    }
  });
})();

/* Theme switcher: atribut data-theme pada <html>
   (light | terra | rose | dark), disimpan di localStorage.
   Token & mapping ada di app/static/theme.css.

   UX: tombol di navbar membuka menu horizontal berisi 4 tema (bukan lagi
   siklus sekali klik). Menu ditutup dengan Escape, klik di luar, atau Tab. */
(function () {
  var KEY = "heka-theme";
  var THEMES = ["light", "terra", "rose", "dark"];
  var root = document.documentElement;
  if (root.classList.contains("force-light")) return;

  function isValid(t) {
    return THEMES.indexOf(t) !== -1;
  }

  function current() {
    var t = root.getAttribute("data-theme");
    if (isValid(t)) return t;
    // Tanpa atribut (mis. halaman cached): pakai localStorage, lalu sistem.
    try {
      var saved = localStorage.getItem(KEY);
      if (isValid(saved)) return saved;
    } catch (e) {}
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

// Ikon pada tombol pemicu menunjukkan tema yang AKTIF.
// `icon`  = nama ikon Font Awesome (tanpa prefix)
// `style` = prefix gaya; default "fa-solid" (mis. "fa-regular" untuk outline)
var META = {
    light: { icon: "fa-sun", name: "Terah" },
    terra: { icon: "fa-fire", name: "Terra" },
    rose: { icon: "fa-heart", style: "fa-regular", name: "Rose" },
    dark: { icon: "fa-moon", name: "Gelap" }
  };

  var els = {};

  function syncUI() {
    var now = current();
    var meta = META[now];

    if (els.icon) {
      // Buang SEMUA kelas fa-* yang menempel, bukan daftar ikon per tema.
      // Kalau daftar itu ditulis manual, menambah tema baru bisa lewat dan
      // ikon lama tetap ikut terender.
      var faClasses = [];
      Array.prototype.forEach.call(els.icon.classList, function (c) {
        if (/^fa-/.test(c)) faClasses.push(c);
      });
      faClasses.forEach(function (c) { els.icon.classList.remove(c); });
      els.icon.classList.add(meta.style || "fa-solid", meta.icon);
    }
    if (els.trigger) {
      els.trigger.title = "Tema " + meta.name + " aktif. Klik untuk mengubah tema.";
      els.trigger.setAttribute("aria-label", "Pilih tema. Saat ini " + meta.name);
    }
    // Tandai opsi mana yang aktif (aria-checked), bukan hanya gaya.
    Array.prototype.forEach.call(els.opts, function (btn) {
      var on = btn.getAttribute("data-theme-opt") === now;
      btn.setAttribute("aria-checked", on ? "true" : "false");
    });
  }

  function apply(theme, persist) {
    if (!isValid(theme)) theme = "light";
    root.setAttribute("data-theme", theme);
    if (persist) {
      try {
        localStorage.setItem(KEY, theme);
      } catch (e) {}
    }
    syncUI();
  }

  function isOpen() {
    return !!(els.menu && els.menu.classList.contains("is-open"));
  }

  function openMenu() {
    if (!els.menu || !els.trigger || isOpen()) return;
    els.menu.classList.add("is-open");
    els.trigger.setAttribute("aria-expanded", "true");
  }

  function closeMenu(refocus) {
    if (!els.menu || !els.trigger || !isOpen()) return;
    els.menu.classList.remove("is-open");
    els.trigger.setAttribute("aria-expanded", "false");
    if (refocus) els.trigger.focus();
  }

  function focusOpt(index) {
    if (!els.opts.length) return;
    var i = (index + els.opts.length) % els.opts.length;
    els.opts[i].focus();
  }

  document.addEventListener("DOMContentLoaded", function () {
    els.trigger = document.getElementById("theme-toggle");
    els.menu = document.getElementById("themeMenu");
    if (!els.trigger || !els.menu) return;
    els.icon = document.getElementById("theme-toggle-icon");
    els.opts = Array.prototype.slice.call(
      els.menu.querySelectorAll("[data-theme-opt]")
    );

    // Skrip pra-render di base.html sudah menulis data-theme. Terapkan ulang
    // supaya atribut selalu ada walau skrip itu gagal (mis. localStorage diblokir).
    apply(current(), false);

    els.trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      if (isOpen()) closeMenu(false);
      else openMenu();
    });

    // delegated click pada menu: aman walau markup berubah
    els.menu.addEventListener("click", function (e) {
      var btn = e.target.closest ? e.target.closest("[data-theme-opt]") : null;
      if (!btn) return;
      e.stopPropagation();
      apply(btn.getAttribute("data-theme-opt"), true);
      closeMenu(true);
    });

    // Klik di luar → tutup
    document.addEventListener("click", function (e) {
      if (!isOpen()) return;
      if (!els.menu.contains(e.target) && !els.trigger.contains(e.target)) {
        closeMenu(false);
      }
    });

    document.addEventListener("keydown", function (e) {
      if (!isOpen()) return;
      var active = document.activeElement;
      var i = els.opts.indexOf(active);
      if (e.key === "Escape") {
        e.preventDefault();
        closeMenu(true);
      } else if (e.key === "ArrowDown" || e.key === "ArrowRight") {
        e.preventDefault();
        focusOpt(i + 1);
      } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
        e.preventDefault();
        focusOpt(i - 1);
      } else if (e.key === "Home") {
        e.preventDefault();
        focusOpt(0);
      } else if (e.key === "End") {
        e.preventDefault();
        focusOpt(els.opts.length - 1);
      } else if (e.key === "Tab") {
        // Biarkan Tab bergerak seperti biasa, menu menutup saat fokus keluar.
        closeMenu(false);
      }
    });

    // Menu mengikuti tema aktif walau berubah dari tab lain.
    window.addEventListener("storage", function (e) {
      if (e.key === KEY) syncUI();
    });
  });

  // Saat print, paksa tema terang supaya PDF tidak gelap.
  window.addEventListener("beforeprint", function () {
    if (current() !== "light") {
      root.setAttribute("data-theme-before-print", current());
      root.setAttribute("data-theme", "light");
    }
  });
  window.addEventListener("afterprint", function () {
    var before = root.getAttribute("data-theme-before-print");
    if (before) {
      root.setAttribute("data-theme", before);
      root.removeAttribute("data-theme-before-print");
    }
  });
})();
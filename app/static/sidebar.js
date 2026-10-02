/* Perilaku sidebar navigasi (collapsible + off-canvas drawer) dan dropdown user.
   State hanya boolean UI di localStorage, tidak ada data sensitif. */
(function () {
  var STORAGE_COLLAPSED = 'sidebarCollapsed';
  var STORAGE_ADMIN_OPEN = 'sidebarAdminOpen';
  var MOBILE_QUERY = '(max-width: 767px)';

  function readStore(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function writeStore(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {}
  }

  function isMobile() {
    return window.matchMedia(MOBILE_QUERY).matches;
  }

  document.addEventListener('DOMContentLoaded', function () {
    var root = document.documentElement;
    var sidebar = document.getElementById('app-sidebar');
    var toggle = document.getElementById('sidebar-toggle');
    var overlay = document.getElementById('sidebar-overlay');
    var closeBtn = document.getElementById('sidebar-drawer-close');
    var adminToggle = document.getElementById('sidebar-admin-toggle');
    var adminSubmenu = document.getElementById('sidebar-admin-submenu');
    var adminCaret = document.getElementById('sidebar-admin-caret');
    var userBtn = document.getElementById('user-menu-btn');
    var userDropdown = document.getElementById('user-menu-dropdown');

    /* ---------- Collapsed / expanded ---------- */
    function applyCollapsed(collapsed) {
      root.classList.toggle('sidebar-collapsed', collapsed);
      hideTooltip(null);
      if (toggle) {
        toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        toggle.setAttribute('aria-label', collapsed ? 'Perluas sidebar navigasi' : 'Ciutkan sidebar navigasi');
        toggle.title = collapsed ? 'Perluas sidebar navigasi' : 'Ciutkan sidebar navigasi';
      }
    }

    if (toggle) {
      toggle.addEventListener('click', function () {
        if (isMobile()) {
          setDrawerOpen(!root.classList.contains('sidebar-drawer-open'));
          return;
        }
        var collapsed = !root.classList.contains('sidebar-collapsed');
        applyCollapsed(collapsed);
        writeStore(STORAGE_COLLAPSED, collapsed ? 'true' : 'false');
      });
    }

    applyCollapsed(root.classList.contains('sidebar-collapsed'));
    // Di mobile sidebar selalu mulai tertutup (off-canvas), abaikan state collapsed.
    if (isMobile()) setDrawerOpen(false);

    /* ---------- Off-canvas drawer (mobile) ---------- */
    function setDrawerOpen(open) {
      root.classList.toggle('sidebar-drawer-open', open);
      if (!open) hideTooltip(null);
      if (sidebar) {
        sidebar.setAttribute('aria-hidden', open ? 'false' : (isMobile() ? 'true' : 'false'));
      }
      if (toggle) {
        // Di mobile aria-expanded menggambarkan drawer; di desktop menggambarkan sidebar.
        var expanded = isMobile() ? open : !root.classList.contains('sidebar-collapsed');
        toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      }
    }

    if (overlay) overlay.addEventListener('click', function () { setDrawerOpen(false); });
    if (closeBtn) closeBtn.addEventListener('click', function () { setDrawerOpen(false); });

    if (sidebar) {
      sidebar.addEventListener('click', function (event) {
        // Navigasi dari drawer harus menutup drawer supaya halaman tidak tertutup.
        var link = event.target.closest ? event.target.closest('a[href]') : null;
        if (link && isMobile()) setDrawerOpen(false);
      });
    }

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') return;
      if (root.classList.contains('sidebar-drawer-open')) {
        setDrawerOpen(false);
        if (toggle) toggle.focus();
        return;
      }
      if (userDropdown && !userDropdown.classList.contains('hidden')) {
        closeUserMenu();
        if (userBtn) userBtn.focus();
      }
    });

    function syncViewport() {
      if (!isMobile()) setDrawerOpen(false);
    }
    window.addEventListener('resize', debounce(syncViewport, 150));

    /* ---------- Submenu Administration ---------- */
    if (adminToggle && adminSubmenu) {
      var childActive = adminSubmenu.querySelector('.sidebar-item-active');

      function setAdminOpen(open, persist) {
        adminSubmenu.classList.toggle('sidebar-submenu-hidden', !open);
        adminToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (adminCaret) adminCaret.classList.toggle('sidebar-section-caret-open', open);
        if (persist) writeStore(STORAGE_ADMIN_OPEN, open ? 'true' : 'false');
      }

      var storedAdmin = readStore(STORAGE_ADMIN_OPEN);
      var adminOpen = childActive ? true : (storedAdmin !== 'false');
      setAdminOpen(adminOpen, false);

      adminToggle.addEventListener('click', function () {
        setAdminOpen(adminSubmenu.classList.contains('sidebar-submenu-hidden'), true);
      });
    }

    /* ---------- Dropdown user ---------- */
    function closeUserMenu() {
      if (!userDropdown) return;
      userDropdown.classList.add('hidden');
      if (userBtn) userBtn.setAttribute('aria-expanded', 'false');
    }

    if (userBtn && userDropdown) {
      userBtn.addEventListener('click', function (event) {
        event.preventDefault();
        event.stopPropagation();
        var open = userDropdown.classList.toggle('hidden') === false;
        userBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      });

      document.addEventListener('click', function (event) {
        if (userDropdown.classList.contains('hidden')) return;
        if (!userDropdown.contains(event.target) && !userBtn.contains(event.target)) closeUserMenu();
      });
    }

    /* ---------- Tooltip untuk mode icon-only ---------- */
    var tooltip = document.getElementById('sidebar-tooltip');

    function tooltipEnabled() {
      return root.classList.contains('sidebar-collapsed') && !isMobile();
    }

    function showTooltip(item) {
      if (!tooltip || !tooltipEnabled()) return;
      var label = item.getAttribute('data-label');
      if (!label) return;
      tooltip.textContent = label; // teks statis dari data-label, bukan HTML
      tooltip.hidden = false;
      var rect = item.getBoundingClientRect();
      tooltip.style.left = Math.round(rect.right + 8) + 'px';
      tooltip.style.top = Math.round(rect.top + rect.height / 2 - 12) + 'px';
      item.setAttribute('aria-describedby', 'sidebar-tooltip');
    }

    function hideTooltip(item) {
      if (!tooltip) return;
      tooltip.hidden = true;
      if (item) item.removeAttribute('aria-describedby');
    }

    if (tooltip) {
      Array.prototype.forEach.call(document.querySelectorAll('.sidebar-item[data-label]'), function (item) {
        item.addEventListener('mouseenter', function () { showTooltip(item); });
        item.addEventListener('mouseleave', function () { hideTooltip(item); });
        item.addEventListener('focus', function () { showTooltip(item); });
        item.addEventListener('blur', function () { hideTooltip(item); });
      });
    }

    /* ---------- Logout ---------- */
    document.querySelectorAll('[data-logout]').forEach(function (link) {
      link.addEventListener('click', function (event) {
        if (!window.confirm('Yakin mau keluar dari aplikasi?')) event.preventDefault();
      });
    });
  });

  function debounce(fn, wait) {
    var timer = null;
    return function () {
      var args = arguments;
      if (timer) clearTimeout(timer);
      timer = setTimeout(function () { fn.apply(null, args); }, wait);
    };
  }
})();

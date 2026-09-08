/* Presence heartbeat:
   - Online: browser terlihat dan user masih berinteraksi.
   - Idle: heartbeat tetap berjalan, tetapi tidak ada interaksi selama 5 menit.
   - Offline: tab hidden/ditutup atau koneksi putus sehingga heartbeat berhenti >90 dtk. */
(function () {
  var HEARTBEAT_MS = 25000;
  var PRESENCE_IDLE_MS = 5 * 60 * 1000;
  var endpoint = "/api/presence/heartbeat";
  var lastActivityAt = Date.now();
  var idleTimer = null;
  var lastMouseMoveAt = 0;

  function isActive() {
    return Date.now() - lastActivityAt < PRESENCE_IDLE_MS;
  }

  function ping(active) {
    var payload = JSON.stringify({ online: true, active: active !== false });
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      credentials: "same-origin",
      keepalive: true
    }).catch(function () {});
  }

  function scheduleIdleHeartbeat() {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(function () {
      if (document.visibilityState === "visible" && !isActive()) {
        ping(false);
      }
    }, PRESENCE_IDLE_MS + 50);
  }

  function recordActivity() {
    var wasIdle = !isActive();
    lastActivityAt = Date.now();
    scheduleIdleHeartbeat();
    // Saat user kembali dari Idle, beri tahu server tanpa menunggu heartbeat berikutnya.
    if (wasIdle && document.visibilityState === "visible") ping(true);
  }

  function recordMouseMove() {
    var now = Date.now();
    if (now - lastMouseMoveAt < 1000) return;
    lastMouseMoveAt = now;
    recordActivity();
  }

  ["mousedown", "keydown", "scroll", "touchstart"].forEach(function (eventName) {
    document.addEventListener(eventName, recordActivity, { passive: true });
  });
  document.addEventListener("mousemove", recordMouseMove, { passive: true });

  ping(true);
  scheduleIdleHeartbeat();
  setInterval(function () {
    // Background tabs sering ditunda browser; pertahankan grace period Offline yang ada.
    if (document.visibilityState === "hidden") return;
    ping(isActive());
  }, HEARTBEAT_MS);

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      // Kembali ke aplikasi adalah sinyal aktivitas user.
      lastActivityAt = Date.now();
      scheduleIdleHeartbeat();
      ping(true);
    } else if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
  });
})();

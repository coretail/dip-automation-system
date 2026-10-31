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
  var heartbeatInterval = null; // Stored reference
  var isRedirecting = false; // Guard flag

  function isActive() {
    return Date.now() - lastActivityAt < PRESENCE_IDLE_MS;
  }

  function stopHeartbeat() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    heartbeatInterval = null;
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = null;
  }
  window.stopPresenceHeartbeat = stopHeartbeat;

  // FE-04: startHeartbeat() idempoten (bersihkan interval lama dulu) supaya bisa
  // dipanggil ulang saat halaman kembali dari bfcache tanpa membuat interval ganda.
  function startHeartbeat() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    heartbeatInterval = setInterval(function () {
      // Background tabs sering ditunda browser; pertahankan grace period Offline yang ada.
      if (document.visibilityState === "hidden") return;
      ping(isActive());
    }, HEARTBEAT_MS);
  }

  function ping(active) {
    if (isRedirecting) return;
    var payload = JSON.stringify({ online: true, active: active !== false });
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      credentials: "same-origin",
      keepalive: true
    }).then(function (response) {
      if (response.redirected && response.url.includes("/login")) {
        isRedirecting = true;
        stopHeartbeat();
        window.location.href = response.url;
        return;
      }
      if (response.status === 401) {
        isRedirecting = true;
        stopHeartbeat();
        if (typeof window.handleSessionExpired === "function") window.handleSessionExpired();
      }
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
  startHeartbeat();

  window.addEventListener("beforeunload", stopHeartbeat);
  window.addEventListener("pagehide", stopHeartbeat);

  // FE-04: kembali dari bfcache (tombol maju/mundur) — pagehide sudah menghentikan
  // heartbeat tetapi skrip tidak dijalankan ulang; aktifkan lagi agar pengguna
  // tidak salah ditandai Offline setelah grace period ~90 dtk.
  window.addEventListener("pageshow", function (event) {
    if (!event.persisted || isRedirecting) return;
    if (document.visibilityState !== "visible") return;
    lastActivityAt = Date.now();
    scheduleIdleHeartbeat();
    startHeartbeat();
    ping(true);
  });

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

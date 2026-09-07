/* Heartbeat presence: tandai user Online selama tab aplikasi masih terbuka.
   Offline otomatis ~90 detik setelah tab ditutup, atau langsung saat Logout. */
(function () {
  var HEARTBEAT_MS = 25000;
  var endpoint = "/api/presence/heartbeat";

  function ping(online) {
    var payload = JSON.stringify({ online: online !== false });
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      credentials: "same-origin",
      keepalive: true
    }).catch(function () {});
  }

  ping(true);
  setInterval(function () {
    if (document.visibilityState === "hidden") return;
    ping(true);
  }, HEARTBEAT_MS);

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") ping(true);
  });
})();

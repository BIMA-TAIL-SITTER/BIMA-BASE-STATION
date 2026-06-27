/**
 * system.js — System events WebSocket client
 * ────────────────────────────────────────────
 * Connects to /ws/system, drives the connection status indicator,
 * header info, and provides the global GS_log() helper.
 *
 * MUST be loaded before telemetry.js and video.js (it defines GS_log).
 */

(function () {
  "use strict";

  // ─── DOM refs ────────────────────────────────────────────────────────────
  const udpAddrEl   = document.getElementById("udp-addr");
  const udpPortEl   = document.getElementById("udp-port");
  const yoloStatEl  = document.getElementById("yolo-toggle");

  // ─── Log (console-only in this layout, no log feed panel) ───────────────
  let logEntries  = [];
  const MAX_LOGS  = 200;

  /**
   * Global log function.
   * @param {string} level   "info" | "event" | "warning" | "error"
   * @param {string} category  "system" | "video" | "telemetry" | …
   * @param {string} message
   */
  window.GS_log = function (level, category, message) {
    const now = new Date();
    const ts  = `${String(now.getHours()).padStart(2,"0")}:${
      String(now.getMinutes()).padStart(2,"0")}:${
      String(now.getSeconds()).padStart(2,"0")}`;

    const entry = { ts, level, category, message };
    logEntries.push(entry);
    if (logEntries.length > MAX_LOGS) logEntries.shift();
    console.log(`[${ts}] [${level.toUpperCase()}] ${category}: ${message}`);
  };

  // ─── System WebSocket ─────────────────────────────────────────────────────
  const WS_URL = `${window.GS_CONFIG.wsProto}://${window.GS_CONFIG.wsHost}/ws/system`;
  let ws       = null;
  let backoff  = 1000;

  function connect() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log("[system] WebSocket connected");
      backoff = 1000;
      window.GS_log("event", "system", "Ground Station WebSocket connected");
    };

    ws.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data);
        const d     = new Date(event.ts * 1000);
        const ts    = `${String(d.getHours()).padStart(2,"0")}:${
          String(d.getMinutes()).padStart(2,"0")}:${
          String(d.getSeconds()).padStart(2,"0")}`;
        logEntries.push({ ts, level: event.level, category: event.category, message: event.message });
        if (logEntries.length > MAX_LOGS) logEntries.shift();
      } catch (_) {}
    };

    ws.onclose = () => {
      window.GS_log("warning", "system", `System WS closed — reconnecting in ${backoff / 1000}s`);
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 16000);
    };

    ws.onerror = () => {
      console.warn("[system] WebSocket error");
    };
  }

  connect();

  // ─── Poll /health every 10 s ─────────────────────────────────────────────
  async function pollHealth() {
    try {
      const r    = await fetch("/health");
      const data = await r.json();

      // Update header info from health response
      if (data.video && data.video.sender && udpAddrEl) {
        const sender = data.video.sender;
        if (sender && sender !== "---") {
          const parts = sender.split(":");
          udpAddrEl.textContent = parts[0] || "<IP ADDRESS>";
          if (udpPortEl) udpPortEl.textContent = parts[1] || "<PORT>";
        }
      }
      if (yoloStatEl) {
        const yoloEnabled = data.yolo && data.yolo.enabled;
        yoloStatEl.checked = yoloEnabled;
      }
    } catch (_) {}
  }
  
  if (yoloStatEl) {
    yoloStatEl.addEventListener("change", async (e) => {
      // Temporarily disable the switch while the request is processing
      yoloStatEl.disabled = true;
      try {
        const r = await fetch("/api/video/yolo/toggle", { method: "POST" });
        const data = await r.json();
        const yoloEnabled = data.enabled;
        yoloStatEl.checked = yoloEnabled;
        
        
        
        if (yoloEnabled) {
          window.GS_log("info", "system", "YOLO activated");
        } else {
          window.GS_log("info", "system", "YOLO deactivated");
        }
      } catch (err) {
        window.GS_log("error", "system", "Failed to toggle YOLO");
        // Revert UI state on failure
        yoloStatEl.checked = !yoloStatEl.checked;
      } finally {
        yoloStatEl.disabled = false;
      }
    });
  }
  setInterval(pollHealth, 10000);
  pollHealth();

  // ─── Boot log ─────────────────────────────────────────────────────────────
  window.GS_log("info", "system", "Ground Station interface initialised");

})();

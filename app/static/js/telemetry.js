/**
 * telemetry.js — Telemetry WebSocket client
 * ──────────────────────────────────────────
 * Receives JSON telemetry packets at 5 Hz and updates the center
 * telemetry panels with Lat/Lon/Alt/WP/Spd values.
 */

(function () {
  "use strict";

  const WS_URL = `${window.GS_CONFIG.wsProto}://${window.GS_CONFIG.wsHost}/ws/telemetry`;
  let ws       = null;
  let backoff  = 1000;

  // ─── DOM refs ─────────────────────────────────────────────────────────────
  const el = (id) => document.getElementById(id);

  const $ = {
    // Panel 1 (upper)
    gpsLat:     el("gps-lat"),
    gpsLon:     el("gps-lon"),
    navAlt:     el("nav-alt"),
    wpCurrent:  el("wp-current"),
    navGspd:    el("nav-gspd"),
    // Panel 2 (lower)
    gpsLat2:    el("gps-lat-2"),
    gpsLon2:    el("gps-lon-2"),
    navAlt2:    el("nav-alt-2"),
    wpCurrent2: el("wp-current-2"),
    navGspd2:   el("nav-gspd-2"),
  };

  // ─── Update helper ──────────────────────────────────────────────────────
  function setVal(el, text) {
    if (el && el.value !== text) el.value = text;
  }

  // ─── Telemetry update ─────────────────────────────────────────────────────
  function applyTelemetry(t) {
    // ── Panel 1 (primary UAV) ──────────────────────────────────────────
    setVal($.gpsLat,    (t.lat !== undefined) ? t.lat.toFixed(9) : "--.-------");
    setVal($.gpsLon,    (t.lon !== undefined) ? t.lon.toFixed(9) : "---.-------");
    setVal($.navAlt,    (t.altitude_m ?? 0).toFixed(1));
    setVal($.wpCurrent, String(t.current_waypoint ?? 0));
    setVal($.navGspd,   (t.ground_speed_ms ?? 0).toFixed(0) + " m/s");

    // ── Panel 2 (mirror for now — will use second UAV data when available)
    setVal($.gpsLat2,    (t.lat !== undefined) ? t.lat.toFixed(9) : "--.-------");
    setVal($.gpsLon2,    (t.lon !== undefined) ? t.lon.toFixed(9) : "---.-------");
    setVal($.navAlt2,    (t.altitude_m ?? 0).toFixed(1));
    setVal($.wpCurrent2, String(t.current_waypoint ?? 0));
    setVal($.navGspd2,   (t.ground_speed_ms ?? 0).toFixed(0) + " m/s");
  }

  // ─── WebSocket ───────────────────────────────────────────────────────────
  function connect() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log("[telemetry] WebSocket connected");
      backoff = 1000;
      window.GS_log("event", "telemetry", "Telemetry WebSocket connected");
    };

    ws.onmessage = (ev) => {
      try {
        applyTelemetry(JSON.parse(ev.data));
      } catch (e) {
        console.warn("[telemetry] JSON parse error", e);
      }
    };

    ws.onclose = () => {
      window.GS_log("warning", "telemetry", `Telemetry disconnected — retry in ${backoff / 1000}s`);
      setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 16000);
    };

    ws.onerror = (e) => console.warn("[telemetry] error", e);
  }

  connect();

})();

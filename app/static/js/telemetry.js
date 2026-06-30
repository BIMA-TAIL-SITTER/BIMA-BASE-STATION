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
    gpsSats:    el("gps-sats"),
    gpsLat:     el("gps-lat"),
    gpsLon:     el("gps-lon"),
    wpCurrent:  el("wp-current"),
    navGspd:    el("nav-gspd"),
    battVolt:   el("batt-volt"),
    src1:       el("mavlink-source-1"),
    port1:      el("mavlink-port-1"),
    btn1:       el("mavlink-btn-1"),
    status1:    el("mavlink-status-1"),
    attRoll1:   el("attitude-roll-1"),
    attPitch1:  el("attitude-pitch-1"),
    altTapeTicks1: el("alt-tape-ticks-1"),
    altTapeVal1:   el("alt-tape-val-1"),
    hudHead1:   el("hud-head-1"),
    headCompass1: el("heading-compass-1"),
    // Panel 2 (lower)
    gpsSats2:   el("gps-sats-2"),
    gpsLat2:    el("gps-lat-2"),
    gpsLon2:    el("gps-lon-2"),
    wpCurrent2: el("wp-current-2"),
    navGspd2:   el("nav-gspd-2"),
    battVolt2:  el("batt-volt-2"),
    src2:       el("mavlink-source-2"),
    port2:      el("mavlink-port-2"),
    btn2:       el("mavlink-btn-2"),
    status2:    el("mavlink-status-2"),
    attRoll2:   el("attitude-roll-2"),
    attPitch2:  el("attitude-pitch-2"),
    altTapeTicks2: el("alt-tape-ticks-2"),
    altTapeVal2:   el("alt-tape-val-2"),
    hudHead2:   el("hud-head-2"),
    headCompass2: el("heading-compass-2"),
  };

  // Track latest update times to detect disconnected state
  const lastUpdate = { 1: 0, 2: 0 };

  // ─── Update helper ──────────────────────────────────────────────────────
  function setVal(el, text) {
    if (el && el.value !== text) el.value = text;
  }

  function setMavlinkStatus(el, state, armed) {
    if (!el) return;
    if (state === "DISCONNECTED") {
      el.textContent = "No Mavlink Detected";
      el.style.backgroundColor = "var(--panel)";
      el.style.color = "var(--muted)";
      el.style.border = "1px solid var(--border)";
    } else if (state === "CONNECTED") {
      el.style.border = "none";
      if (armed) {
        el.textContent = "ARMED";
        el.style.backgroundColor = "var(--ok)";
        el.style.color = "var(--status-text)";
      } else {
        el.textContent = "DISARMED";
        el.style.backgroundColor = "var(--danger)";
        el.style.color = "var(--status-text)";
      }
    }
  }

  // ─── Telemetry update ─────────────────────────────────────────────────────
  function applyTelemetry(t) {
    const slot = t.slot || 1;
    
    // Ignore incoming data if the user has selected "No Source" for this slot
    if (slot === 2 && $.src2.value === "none") return;
    if (slot === 1 && $.src1.value === "none") return;
    
    lastUpdate[slot] = Date.now();
    
    if (slot === 2) {
      setVal($.gpsSats2,   (t.satellites_visible !== undefined) ? String(t.satellites_visible) : "0");
      setVal($.gpsLat2,    (t.lat !== undefined && t.lat !== 0) ? t.lat.toFixed(9) : "--.-------");
      setVal($.gpsLon2,    (t.lon !== undefined && t.lon !== 0) ? t.lon.toFixed(9) : "---.-------");
      setVal($.wpCurrent2, (t.current_waypoint !== undefined) ? String(t.current_waypoint) : "0");
      setVal($.navGspd2,   (t.ground_speed_ms !== undefined) ? t.ground_speed_ms.toFixed(0) + " m/s" : "0 m/s");
      setVal($.battVolt2,  (t.battery_voltage !== undefined) ? t.battery_voltage.toFixed(1) + " V" : "0.0 V");
      if (t.armed !== undefined) setMavlinkStatus($.status2, "CONNECTED", t.armed);
      
      // Attitude Gauge
      if ($.attRoll2 && t.roll_deg !== undefined) $.attRoll2.style.transform = `translate(-50%, -50%) rotate(${-t.roll_deg}deg)`;
      if ($.attPitch2 && t.pitch_deg !== undefined) $.attPitch2.style.transform = `translateY(${t.pitch_deg}px)`;
      // Altitude Tape & Heading HUD
      if ($.altTapeTicks2 && t.altitude_m !== undefined) {
        $.altTapeTicks2.style.backgroundPositionY = `calc(50% + ${t.altitude_m * 4}px)`;
        $.altTapeVal2.textContent = t.altitude_m.toFixed(0);
      }
      if (t.heading_deg !== undefined) {
        if ($.hudHead2) $.hudHead2.textContent = String(Math.round(t.heading_deg)).padStart(3, '0') + "\xB0";
        if ($.headCompass2) $.headCompass2.style.transform = `rotate(${-t.heading_deg}deg)`;
      }

    } else {
      setVal($.gpsSats,    (t.satellites_visible !== undefined) ? String(t.satellites_visible) : "0");
      setVal($.gpsLat,     (t.lat !== undefined && t.lat !== 0) ? t.lat.toFixed(9) : "--.-------");
      setVal($.gpsLon,     (t.lon !== undefined && t.lon !== 0) ? t.lon.toFixed(9) : "---.-------");
      setVal($.wpCurrent,  (t.current_waypoint !== undefined) ? String(t.current_waypoint) : "0");
      setVal($.navGspd,    (t.ground_speed_ms !== undefined) ? t.ground_speed_ms.toFixed(0) + " m/s" : "0 m/s");
      setVal($.battVolt,   (t.battery_voltage !== undefined) ? t.battery_voltage.toFixed(1) + " V" : "0.0 V");
      if (t.armed !== undefined) setMavlinkStatus($.status1, "CONNECTED", t.armed);

      // Attitude Gauge
      if ($.attRoll1 && t.roll_deg !== undefined) $.attRoll1.style.transform = `translate(-50%, -50%) rotate(${-t.roll_deg}deg)`;
      if ($.attPitch1 && t.pitch_deg !== undefined) $.attPitch1.style.transform = `translateY(${t.pitch_deg}px)`;
      // Altitude Tape & Heading HUD
      if ($.altTapeTicks1 && t.altitude_m !== undefined) {
        $.altTapeTicks1.style.backgroundPositionY = `calc(50% + ${t.altitude_m * 4}px)`;
        $.altTapeVal1.textContent = t.altitude_m.toFixed(0);
      }
      if (t.heading_deg !== undefined) {
        if ($.hudHead1) $.hudHead1.textContent = String(Math.round(t.heading_deg)).padStart(3, '0') + "\xB0";
        if ($.headCompass1) $.headCompass1.style.transform = `rotate(${-t.heading_deg}deg)`;
      }
    }
  }

  // ─── Timeout check ────────────────────────────────────────────────────────
  setInterval(() => {
    const now = Date.now();
    if ($.src1.value !== "none" && now - lastUpdate[1] > 3000) {
      setMavlinkStatus($.status1, "DISCONNECTED");
    }
    if ($.src2.value !== "none" && now - lastUpdate[2] > 3000) {
      setMavlinkStatus($.status2, "DISCONNECTED");
    }
  }, 1000);

  // ─── Source Selector Logic ────────────────────────────────────────────────
  async function loadSources() {
    try {
      const res = await fetch("/api/telemetry/sources");
      const data = await res.json();
      const hosts = data.hosts || [];
      const defaultPort = data.default_port || 5761;
      
      [$.src1, $.src2].forEach(select => {
        select.innerHTML = '<option value="none">No Source</option>';
        hosts.forEach(ip => {
          const opt = new Option(ip, ip);
          select.appendChild(opt);
        });
      });
      $.port1.value = defaultPort;
      $.port2.value = defaultPort;
    } catch (e) {
      console.error("Failed to load telemetry sources", e);
    }
  }

  async function handleSourceChange(slot, srcEl, portEl, btnEl) {
    const ip = srcEl.value;
    
    if (ip === "none") {
      portEl.style.display = "none";
      btnEl.style.display = "none";
      await fetch("/api/telemetry/disconnect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot })
      });
      console.log(`[telemetry] Disconnected slot ${slot}`);
      // Clear panel
      const dummy = { slot };
      applyTelemetry(dummy);
      // Update status box
      if (slot === 1) {
        setMavlinkStatus($.status1, "DISCONNECTED");
      } else {
        setMavlinkStatus($.status2, "DISCONNECTED");
      }
    } else {
      portEl.style.display = "inline-block";
      btnEl.style.display = "inline-block";
    }
  }

  async function handleConnect(slot, srcEl, portEl) {
    const ip = srcEl.value;
    const port = parseInt(portEl.value, 10);
    
    if (ip === "none") return;
    
    // Clear panel immediately while connecting
    const dummy = { slot };
    applyTelemetry(dummy);
    
    await fetch("/api/telemetry/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot, ip, port })
    });
    console.log(`[telemetry] Connected slot ${slot} to ${ip}:${port}`);
  }

  $.src1.addEventListener("change", () => handleSourceChange(1, $.src1, $.port1, $.btn1));
  $.btn1.addEventListener("click", () => handleConnect(1, $.src1, $.port1));
  
  $.src2.addEventListener("change", () => handleSourceChange(2, $.src2, $.port2, $.btn2));
  $.btn2.addEventListener("click", () => handleConnect(2, $.src2, $.port2));

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

  // ─── Theme Toggling ──────────────────────────────────────────────────────
  const themes = {
    dark: {
      "--accent": "#D5FF40",
      "--bg": "#11110F",
      "--panel": "#0A0A08",
      "--border": "#2A2A22",
      "--muted": "#555540",
      "--text-main": "#ffffff",
      "--ok": "#40FF80",
      "--danger": "#FF4040",
      "--status-text": "#000000"
    },
    light: {
      "--accent": "#f7a0b8", // Pink accent
      "--bg": "#faf5ec",     // Cream background
      "--panel": "#fae9d7",  // Peach panel
      "--border": "#fbb6c4", // Light pink border
      "--muted": "#f7a0b8",  // Darkest pink for muted text
      "--text-main": "#f7a0b8", // Darkest pink for all main text
      "--ok": "#f7a0b8",     // Pink for ARMED
      "--danger": "#a2d2ff", // Light Blue for DISARMED
      "--status-text": "#5c3a41" // Dark text for contrast on colored badges
    }
  };

  const themeToggle = document.getElementById("theme-toggle");
  if (themeToggle) {
    themeToggle.addEventListener("change", (e) => {
      const mode = e.target.checked ? "light" : "dark";
      const palette = themes[mode];
      for (const [key, value] of Object.entries(palette)) {
        document.documentElement.style.setProperty(key, value);
      }
      window.GS_log("event", "ui", `Theme switched to ${mode}`);
    });
  }

  loadSources();
  connect();

})();

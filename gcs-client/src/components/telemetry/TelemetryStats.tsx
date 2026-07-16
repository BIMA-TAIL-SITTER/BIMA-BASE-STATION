"use client";

import { memo } from "react";
import type { TelemetryData, MavlinkStatus } from "@/types/telemetry";

interface TelemetryStatsProps {
  telemetry: TelemetryData | null;
  mavlinkStatus: MavlinkStatus;
  panelId: 1 | 2;
  /** UDP target detection data */
  udpTarget?: {
    detected: boolean;
    lat?: string;
    lon?: string;
    dist?: string;
    gsd?: string;
  };
}

function TelemetryStatsInner({ telemetry, udpTarget, panelId }: TelemetryStatsProps) {
  const t = telemetry;

  return (
    <div className="telem-stats">
      {/* Core telemetry */}
      <TelemRow label="HDOP" value={t?.hdop !== undefined ? t.hdop.toFixed(2) : "0.00"} />
      <TelemRow label="LAT" value={t?.lat && t.lat !== 0 ? t.lat.toFixed(9) : "--.-------"} />
      <TelemRow label="LON" value={t?.lon && t.lon !== 0 ? t.lon.toFixed(9) : "---.-------"} />
      <TelemRow label="WP" value={t?.current_waypoint !== undefined ? String(t.current_waypoint) : "0"} />
      <TelemRow label="SPD" value={t?.ground_speed_ms !== undefined ? `${t.ground_speed_ms.toFixed(0)} m/s` : "0 m/s"} />

      {/* UDP Target Section matching vanilla index.html */}
      <div style={{ marginTop: 15, marginBottom: 10 }}>
        <select
          className="cam-select"
          style={{ width: "100%", marginBottom: 8, textAlign: "center", display: "block" }}
          defaultValue={panelId === 1 ? "1001" : "1002"}
        >
          <option value={panelId === 1 ? "1001" : "1002"}>{panelId === 1 ? "1001" : "1002"}</option>
        </select>
        <div
          className="udp-detect-status"
          style={{
            backgroundColor: udpTarget?.detected ? "#f44336" : "var(--border)",
            color: "var(--text-main)",
            padding: "6px 0",
            borderRadius: "4px",
            fontWeight: "bold",
            fontSize: "14px",
            textAlign: "center",
            width: "100%",
            letterSpacing: "1px",
          }}
        >
          {udpTarget?.detected ? "TARGET DETECTED" : "NO TARGET"}
        </div>
      </div>
      <TelemRow label="T-LAT" value={udpTarget?.lat || "--"} accent />
      <TelemRow label="T-LON" value={udpTarget?.lon || "--"} accent />
      <TelemRow label="DIST" value={udpTarget?.dist || "--"} accent />
      <TelemRow label="GSD" value={udpTarget?.gsd || "--"} accent />
    </div>
  );
}

function TelemRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="telem-row">
      <span className="telem-label" style={accent ? { color: "#ffeb3b" } : undefined}>
        {label}
      </span>
      <input type="text" className="telem-input" value={value} readOnly />
    </div>
  );
}

export const TelemetryStats = memo(TelemetryStatsInner);

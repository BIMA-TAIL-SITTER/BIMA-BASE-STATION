
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
      <TelemRow label="LAT" value={t?.lat && t.lat !== 0 ? t.lat.toFixed(9) : "--.-------"} />
      <TelemRow label="LON" value={t?.lon && t.lon !== 0 ? t.lon.toFixed(9) : "---.-------"} />
      <TelemRow label="HDOP" value={t?.hdop !== undefined ? t.hdop.toFixed(2) : "0.00"} />
      <TelemRow label="SPD" value={t?.ground_speed_ms !== undefined ? `${t.ground_speed_ms.toFixed(0)} m/s` : "0 m/s"} />
      <TelemRow label="WP" value={t?.current_waypoint !== undefined ? String(t.current_waypoint) : "0"} />

      {/* UDP Target Section matching vanilla index.html */}
      <div className="telem-row">
        <span className="telem-label">TGT</span>
        <div
          className={`udp-detect-status telem-input ${
            udpTarget?.detected ? "is-detected" : ""
          }`}
          style={{ 
            display: "flex", alignItems: "center", justifyContent: "flex-start", 
            border: "none", background: "transparent", padding: 0,
            color: udpTarget?.detected ? "var(--caution)" : "var(--muted)" 
          }}
        >
          {udpTarget?.detected ? "DETECTED" : "NO TARGET"}
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
      <span className={`telem-label ${accent ? "is-target" : ""}`}>
        {label}
      </span>
      <input type="text" className="telem-input" value={value} readOnly />
    </div>
  );
}

export const TelemetryStats = memo(TelemetryStatsInner);

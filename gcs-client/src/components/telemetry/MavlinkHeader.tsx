"use client";

import { memo } from "react";
import { MavlinkSourceSelector } from "./MavlinkSourceSelector";
import type { MavlinkStatus } from "@/types/telemetry";

interface MavlinkHeaderProps {
  panelId: 1 | 2;
  mavlinkStatus: MavlinkStatus;
}

function MavlinkHeaderInner({ panelId, mavlinkStatus }: MavlinkHeaderProps) {
  const statusStyle = (): { bg: string; color: string; text: string } => {
    switch (mavlinkStatus) {
      case "ARMED":
        return { bg: "var(--ok)", color: "var(--status-text)", text: "ARMED" };
      case "DISARMED":
        return { bg: "var(--danger)", color: "var(--status-text)", text: "DISARMED" };
      default:
        return { bg: "var(--panel)", color: "var(--muted)", text: "No Mavlink Detected" };
    }
  };

  const status = statusStyle();

  return (
    <div style={{ width: "100%" }}>
      <MavlinkSourceSelector panelId={panelId} />
      <div className="telem-row" style={{ marginBottom: "10px" }}>
        <div
          id={`mavlink-status-${panelId}`}
          className="mavlink-status"
          style={{
            position: "relative",
            zIndex: 10,
            backgroundColor: status.bg,
            color: status.color,
            padding: "4px 0",
            borderRadius: "4px",
            fontWeight: "bold",
            fontSize: "14px",
            textAlign: "center",
            width: "100%",
            letterSpacing: "1px",
            border: mavlinkStatus === "DISCONNECTED" ? "1px solid var(--border)" : "none",
          }}
        >
          {status.text}
        </div>
      </div>
    </div>
  );
}

export const MavlinkHeader = memo(MavlinkHeaderInner);

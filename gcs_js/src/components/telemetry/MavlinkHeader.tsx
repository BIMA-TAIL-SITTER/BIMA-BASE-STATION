"use client";

import { memo } from "react";
import type { MavlinkStatus, UAVId } from "@/types/telemetry";

interface MavlinkHeaderProps {
  panelId: UAVId;
  mavlinkStatus: MavlinkStatus;
}

function MavlinkHeaderInner({ panelId, mavlinkStatus }: MavlinkHeaderProps) {
  const statusPresentation = (): { className: string; text: string } => {
    switch (mavlinkStatus) {
      case "ARMED":
        return { className: "is-armed", text: "ARMED" };
      case "DISARMED":
        return { className: "is-disarmed", text: "DISARMED" };
      default:
        return {
          className: "is-disconnected",
          text: "No Mavlink Detected",
        };
    }
  };

  const status = statusPresentation();

  return (
    <div className="mavlink-header">
      <div className="mavlink-status-row" style={{ width: "100%" }}>
        <div
          id={`mavlink-status-${panelId}`}
          className={`mavlink-status ${status.className}`}
          style={{ width: "100%" }}
        >
          {status.text}
        </div>
      </div>
    </div>
  );
}

export const MavlinkHeader = memo(MavlinkHeaderInner);

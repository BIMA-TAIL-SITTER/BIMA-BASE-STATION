"use client";

import { useCallback, useState } from "react";
import {
  createDefaultConnectionRecord,
  UAV_AGENT_BY_ID,
  UAV_IDS,
} from "@/config/agents";
import { useGCSStore } from "@/hooks/useGCSStore";
import type { UAVId } from "@/types/telemetry";
import UAVConnectionCardGrid, {
  type ConnectionFieldKey,
} from "./UAVConnectionCardGrid";

export default function EditConnectionModal() {
  const { isEditModalOpen } = useGCSStore();
  return isEditModalOpen ? <EditConnectionDialog /> : null;
}

function EditConnectionDialog() {
  const {
    uavs,
    setUAVConfig,
    setIsEditModalOpen,
  } = useGCSStore();
  const [values, setValues] = useState(() => {
    const next = createDefaultConnectionRecord();
    for (const uavId of UAV_IDS) {
      if (uavs[uavId]) {
        next[uavId] = { ...next[uavId], ...uavs[uavId] };
      }
    }
    return next;
  });

  const handleChange = useCallback(
    (uavId: UAVId, key: ConnectionFieldKey, value: string) => {
      setValues((current) => ({
        ...current,
        [uavId]: { ...current[uavId], [key]: value },
      }));
    },
    [],
  );

  const handleSave = useCallback(() => {
    const apiBase = window.location.origin.replace(/:\d+$/, ":8000");

    for (const uavId of UAV_IDS) {
      const hasVideo = UAV_AGENT_BY_ID[uavId].hasVideo;
      const ip = (values[uavId].tcpIp || "").trim();
      const mavPort = (values[uavId].mavlinkPort || "").trim();

      setUAVConfig(uavId, {
        streamPort: hasVideo ? (values[uavId].streamPort || "").trim() : "",
        tcpIp: ip,
        mavlinkPort: mavPort,
        jsonPort: hasVideo ? (values[uavId].jsonPort || "").trim() : "",
        missionUdpPort: !hasVideo ? (values[uavId].missionUdpPort || "").trim() : "",
        raspiIp: !hasVideo ? (values[uavId].raspiIp || "").trim() : "",
      });

      // Reconnect MAVLink for slots with a valid IP and port
      if (ip && ip !== "0" && ip !== "0.0.0.0" && mavPort) {
        const portNum = parseInt(mavPort, 10);
        if (portNum > 0) {
          fetch(`${apiBase}/api/telemetry/connect`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ slot: uavId, ip, port: portNum }),
          }).catch((e) =>
            console.error(`[edit-modal] Reconnect slot ${uavId} failed:`, e),
          );
        }
      }

      // POST mission config to backend for copter slots (writes mission_config.json)
      if (!hasVideo && (values[uavId].missionUdpPort || "").trim()) {
        const raspiIp = (values[uavId].raspiIp || "").trim();
        if (raspiIp) {
          fetch(`${apiBase}/api/control/mission-config`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              slot: uavId,
              raspi_ip: raspiIp,
              mission_udp_port: parseInt(values[uavId].missionUdpPort.trim()) || 14560,
            }),
          }).catch(() => {/* ignore — best effort */});
        }
      }
    }
    setIsEditModalOpen(false);
  }, [setIsEditModalOpen, setUAVConfig, values]);

  return (
    <div className="setup-overlay">
      <div className="setup-modal" role="dialog" aria-modal="true" aria-labelledby="edit-connection-title">
        <button
          onClick={() => setIsEditModalOpen(false)}
          className="setup-close-button"
          aria-label="Close connection settings"
          title="Close"
        >
          ×
        </button>

        <div className="setup-header">
          <div className="setup-icon" aria-hidden="true">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </div>
          <h2 className="setup-title" id="edit-connection-title">EDIT CONNECTION SETUP</h2>
        </div>

        <UAVConnectionCardGrid
          values={values}
          onChange={handleChange}
          onEnter={handleSave}
        />

        <div className="setup-actions setup-actions-with-cancel">
          <button
            onClick={() => setIsEditModalOpen(false)}
            className="setup-btn-secondary"
          >
            CANCEL
          </button>
          <button className="setup-btn-primary" onClick={handleSave}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14" />
              <path d="M12 5l7 7-7 7" />
            </svg>
            SAVE &amp; RECONNECT
          </button>
        </div>

        <div className="setup-footer">
          <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
          </svg>
          Updates are cached locally and applied to all configured UAV slots.
        </div>
      </div>
    </div>
  );
}

"use client";

import React, { useState, useEffect } from "react";
import { useGCSStore } from "@/hooks/useGCSStore";
import type { UAVConnectionConfig } from "@/types/telemetry";

const portIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </svg>
);
const videoIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polygon points="23 7 16 12 23 17 23 7" />
    <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
  </svg>
);
const serverIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
    <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
    <line x1="6" y1="6" x2="6.01" y2="6" />
    <line x1="6" y1="18" x2="6.01" y2="18" />
  </svg>
);
const codeIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </svg>
);

export default function EditConnectionModal() {
  const { uav1, uav2, setUAVConfig, isEditModalOpen, setIsEditModalOpen } = useGCSStore();

  const [uav1StreamPort, setUav1StreamPort] = useState("");
  const [uav1TcpIp, setUav1TcpIp] = useState("");
  const [uav1MavlinkPort, setUav1MavlinkPort] = useState("");
  const [uav1JsonPort, setUav1JsonPort] = useState("");

  const [uav2StreamPort, setUav2StreamPort] = useState("");
  const [uav2TcpIp, setUav2TcpIp] = useState("");
  const [uav2MavlinkPort, setUav2MavlinkPort] = useState("");
  const [uav2JsonPort, setUav2JsonPort] = useState("");

  useEffect(() => {
    if (isEditModalOpen) {
      setUav1StreamPort(uav1?.streamPort || "5600");
      setUav1TcpIp(uav1?.tcpIp || "192.168.1.10");
      setUav1MavlinkPort(uav1?.mavlinkPort || "5761");
      setUav1JsonPort(uav1?.jsonPort || "5001");

      setUav2StreamPort(uav2?.streamPort || "5601");
      setUav2TcpIp(uav2?.tcpIp || "192.168.1.11");
      setUav2MavlinkPort(uav2?.mavlinkPort || "5762");
      setUav2JsonPort(uav2?.jsonPort || "5002");
    }
  }, [isEditModalOpen, uav1, uav2]);

  if (!isEditModalOpen) return null;

  const handleSimpan = () => {
    const cfg1: UAVConnectionConfig = {
      streamPort: uav1StreamPort.trim() || "5600",
      tcpIp: uav1TcpIp.trim() || "192.168.1.10",
      mavlinkPort: uav1MavlinkPort.trim() || "5761",
      jsonPort: uav1JsonPort.trim() || "5001",
    };
    const cfg2: UAVConnectionConfig = {
      streamPort: uav2StreamPort.trim() || "5601",
      tcpIp: uav2TcpIp.trim() || "192.168.1.11",
      mavlinkPort: uav2MavlinkPort.trim() || "5762",
      jsonPort: uav2JsonPort.trim() || "5002",
    };

    setUAVConfig(1, cfg1);
    setUAVConfig(2, cfg2);
    setIsEditModalOpen(false);
  };

  return (
    <div className="setup-overlay">
      <div className="setup-modal relative">
        {/* Tombol Tutup Pojok Kanan Atas */}
        <button
          onClick={() => setIsEditModalOpen(false)}
          className="absolute top-4 right-4 text-[#7B829A] hover:text-white px-2 py-1 text-base font-bold transition-colors"
          title="Tutup"
        >
          ✕
        </button>

        {/* Header */}
        <div className="setup-header">
          <div className="setup-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
            </svg>
          </div>
          <h2 className="setup-title">EDIT CONNECTION SETUP</h2>
          <p className="setup-subtitle">
            Update UAV connection parameters and re-apply in real time
          </p>
        </div>

        {/* UAV Cards */}
        <div className="setup-cards">
          {/* UAV 1 */}
          <div className="setup-card">
            <div className="setup-card-header">
              <div className="setup-card-indicator" />
              <span className="setup-card-label">UAV 1</span>
              <span className="setup-card-type">FIXED WING</span>
            </div>
            <div className="setup-card-body">
              <div className="setup-field">
                <label className="setup-field-label">
                  {videoIcon}
                  STREAM PORT
                </label>
                <input
                  type="text"
                  className="setup-input"
                  placeholder="e.g. 5600"
                  value={uav1StreamPort}
                  onChange={(e) => setUav1StreamPort(e.target.value)}
                />
              </div>
              <div className="setup-field">
                <label className="setup-field-label">
                  {serverIcon}
                  TCP IP
                </label>
                <input
                  type="text"
                  className="setup-input"
                  placeholder="e.g. 192.168.1.10"
                  value={uav1TcpIp}
                  onChange={(e) => setUav1TcpIp(e.target.value)}
                />
              </div>
              <div className="setup-field">
                <label className="setup-field-label">
                  {portIcon}
                  MAVLINK PORT
                </label>
                <input
                  type="text"
                  className="setup-input"
                  placeholder="e.g. 5761"
                  value={uav1MavlinkPort}
                  onChange={(e) => setUav1MavlinkPort(e.target.value)}
                />
              </div>
              <div className="setup-field">
                <label className="setup-field-label">
                  {codeIcon}
                  JSON PORT
                </label>
                <input
                  type="text"
                  className="setup-input"
                  placeholder="e.g. 5001"
                  value={uav1JsonPort}
                  onChange={(e) => setUav1JsonPort(e.target.value)}
                />
              </div>
            </div>
          </div>

          {/* UAV 2 */}
          <div className="setup-card">
            <div className="setup-card-header">
              <div className="setup-card-indicator" style={{ "--card-accent": "#40C4FF" } as React.CSSProperties} />
              <span className="setup-card-label">UAV 2</span>
              <span className="setup-card-type">FIXED WING</span>
            </div>
            <div className="setup-card-body">
              <div className="setup-field">
                <label className="setup-field-label">
                  {videoIcon}
                  STREAM PORT
                </label>
                <input
                  type="text"
                  className="setup-input"
                  placeholder="e.g. 5601"
                  value={uav2StreamPort}
                  onChange={(e) => setUav2StreamPort(e.target.value)}
                />
              </div>
              <div className="setup-field">
                <label className="setup-field-label">
                  {serverIcon}
                  TCP IP
                </label>
                <input
                  type="text"
                  className="setup-input"
                  placeholder="e.g. 192.168.1.11"
                  value={uav2TcpIp}
                  onChange={(e) => setUav2TcpIp(e.target.value)}
                />
              </div>
              <div className="setup-field">
                <label className="setup-field-label">
                  {portIcon}
                  MAVLINK PORT
                </label>
                <input
                  type="text"
                  className="setup-input"
                  placeholder="e.g. 5762"
                  value={uav2MavlinkPort}
                  onChange={(e) => setUav2MavlinkPort(e.target.value)}
                />
              </div>
              <div className="setup-field">
                <label className="setup-field-label">
                  {codeIcon}
                  JSON PORT
                </label>
                <input
                  type="text"
                  className="setup-input"
                  placeholder="e.g. 5002"
                  value={uav2JsonPort}
                  onChange={(e) => setUav2JsonPort(e.target.value)}
                />
              </div>
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="setup-actions flex items-center justify-center gap-4 mt-2">
          <button
            onClick={() => setIsEditModalOpen(false)}
            className="px-6 py-3.5 text-xs font-bold rounded-lg bg-[#181C26] hover:bg-[#232A39] text-[#A0A6B8] border border-[#2B3245] transition-all tracking-wider"
          >
            CANCEL
          </button>
          <button
            className="setup-btn-primary"
            onClick={handleSimpan}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14" />
              <path d="M12 5l7 7-7 7" />
            </svg>
            SAVE &amp; RECONNECT
          </button>
        </div>

        {/* Footer */}
        <div className="setup-footer">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
          </svg>
          Updates are cached immediately to local storage and re-applied to active UAV connections.
        </div>
      </div>
    </div>
  );
}

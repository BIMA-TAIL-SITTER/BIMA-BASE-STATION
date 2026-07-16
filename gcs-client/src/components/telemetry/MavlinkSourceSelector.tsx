"use client";

import { useEffect, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MavlinkSourceSelectorProps {
  panelId: 1 | 2;
  onConnect?: (ip: string, port: number) => void;
  onDisconnect?: () => void;
}

export function MavlinkSourceSelector({ panelId, onConnect, onDisconnect }: MavlinkSourceSelectorProps) {
  const [sources, setSources] = useState<string[]>([]);
  const [selectedSource, setSelectedSource] = useState<string>("none");
  const [port, setPort] = useState<number>(5761);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/api/telemetry/sources`)
      .then((res) => res.json())
      .then((data) => {
        if (data.hosts) {
          setSources(data.hosts);
        }
        if (data.default_port) {
          setPort(data.default_port);
        }
      })
      .catch((e) => console.error("[telemetry] Failed to load MAVLink sources:", e));
  }, []);

  const handleSourceChange = async (val: string) => {
    setSelectedSource(val);
    if (val === "none") {
      try {
        await fetch(`${API_BASE}/api/telemetry/disconnect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slot: panelId }),
        });
        if (onDisconnect) onDisconnect();
      } catch (e) {
        console.error(`[telemetry] Disconnect slot ${panelId} error:`, e);
      }
    }
  };

  const handleConnect = async () => {
    if (selectedSource === "none") return;
    setConnecting(true);
    try {
      await fetch(`${API_BASE}/api/telemetry/connect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slot: panelId, ip: selectedSource, port }),
      });
      console.log(`[telemetry] Connected slot ${panelId} to ${selectedSource}:${port}`);
      if (onConnect) onConnect(selectedSource, port);
    } catch (e) {
      console.error(`[telemetry] Connect slot ${panelId} error:`, e);
    } finally {
      setConnecting(false);
    }
  };

  return (
    <div
      className="cam-selector"
      style={{
        marginBottom: "10px",
        borderBottom: "1px solid var(--border)",
        paddingBottom: "8px",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
      }}
    >
      <select
        id={`mavlink-source-${panelId}`}
        className="cam-select"
        value={selectedSource}
        onChange={(e) => handleSourceChange(e.target.value)}
      >
        <option value="none">No Source</option>
        {sources.map((ip) => (
          <option key={ip} value={ip}>
            {ip}
          </option>
        ))}
      </select>
      {selectedSource !== "none" && (
        <>
          <input
            type="number"
            id={`mavlink-port-${panelId}`}
            className="cam-select"
            value={port}
            onChange={(e) => setPort(parseInt(e.target.value, 10) || 5761)}
            style={{ width: "60px", marginLeft: "5px" }}
            placeholder="Port"
          />
          <button
            id={`mavlink-btn-${panelId}`}
            className="cam-select"
            onClick={handleConnect}
            disabled={connecting}
            style={{
              marginLeft: "5px",
              padding: "2px 8px",
              cursor: "pointer",
              background: "#444",
              border: "1px solid #555",
              color: "#fff",
            }}
          >
            {connecting ? "..." : "Connect"}
          </button>
        </>
      )}
    </div>
  );
}

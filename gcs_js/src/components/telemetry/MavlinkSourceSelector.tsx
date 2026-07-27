"use client";

import { useEffect, useState, useMemo } from "react";
import { useGCSStore } from "@/hooks/useGCSStore";
import { UAV_AGENT_BY_ID, UAV_IDS } from "@/config/agents";
import type { UAVId } from "@/types/telemetry";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface MavlinkSourceSelectorProps {
  panelId: UAVId;
  onConnect?: (ip: string, port: number) => void;
  onDisconnect?: () => void;
}

export function MavlinkSourceSelector({ panelId, onConnect, onDisconnect }: MavlinkSourceSelectorProps) {
  const { uavs } = useGCSStore();
  const [apiSources, setApiSources] = useState<string[]>([]);
  const [selectedSource, setSelectedSource] = useState<string>("none");
  const [port, setPort] = useState<number>(
    Number(
      uavs[panelId]?.mavlinkPort
        ?? UAV_AGENT_BY_ID[panelId].defaultConnection.mavlinkPort,
    ),
  );
  const [connecting, setConnecting] = useState(false);

  // Build merged & deduplicated source list: configured TCP IPs first, then API sources
  const sources = useMemo(() => {
    const configuredIps: string[] = [];
    for (const uavId of UAV_IDS) {
      const ip = uavs[uavId]?.tcpIp;
      if (ip && !configuredIps.includes(ip)) configuredIps.push(ip);
    }

    // Merge API sources, skip duplicates
    const merged = [...configuredIps];
    for (const ip of apiSources) {
      if (!merged.includes(ip)) merged.push(ip);
    }
    return merged;
  }, [uavs, apiSources]);

  useEffect(() => {
    fetch(`${API_BASE}/api/telemetry/sources`)
      .then((res) => res.json())
      .then((data) => {
        if (data.hosts) {
          setApiSources(data.hosts);
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
      className="cam-selector mavlink-source-selector"
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
            onChange={(e) => setPort(
              parseInt(e.target.value, 10)
                || Number(UAV_AGENT_BY_ID[panelId].defaultConnection.mavlinkPort),
            )}
            style={{ width: "60px", marginLeft: "5px" }}
            placeholder="Port"
          />
          <button
            id={`mavlink-btn-${panelId}`}
            className="cam-select mavlink-connect-button"
            onClick={handleConnect}
            disabled={connecting}
          >
            {connecting ? "..." : "Connect"}
          </button>
        </>
      )}
    </div>
  );
}

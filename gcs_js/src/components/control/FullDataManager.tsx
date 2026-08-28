"use client";

import {
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { UAV_AGENT_BY_ID } from "@/config/agents";
import { useGCSStore } from "@/hooks/useGCSStore";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { TelemetryData, UAVId } from "@/types/telemetry";
import { UavSelector } from "./UavSelector";

/** Fields to exclude from the raw data view (internal / redundant). */
const HIDDEN_FIELDS = new Set(["slot"]);

function classifyType(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return Number.isFinite(value) ? "number" : "number (NaN/Inf)";
  if (typeof value === "string") return "string";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return String(value);
    // Show up to 6 decimal places, trim trailing zeros
    return Number.isInteger(value) ? String(value) : value.toFixed(6).replace(/\.?0+$/, "");
  }
  if (typeof value === "string") return value || '""';
  return JSON.stringify(value);
}

export function FullDataManager() {
  const [slot, setSlot] = useState<UAVId>(1);
  const [searchQuery, setSearchQuery] = useState("");
  const [isPaused, setIsPaused] = useState(false);
  const [telemetry, setTelemetry] = useState<TelemetryData | null>(null);
  const frozenRef = useRef<TelemetryData | null>(null);

  const { config, isConfigured } = useGCSStore();
  const agent = UAV_AGENT_BY_ID[slot];

  const wsHost = config?.ws_host;
  const telemetryUrl = isConfigured && wsHost ? `ws://${wsHost}/ws/telemetry` : "";

  const onMessage = useCallback(
    (data: string) => {
      try {
        const packet = JSON.parse(data) as TelemetryData;
        if (packet.slot !== slot) return;
        if (!isPaused) {
          setTelemetry(packet);
        }
      } catch {
        // Ignore malformed messages
      }
    },
    [slot, isPaused],
  );

  useWebSocket({
    url: telemetryUrl,
    onMessage,
    enabled: Boolean(telemetryUrl),
  });

  const handleSlotChange = useCallback((nextSlot: UAVId) => {
    setSlot(nextSlot);
    setTelemetry(null);
    frozenRef.current = null;
    setIsPaused(false);
  }, []);

  const handleTogglePause = useCallback(() => {
    setIsPaused((prev) => {
      if (!prev) {
        // Freezing: snapshot the current data
        frozenRef.current = telemetry;
      }
      return !prev;
    });
  }, [telemetry]);

  const displayData = isPaused ? frozenRef.current : telemetry;

  const entries = useMemo(() => {
    if (!displayData) return [];
    const all = Object.entries(displayData)
      .filter(([key]) => !HIDDEN_FIELDS.has(key))
      .sort(([a], [b]) => a.localeCompare(b));

    if (!searchQuery.trim()) return all;
    const q = searchQuery.toLowerCase();
    return all.filter(
      ([key, value]) =>
        key.toLowerCase().includes(q) ||
        String(value).toLowerCase().includes(q),
    );
  }, [displayData, searchQuery]);

  const totalFields = displayData
    ? Object.keys(displayData).filter((k) => !HIDDEN_FIELDS.has(k)).length
    : 0;

  return (
    <div
      className="mission-workspace"
      style={{
        "--agent-color": agent.color,
        "--agent-color-rgb": agent.colorRgb,
      } as CSSProperties}
    >
      <UavSelector value={slot} onChange={handleSlotChange} />

      <section className="operations-section" style={{ flex: 1, display: "flex", flexDirection: "column", minHeight: 0 }}>
        <header className="operations-section-heading">
          <div>
            <h2>FULL TELEMETRY DATA</h2>
            <span>
              {displayData
                ? isPaused
                  ? "DATA PAUSED"
                  : "LIVE"
                : "WAITING FOR DATA..."}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
            <button
              type="button"
              className={`operations-button ${isPaused ? "is-primary" : ""}`}
              onClick={handleTogglePause}
              disabled={!displayData}
              style={{ fontSize: "11px", padding: "6px 14px" }}
            >
              {isPaused ? "▶ RESUME" : "⏸ PAUSE"}
            </button>
            <strong>{entries.length} / {totalFields} FIELDS</strong>
          </div>
        </header>

        {/* Search bar */}
        <div style={{
          padding: "8px 12px",
          borderBottom: "1px solid var(--border-subtle)",
          background: "var(--bg-elevated)",
        }}>
          <input
            type="text"
            placeholder="Search field name or value (e.g. battery, altitude, STABILIZE)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              width: "100%",
              padding: "8px 12px",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border-subtle)",
              background: "rgba(0, 0, 0, 0.3)",
              color: "var(--text-primary)",
              fontSize: "12px",
              outline: "none",
            }}
          />
        </div>

        {/* Table */}
        {displayData ? (
          <div className="operations-table-scroll" style={{ flex: 1, minHeight: 0 }}>
            <table
              className="operations-table"
              aria-label={`Full telemetry data for ${agent.shortLabel}`}
              style={{ minWidth: "500px" }}
            >
              <thead>
                <tr>
                  <th style={{ width: "40px" }}>#</th>
                  <th>FIELD NAME</th>
                  <th>RAW VALUE</th>
                  <th style={{ width: "100px" }}>TYPE</th>
                </tr>
              </thead>
              <tbody>
                {entries.map(([key, value], index) => (
                  <tr key={key}>
                    <td style={{ color: "var(--text-muted)" }}>{index + 1}</td>
                    <td className="operations-table-primary">{key}</td>
                    <td style={{ fontFamily: "var(--font-mono, monospace)" }}>
                      {formatValue(value)}
                    </td>
                    <td>
                      <small style={{ color: "var(--text-muted)" }}>
                        {classifyType(value)}
                      </small>
                    </td>
                  </tr>
                ))}
                {entries.length === 0 && (
                  <tr>
                    <td colSpan={4} style={{ textAlign: "center", padding: "24px", color: "var(--text-muted)" }}>
                      {searchQuery
                        ? `No fields matching "${searchQuery}"`
                        : "No data available"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="operations-empty-state">
            <strong>NO TELEMETRY DATA</strong>
            <span>
              Connect {agent.shortLabel} to start receiving telemetry data.
            </span>
          </div>
        )}
      </section>
    </div>
  );
}

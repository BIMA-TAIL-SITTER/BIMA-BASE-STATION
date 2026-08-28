"use client";

import { memo, useState, useCallback, type CSSProperties } from "react";
import { UAV_AGENT_BY_ID } from "@/config/agents";
import type { MavlinkStatus, TelemetryData, UAVId } from "@/types/telemetry";
import { MavlinkHeader } from "./MavlinkHeader";
import { useUavControl } from "@/hooks/useUavControl";

import { ModeSelector, COPTER_FLIGHT_MODES } from "./ModeSelector";
interface CopterTelemetryPanelProps {
  panelId: UAVId;
  telemetry: TelemetryData | null;
  mavlinkStatus: MavlinkStatus;
}

import { formatNumber, formatCoordinate, formatDistance, formatMetricValue } from "@/utils/telemetryFormatters";

function CopterCompass({
  heading,
  color,
}: {
  heading: number | undefined;
  color: string;
}) {
  const normalizedHeading = heading ?? 0;
  const iconStyle = {
    "--copter-color": color,
    WebkitMaskImage: "url('/copter.svg')",
    maskImage: "url('/copter.svg')",
  } as CSSProperties;

  return (
    <div
      className="copter-compass"
      aria-label={
        heading === undefined
          ? "Heading unavailable"
          : `Heading ${Math.round(normalizedHeading)} degrees`
      }
    >
      <div
        className="copter-compass-dial"
        style={{ transform: `rotate(${-normalizedHeading}deg)` }}
        aria-hidden="true"
      >
        <span className="copter-cardinal copter-cardinal-n">N</span>
        <span className="copter-cardinal copter-cardinal-e">E</span>
        <span className="copter-cardinal copter-cardinal-s">S</span>
        <span className="copter-cardinal copter-cardinal-w">W</span>
        {Array.from({ length: 12 }, (_, index) => (
          <span
            className="copter-compass-tick"
            key={index}
            style={{ transform: `rotate(${index * 30}deg)` }}
          />
        ))}
      </div>
      <span className="copter-compass-icon" style={iconStyle} aria-hidden="true" />
      <span className="copter-heading-value">
        {heading === undefined
          ? "---\u00b0"
          : `${String(Math.round(normalizedHeading)).padStart(3, "0")}\u00b0`}
      </span>
    </div>
  );
}

export function MetricCell({
  label,
  value,
  accent,
  state,
}: {
  label: string;
  value: string;
  accent?: boolean;
  state?: "armed" | "disarmed";
}) {
  return (
    <div className={`copter-metric ${accent ? "is-accent" : ""} ${state ? `is-${state}` : ""}`}>
      <span className="copter-metric-label">{label}</span>
      <span className="copter-metric-value">{value}</span>
    </div>
  );
}


import { useGCSStore } from "@/hooks/useGCSStore";
import type { MetricConfig } from "@/types/telemetry";
import { AVAILABLE_METRICS } from "@/config/metrics";

function CopterTelemetryPanelInner({
  panelId,
  telemetry,
  mavlinkStatus,
}: CopterTelemetryPanelProps) {
  const agent = UAV_AGENT_BY_ID[panelId];
  const heading = telemetry?.heading_deg ?? telemetry?.yaw_deg;
  const isArmed = telemetry?.armed;
  const { uavs, uavMetrics, setUAVMetrics } = useGCSStore();
  const panelStyle = {
    "--agent-accent": agent.color,
    "--agent-accent-rgb": agent.colorRgb,
  } as CSSProperties;

  const isConnected =
    mavlinkStatus === "ARMED" || mavlinkStatus === "DISARMED";

  const battery = telemetry
    ? `${formatNumber(telemetry.battery_voltage, 1, "V")} / ${
        Number.isFinite(telemetry.battery_remaining_pct)
          ? `${telemetry.battery_remaining_pct}%`
          : "--%"
      }`
    : "--.-V / --%";
  const waypoint = telemetry
    ? `${telemetry.current_waypoint ?? "--"}/${telemetry.total_waypoints ?? "--"}`
    : "--/--";

  // Context Menu State
  const [contextMenu, setContextMenu] = useState<{ visible: boolean; x: number; y: number; index: number } | null>(null);
  
  // Modal State
  const [showMetricModal, setShowMetricModal] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null); // null means adding new
  const [searchQuery, setSearchQuery] = useState("");

  const metrics = uavMetrics[panelId] || [];

  const handleContextMenu = (e: React.MouseEvent, index: number) => {
    e.preventDefault();
    const gridRect = e.currentTarget.closest(".copter-metrics-grid")?.getBoundingClientRect();
    if (!gridRect) return;
    
    // Position relative to grid container
    setContextMenu({
      visible: true,
      x: e.clientX - gridRect.left,
      y: e.clientY - gridRect.top,
      index,
    });
  };

  const closeContextMenu = () => setContextMenu(null);

  const handleDeleteMetric = () => {
    if (contextMenu) {
      const newMetrics = [...metrics];
      newMetrics.splice(contextMenu.index, 1);
      setUAVMetrics(panelId, newMetrics);
    }
    closeContextMenu();
  };

  const handleEditMetric = () => {
    if (contextMenu) {
      setEditingIndex(contextMenu.index);
      setSearchQuery("");
      setShowMetricModal(true);
    }
    closeContextMenu();
  };

  const handleAddMetric = () => {
    setEditingIndex(null);
    setSearchQuery("");
    setShowMetricModal(true);
  };

  const handleSelectMetric = (template: Omit<MetricConfig, "id">) => {
    const newMetrics = [...metrics];
    const newMetric: MetricConfig = { ...template, id: Math.random().toString(36).substring(7) };
    
    if (editingIndex !== null) {
      // Preserve accent status if editing
      newMetric.accent = newMetrics[editingIndex].accent;
      newMetrics[editingIndex] = newMetric;
    } else {
      newMetrics.push(newMetric);
    }
    
    setUAVMetrics(panelId, newMetrics);
    setShowMetricModal(false);
  };

  return (
    <section
      className="telem-panel copter-telemetry-panel"
      id={`telem-panel-${panelId}`}
      style={panelStyle}
      aria-labelledby={`copter-panel-title-${panelId}`}
      onClick={closeContextMenu} // Close context menu on any click inside panel
    >
      <MavlinkHeader panelId={panelId} mavlinkStatus={mavlinkStatus} />

      <div className="copter-primary-data">
        <CopterCompass heading={heading} color={agent.color} />
        <div className="copter-primary-grid">
          <ModeSelector
            panelId={panelId}
            currentMode={telemetry?.flight_mode || "--"}
            isConnected={isConnected}
            availableModes={COPTER_FLIGHT_MODES}
          />
          <MetricCell label="BATTERY" value={battery} />
          <MetricCell label="WP" value={waypoint} accent />
        </div>
      </div>

      <div className="copter-metrics-grid" style={{ position: "relative" }}>
        {metrics.map((metric, index) => {
          const rawValue = telemetry?.[metric.telemetryKey];
          const displayValue = formatMetricValue(rawValue, metric.format, metric.decimals, metric.suffix);
          return (
            <div key={metric.id} onContextMenu={(e) => handleContextMenu(e, index)}>
              <MetricCell 
                label={metric.label} 
                value={displayValue} 
                accent={metric.accent} 
              />
            </div>
          );
        })}
        
        <button className="copter-metric-add-btn" onClick={handleAddMetric}>
          + TAMBAH DATA
        </button>

        {contextMenu?.visible && (
          <div 
            className="metric-context-menu" 
            style={{ top: contextMenu.y, left: contextMenu.x }}
          >
            <button onClick={handleEditMetric}>Ubah Data</button>
            <button onClick={handleDeleteMetric} className="delete-opt">Hapus Data</button>
          </div>
        )}
      </div>

      {showMetricModal && (
        <div className="metric-modal-overlay" onClick={() => setShowMetricModal(false)}>
          <div className="metric-modal" onClick={(e) => e.stopPropagation()}>
            <div className="metric-modal-header">
              <h3>{editingIndex !== null ? "Ubah Data Metrik" : "Tambah Data Metrik"}</h3>
              <button className="metric-modal-close" onClick={() => setShowMetricModal(false)}>✕</button>
            </div>
            
            <div style={{ padding: "0 12px 12px", borderBottom: "1px solid rgba(255, 255, 255, 0.1)" }}>
              <input 
                type="text" 
                placeholder="Cari metrik (e.g. ALT, BATT, YAW)..." 
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  borderRadius: "6px",
                  border: "1px solid rgba(255, 255, 255, 0.2)",
                  background: "rgba(0,0,0,0.5)",
                  color: "white",
                  outline: "none"
                }}
                autoFocus
              />
            </div>

            <div className="metric-modal-list">
              {AVAILABLE_METRICS
                .filter(m => m.label.toLowerCase().includes(searchQuery.toLowerCase()) || m.telemetryKey.toLowerCase().includes(searchQuery.toLowerCase()))
                .map((template) => (
                <button 
                  key={template.telemetryKey} 
                  className="metric-modal-item"
                  onClick={() => handleSelectMetric(template)}
                >
                  <span className="metric-label">{template.label}</span>
                  <span className="metric-key">{template.telemetryKey}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="copter-mission-actions" style={{ display: "flex", gap: "8px", marginTop: "12px", flexDirection: "column" }}>
        <div style={{ display: "flex", gap: "8px" }}>
          <button
            className="operations-button is-secondary"
            onClick={async (e) => {
              const uavConfig = uavs[panelId];
              if (!uavConfig?.raspiIp || !uavConfig?.missionUdpPort) {
                alert(`Please configure the Raspi IP and Mission UDP Port for UAV ${panelId} in Edit Connection first!`);
                return;
              }
              const btn = e.currentTarget;
              const originalText = btn.textContent;
              btn.textContent = "UPLOADING...";
              btn.disabled = true;
              try {
                const apiBase = window.location.origin.replace(/:\d+$/, ":8000");
                const res = await fetch(`${apiBase}/api/control/companion/upload`, { 
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ ip: uavConfig.raspiIp, port: parseInt(uavConfig.missionUdpPort) || 14560 })
                });
                const data = await res.json();
                alert(data.message + "\n\n" + (data.output || ""));
              } catch (err) {
                alert("Request failed.");
              } finally {
                btn.textContent = originalText;
                btn.disabled = false;
              }
            }}
            style={{ flex: 1, padding: "8px", fontSize: "11px" }}
          >
            UPLOAD MISSION
          </button>
          <button
            className="operations-button is-primary"
            onClick={async (e) => {
              const uavConfig = uavs[panelId];
              if (!uavConfig?.raspiIp || !uavConfig?.missionUdpPort) {
                alert(`Please configure the Raspi IP and Mission UDP Port for UAV ${panelId} in Edit Connection first!`);
                return;
              }
              const btn = e.currentTarget;
              const originalText = btn.textContent;
              btn.textContent = "STARTING...";
              btn.disabled = true;
              try {
                const apiBase = window.location.origin.replace(/:\d+$/, ":8000");
                const res = await fetch(`${apiBase}/api/control/companion/start`, { 
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ ip: uavConfig.raspiIp, port: parseInt(uavConfig.missionUdpPort) || 14560 })
                });
                const data = await res.json();
                alert(data.message + "\n\n" + (data.output || ""));
              } catch (err) {
                alert("Request failed.");
              } finally {
                btn.textContent = originalText;
                btn.disabled = false;
              }
            }}
            style={{ flex: 1, padding: "8px", fontSize: "11px", backgroundColor: "var(--agent-accent)", color: "#000" }}
          >
            START MISSION
          </button>
        </div>
      </div>
    </section>
  );
}

export const CopterTelemetryPanel = memo(CopterTelemetryPanelInner);

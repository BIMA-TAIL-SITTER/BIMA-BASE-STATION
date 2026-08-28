"use client";
import { memo, useState } from "react";
import type { TelemetryData, MavlinkStatus, MetricConfig } from "@/types/telemetry";
import { useGCSStore } from "@/hooks/useGCSStore";
import { AVAILABLE_METRICS } from "@/config/metrics";
import { formatMetricValue, formatNumber } from "@/utils/telemetryFormatters";
import { ModeSelector, PLANE_FLIGHT_MODES } from "./ModeSelector";
import { MetricCell } from "./CopterTelemetryPanel";

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

function TelemetryStatsInner({ telemetry, mavlinkStatus, panelId, udpTarget }: TelemetryStatsProps) {
  const t = telemetry;
  const { uavMetrics, setUAVMetrics } = useGCSStore();
  const metrics = uavMetrics[panelId] || [];

  const battery = t
    ? `${formatNumber(t.battery_voltage, 1, "V")} / ${
        Number.isFinite(t.battery_remaining_pct)
          ? `${t.battery_remaining_pct}%`
          : "--%"
      }`
    : "--.-V / --%";
  const waypoint = t
    ? `${t.current_waypoint ?? "--"}/${t.total_waypoints ?? "--"}`
    : "--/--";

  const [contextMenu, setContextMenu] = useState<{ visible: boolean; x: number; y: number; index: number } | null>(null);
  const [showMetricModal, setShowMetricModal] = useState(false);
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [searchQuery, setSearchQuery] = useState("");

  const handleContextMenu = (e: React.MouseEvent, index: number) => {
    e.preventDefault();
    const gridRect = e.currentTarget.closest(".telem-stats-rail")?.getBoundingClientRect();
    if (!gridRect) return;
    
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
      newMetric.accent = newMetrics[editingIndex].accent;
      newMetrics[editingIndex] = newMetric;
    } else {
      newMetrics.push(newMetric);
    }
    
    setUAVMetrics(panelId, newMetrics);
    setShowMetricModal(false);
  };

  return (
    <div className="telem-stats" onClick={closeContextMenu}>
      <div className="telem-stats-strip">
        <div className="copter-primary-grid" style={{ gridColumn: "1 / -1", marginBottom: "4px", gridTemplateColumns: "repeat(3, 1fr)" }}>
          <ModeSelector
            panelId={panelId}
            currentMode={t?.flight_mode || "--"}
            isConnected={mavlinkStatus === "ARMED" || mavlinkStatus === "DISARMED"}
            availableModes={PLANE_FLIGHT_MODES}
          />
          <MetricCell label="BATTERY" value={battery} />
          <MetricCell label="WP" value={waypoint} accent />
        </div>
        <div 
          className={`tgt-status-bar ${udpTarget?.detected ? "is-detected" : ""}`}
          style={{
            gridColumn: "1 / -1",
            width: "100%",
            textAlign: "center",
            padding: "6px",
            backgroundColor: udpTarget?.detected ? "rgba(var(--warning-rgb, 245, 166, 35), 0.15)" : "rgba(var(--bg-base-rgb, 0, 0, 0), 0.3)",
            color: udpTarget?.detected ? "var(--warning)" : "var(--text-muted)",
            border: `1px solid ${udpTarget?.detected ? "rgba(var(--warning-rgb, 245, 166, 35), 0.3)" : "var(--border-subtle)"}`,
            borderRadius: "var(--radius-sm)",
            fontWeight: 600,
            fontSize: "10px",
            letterSpacing: "0.05em"
          }}
        >
          {udpTarget?.detected ? "TARGET DETECTED" : "NO TARGET"}
        </div>
      </div>

      <div className="telem-stats-rail" style={{ position: "relative" }}>
        {metrics.map((metric, index) => {
          const rawValue = telemetry?.[metric.telemetryKey];
          const displayValue = formatMetricValue(rawValue, metric.format, metric.decimals, metric.suffix);
          return (
            <div key={metric.id} onContextMenu={(e) => handleContextMenu(e, index)}>
              <TelemRow label={metric.label} value={displayValue} accent={metric.accent} />
            </div>
          );
        })}
        
        <TelemRow label="DIST" value={udpTarget?.dist || "--"} accent />
        <TelemRow label="GSD" value={udpTarget?.gsd || "--"} accent />

        <button className="copter-metric-add-btn" style={{ marginTop: 8 }} onClick={handleAddMetric}>
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
    </div>
  );
}

function TelemRow({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="telem-row">
      <span className={`telem-label ${accent ? "is-target" : ""}`}>
        {label}
      </span>
      <span className="telem-input">{value}</span>
    </div>
  );
}

export const TelemetryStats = memo(TelemetryStatsInner);

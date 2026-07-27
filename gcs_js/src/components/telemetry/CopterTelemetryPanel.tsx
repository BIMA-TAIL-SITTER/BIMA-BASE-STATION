"use client";

import { memo, type CSSProperties } from "react";
import { UAV_AGENT_BY_ID } from "@/config/agents";
import type { MavlinkStatus, TelemetryData, UAVId } from "@/types/telemetry";
import { MavlinkHeader } from "./MavlinkHeader";

interface CopterTelemetryPanelProps {
  panelId: UAVId;
  telemetry: TelemetryData | null;
  mavlinkStatus: MavlinkStatus;
}

function formatNumber(
  value: number | undefined,
  decimals: number,
  suffix = "",
): string {
  return Number.isFinite(value)
    ? `${value!.toFixed(decimals)}${suffix}`
    : "--";
}

function formatCoordinate(value: number | undefined): string {
  return Number.isFinite(value) && value !== 0 ? value!.toFixed(7) : "--";
}

function formatDistance(value: number | undefined): string {
  if (!Number.isFinite(value)) return "--";
  if (value! >= 1000) return `${(value! / 1000).toFixed(2)} km`;
  return `${value!.toFixed(0)} m`;
}

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

function MetricCell({
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

function CopterTelemetryPanelInner({
  panelId,
  telemetry,
  mavlinkStatus,
}: CopterTelemetryPanelProps) {
  const agent = UAV_AGENT_BY_ID[panelId];
  const heading = telemetry?.heading_deg ?? telemetry?.yaw_deg;
  const isArmed = telemetry?.armed;
  const panelStyle = {
    "--agent-accent": agent.color,
    "--agent-accent-rgb": agent.colorRgb,
  } as CSSProperties;

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

  return (
    <section
      className="telem-panel copter-telemetry-panel"
      id={`telem-panel-${panelId}`}
      style={panelStyle}
      aria-labelledby={`copter-panel-title-${panelId}`}
    >

      <MavlinkHeader panelId={panelId} mavlinkStatus={mavlinkStatus} />

      <div className="copter-primary-data">
        <CopterCompass heading={heading} color={agent.color} />
        <div className="copter-primary-grid">
          <MetricCell label="MODE" value={telemetry?.flight_mode || "--"} accent />
          <MetricCell
            label="ARMED"
            value={isArmed === undefined ? "--" : isArmed ? "ARMED" : "DISARMED"}
            state={isArmed === undefined ? undefined : isArmed ? "armed" : "disarmed"}
          />
          <MetricCell label="BATTERY" value={battery} />
          <MetricCell label="WP" value={waypoint} accent />
        </div>
      </div>

      <div className="copter-metrics-grid">
        <MetricCell label="ALT AGL" value={formatNumber(telemetry?.relative_alt_m, 1, " m")} />
        <MetricCell label="ALT MSL" value={formatNumber(telemetry?.altitude_m, 1, " m")} />
        <MetricCell label="SPD" value={formatNumber(telemetry?.ground_speed_ms, 1, " m/s")} />
        <MetricCell label="VSPD" value={formatNumber(telemetry?.climb_rate_ms, 1, " m/s")} />
        <MetricCell
          label="HDG"
          value={heading === undefined ? "--" : `${Math.round(heading)}\u00b0`}
        />
        <MetricCell label="SAT" value={telemetry?.satellites_visible?.toString() ?? "--"} />
        <MetricCell label="HDOP" value={formatNumber(telemetry?.hdop, 2)} />
        <MetricCell label="WP DIST" value={formatDistance(telemetry?.distance_to_wp_m)} accent />
        <MetricCell label="HOME DIST" value={formatDistance(telemetry?.home_distance_m)} />
      </div>

      <div className="copter-coordinate-grid">
        <MetricCell label="LAT" value={formatCoordinate(telemetry?.lat)} />
        <MetricCell label="LON" value={formatCoordinate(telemetry?.lon)} />
        <MetricCell label="T-LAT" value={formatCoordinate(telemetry?.target_waypoint_lat)} accent />
        <MetricCell label="T-LON" value={formatCoordinate(telemetry?.target_waypoint_lon)} accent />
      </div>
    </section>
  );
}

export const CopterTelemetryPanel = memo(CopterTelemetryPanelInner);

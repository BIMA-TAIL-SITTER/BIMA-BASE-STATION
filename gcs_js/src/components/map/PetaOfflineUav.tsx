"use client";

import React, { useEffect, useState } from "react";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import {
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  Tooltip,
} from "react-leaflet";
import {
  COPTER_IDS,
  UAV_AGENTS,
  UAV_AGENT_BY_ID,
  UAV_IDS,
} from "@/config/agents";
import { getColoredIcon } from "@/lib/coloredSvgIcon";
import { AttitudeIndicator } from "@/components/telemetry/AttitudeIndicator";
import type { MavlinkStatus, UAVId, UAVRecord } from "@/types/telemetry";

export interface UAVMapTelemetry {
  id: UAVId;
  lat: number | null;
  lon: number | null;
  roll?: number;
  pitch?: number;
  heading: number;
  altitude: number;
  satellites?: number;
  hdop?: number;
  mode?: string;
  currentWaypoint?: number;
  totalWaypoints?: number;
  distanceToWaypoint?: number;
}

interface PetaOfflineUavProps {
  vehicles: UAVRecord<UAVMapTelemetry>;
  mavlinkStatuses: UAVRecord<MavlinkStatus>;
}

interface Waypoint {
  seq: number;
  command: number;
  lat: number;
  lon: number;
  alt: number;
}

const DEFAULT_LAT = -7.7956;
const DEFAULT_LON = 110.3695;
const DEFAULT_OFFSETS: UAVRecord<[number, number]> = {
  1: [0, 0],
  2: [0.003, 0.003],
  3: [-0.0025, 0.003],
  4: [0.0025, -0.003],
};
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function formatSatellites(value: number | undefined): string {
  return Number.isFinite(value) ? String(value) : "--";
}

function formatHdop(value: number | undefined): string {
  return Number.isFinite(value) ? value!.toFixed(2) : "--";
}

export default function PetaOfflineUav({
  vehicles,
  mavlinkStatuses,
}: PetaOfflineUavProps) {
  const [missions, setMissions] = useState<Partial<Record<UAVId, Waypoint[]>>>({});
  const [visibleMissions, setVisibleMissions] = useState<UAVRecord<boolean>>({
    1: false,
    2: false,
    3: false,
    4: false,
  });
  const [loadingMissions, setLoadingMissions] = useState<UAVRecord<boolean>>({
    1: false,
    2: false,
    3: false,
    4: false,
  });
  const [coloredCopterIcons, setColoredCopterIcons] = useState<
    Partial<Record<UAVId, string>>
  >({});

  useEffect(() => {
    let cancelled = false;
    Promise.all(
      COPTER_IDS.map(async (uavId) => {
        const agent = UAV_AGENT_BY_ID[uavId];
        const icon = await getColoredIcon(agent.iconPath, agent.color);
        return [uavId, icon] as const;
      }),
    )
      .then((entries) => {
        if (!cancelled) {
          setColoredCopterIcons(Object.fromEntries(entries));
        }
      })
      .catch((error) => console.error("[map] Failed to color copter icon:", error));

    return () => {
      cancelled = true;
    };
  }, []);

  const handleToggleMission = async (uavId: UAVId) => {
    if (visibleMissions[uavId]) {
      setVisibleMissions((current) => ({ ...current, [uavId]: false }));
      return;
    }

    setLoadingMissions((current) => ({ ...current, [uavId]: true }));
    try {
      const response = await fetch(`${API_BASE}/api/telemetry/mission/${uavId}`);
      const data = (await response.json()) as { waypoints?: Waypoint[] };
      const validWaypoints = (data.waypoints ?? []).filter(
        (waypoint) => waypoint.lat !== 0 && waypoint.lon !== 0,
      );
      setMissions((current) => ({ ...current, [uavId]: validWaypoints }));
      setVisibleMissions((current) => ({ ...current, [uavId]: true }));
    } catch (error) {
      console.error(`[map] Error reading UAV ${uavId} mission:`, error);
    } finally {
      setLoadingMissions((current) => ({ ...current, [uavId]: false }));
    }
  };

  const tileServerUrl = `${API_BASE}/api/peta/ubin/{z}/{x}/{y}.png`;

  const resolvedVehicles = UAV_IDS.map((uavId) => {
    const vehicle = vehicles[uavId];
    const [latOffset, lonOffset] = DEFAULT_OFFSETS[uavId];
    return {
      ...vehicle,
      lat: vehicle.lat ?? DEFAULT_LAT + latOffset,
      lon: vehicle.lon ?? DEFAULT_LON + lonOffset,
    };
  });

  const createVehicleIcon = (vehicle: UAVMapTelemetry, iconSource: string) => {
    const agent = UAV_AGENT_BY_ID[vehicle.id];
    const headingMarker = agent.type === "COPTER"
      ? `<span style="position:absolute;top:-4px;left:50%;width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-bottom:8px solid ${agent.color};transform:translateX(-50%);filter:drop-shadow(0 1px 2px rgba(0,0,0,.9));"></span>`
      : "";
    const html = `
      <div style="position:relative;transform:rotate(${vehicle.heading}deg);width:36px;height:36px;display:flex;align-items:center;justify-content:center;">
        ${headingMarker}
        <img alt="" src="${iconSource}" style="width:36px;height:36px;max-width:36px;max-height:36px;filter:drop-shadow(0 2px 4px rgba(0,0,0,.78));" />
      </div>
    `;

    return L.divIcon({
      className: "ikon-pesawat-kustom",
      html,
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    });
  };

  const createWaypointIcon = (sequence: number, color: string) => L.divIcon({
    className: "ikon-waypoint-kustom",
    html: `
      <div style="background:${color};color:#fff;border:2px solid rgba(0,0,0,0.3);border-radius:50%;width:18px;height:18px;display:flex;align-items:center;justify-content:center;font-family:var(--font-data);font-size:10px;font-weight:600;box-shadow:0 2px 4px rgba(0,0,0,.4);">
        ${sequence}
      </div>
    `,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });

  return (
    <div className="uav-map-shell">
      <MapContainer
        center={[resolvedVehicles[0].lat, resolvedVehicles[0].lon]}
        zoom={14}
        style={{ width: "100%", height: "100%" }}
        zoomControl={false}
      >
        <TileLayer
          url={tileServerUrl}
          maxZoom={19}
          attribution="Peta Offline MBTiles GCS"
        />

        {UAV_AGENTS.map((agent) => {
          const mission = missions[agent.id] ?? [];
          if (!visibleMissions[agent.id] || mission.length === 0) return null;
          return (
            <React.Fragment key={`mission-${agent.id}`}>
              {mission.map((waypoint, index) => (
                <Marker
                  key={`wp-uav-${agent.id}-${waypoint.seq}-${index}`}
                  position={[waypoint.lat, waypoint.lon]}
                  icon={createWaypointIcon(waypoint.seq, agent.color)}
                />
              ))}
              <Polyline
                positions={mission.map((waypoint) => [waypoint.lat, waypoint.lon])}
                pathOptions={{ color: agent.color, dashArray: "6, 4", weight: 2, opacity: 0.7 }}
              />
            </React.Fragment>
          );
        })}

        {resolvedVehicles.map((vehicle) => {
          const agent = UAV_AGENT_BY_ID[vehicle.id];
          const iconSource = agent.type === "COPTER"
            ? coloredCopterIcons[vehicle.id]
            : agent.iconPath;
          if (!iconSource) return null;

          return (
            <Marker
              key={`uav-marker-${vehicle.id}`}
              position={[vehicle.lat, vehicle.lon]}
              icon={createVehicleIcon(vehicle, iconSource)}
            >
              <Tooltip direction="top" offset={[0, -20]} className="uav-marker-tooltip">
                <strong style={{ color: agent.color }}>{agent.shortLabel}</strong>
                <span>{agent.type}</span>
                <span>MODE: {vehicle.mode || "--"}</span>
                <span>ALT: {Number.isFinite(vehicle.altitude) ? `${vehicle.altitude.toFixed(1)} m` : "--"}</span>
              </Tooltip>
            </Marker>
          );
        })}
      </MapContainer>

      {/* Top-left overlay: UAV 01 */}
      <div
        className="map-uav-overlay map-uav-overlay-top-left"
        style={{
          "--agent-color": UAV_AGENT_BY_ID[1].color,
          "--agent-color-rgb": UAV_AGENT_BY_ID[1].colorRgb,
        } as React.CSSProperties}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          <strong>UAV 01 GPS DATA</strong>
          <span>SAT: {formatSatellites(vehicles[1].satellites)}</span>
          <span>HDOP: {formatHdop(vehicles[1].hdop)}</span>
        </div>
        <div style={{ transform: "scale(0.6)", transformOrigin: "top left" }}>
          <AttitudeIndicator
            roll={vehicles[1].roll ?? 0}
            pitch={vehicles[1].pitch ?? 0}
            heading={vehicles[1].heading}
            altitude={vehicles[1].altitude}
            panelId={1}
          />
        </div>
      </div>

      {/* Bottom-left overlay: UAV 02 */}
      <div
        className="map-uav-overlay map-uav-overlay-bottom-left"
        style={{
          "--agent-color": UAV_AGENT_BY_ID[2].color,
          "--agent-color-rgb": UAV_AGENT_BY_ID[2].colorRgb,
        } as React.CSSProperties}
      >
        <div style={{ transform: "scale(0.6)", transformOrigin: "bottom left" }}>
          <AttitudeIndicator
            roll={vehicles[2].roll ?? 0}
            pitch={vehicles[2].pitch ?? 0}
            heading={vehicles[2].heading}
            altitude={vehicles[2].altitude}
            panelId={2}
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
          <strong>UAV 02 GPS DATA</strong>
          <span>SAT: {formatSatellites(vehicles[2].satellites)}</span>
          <span>HDOP: {formatHdop(vehicles[2].hdop)}</span>
        </div>
      </div>

      {/* Top-right overlay: UAV 03 */}
      <div
        className="map-uav-overlay map-uav-overlay-top-right"
        style={{
          "--agent-color": UAV_AGENT_BY_ID[3].color,
          "--agent-color-rgb": UAV_AGENT_BY_ID[3].colorRgb,
        } as React.CSSProperties}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "4px", alignItems: "flex-end", textAlign: "right" }}>
          <strong>UAV 03 GPS DATA</strong>
          <span>SAT: {formatSatellites(vehicles[3].satellites)}</span>
          <span>HDOP: {formatHdop(vehicles[3].hdop)}</span>
        </div>
        <div style={{ transform: "scale(0.6)", transformOrigin: "top right" }}>
          <AttitudeIndicator
            roll={vehicles[3].roll ?? 0}
            pitch={vehicles[3].pitch ?? 0}
            heading={vehicles[3].heading}
            altitude={vehicles[3].altitude}
            panelId={3}
          />
        </div>
      </div>

      {/* Bottom-right overlay: UAV 04 */}
      <div
        className="map-uav-overlay map-uav-overlay-bottom-right"
        style={{
          "--agent-color": UAV_AGENT_BY_ID[4].color,
          "--agent-color-rgb": UAV_AGENT_BY_ID[4].colorRgb,
        } as React.CSSProperties}
      >
        <div style={{ transform: "scale(0.6)", transformOrigin: "bottom right" }}>
          <AttitudeIndicator
            roll={vehicles[4].roll ?? 0}
            pitch={vehicles[4].pitch ?? 0}
            heading={vehicles[4].heading}
            altitude={vehicles[4].altitude}
            panelId={4}
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: "4px", alignItems: "flex-end", textAlign: "right" }}>
          <strong>UAV 04 GPS DATA</strong>
          <span>SAT: {formatSatellites(vehicles[4].satellites)}</span>
          <span>HDOP: {formatHdop(vehicles[4].hdop)}</span>
        </div>
      </div>

      <div className="map-offline-status">
        <span aria-hidden="true" />
        MAP SOURCE / LOCAL TILES
      </div>

      <div className="map-mission-controls">
        {UAV_AGENTS.map((agent) => (
          mavlinkStatuses[agent.id] !== "DISCONNECTED" && (
            <button
              key={agent.id}
              onClick={() => handleToggleMission(agent.id)}
              style={{
                "--mission-color": agent.color,
                "--mission-color-rgb": agent.colorRgb,
              } as React.CSSProperties}
            >
              {loadingMissions[agent.id]
                ? `UAV ${agent.id} READING`
                : visibleMissions[agent.id]
                  ? `UAV ${agent.id} HIDE`
                  : `UAV ${agent.id} MISSION`}
            </button>
          )
        ))}
      </div>
    </div>
  );
}

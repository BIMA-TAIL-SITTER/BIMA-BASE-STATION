/** Interactive offline mini-map for mission coordinates and route preview. */

"use client";

import { useEffect } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { CONTROL_API_BASE } from "@/lib/controlApi";
import type { MissionItem } from "@/types/control";

const DEFAULT_CENTER: [number, number] = [-7.7956, 110.3695];

interface MissionMapProps {
  waypoints: MissionItem[];
  color: string;
  onCoordinatePick: (lat: number, lon: number) => void;
}

function MapClickHandler({
  onCoordinatePick,
}: Pick<MissionMapProps, "onCoordinatePick">) {
  useMapEvents({
    click(event) {
      onCoordinatePick(event.latlng.lat, event.latlng.lng);
    },
  });
  return null;
}

function MapViewport({ waypoints }: { waypoints: MissionItem[] }) {
  const map = useMap();

  useEffect(() => {
    const valid = waypoints.filter(
      (waypoint) =>
        Number.isFinite(waypoint.lat) && Number.isFinite(waypoint.lon),
    );
    if (valid.length === 1) {
      map.setView([valid[0].lat, valid[0].lon], 15);
    } else if (valid.length > 1) {
      map.fitBounds(
        valid.map((waypoint) => [waypoint.lat, waypoint.lon]),
        { padding: [24, 24], maxZoom: 16 },
      );
    }
  }, [map, waypoints]);

  return null;
}

function MapResizeHandler() {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    const resizeObserver = new ResizeObserver(() => {
      map.invalidateSize({
        debounceMoveend: true,
        pan: false,
      });
    });

    resizeObserver.observe(container);
    map.invalidateSize({
      debounceMoveend: true,
      pan: false,
    });

    return () => resizeObserver.disconnect();
  }, [map]);

  return null;
}

function createWaypointIcon(sequence: number, color: string, current: boolean) {
  return L.divIcon({
    className: "mission-waypoint-marker",
    html: `<span style="--waypoint-color:${color}" class="${
      current ? "is-current" : ""
    }">${sequence}</span>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

export default function MissionMap({
  waypoints,
  color,
  onCoordinatePick,
}: MissionMapProps) {
  const validWaypoints = waypoints.filter(
    (waypoint) =>
      Number.isFinite(waypoint.lat) && Number.isFinite(waypoint.lon),
  );
  const center: [number, number] = validWaypoints.length
    ? [validWaypoints[0].lat, validWaypoints[0].lon]
    : DEFAULT_CENTER;

  return (
    <div className="mission-map-shell">
      <MapContainer
        center={center}
        zoom={14}
        zoomControl
        style={{ width: "100%", height: "100%" }}
      >
        <TileLayer
          url={`${CONTROL_API_BASE}/api/peta/ubin/{z}/{x}/{y}.png`}
          maxZoom={19}
          attribution="Peta Offline MBTiles GCS"
        />
        <MapClickHandler onCoordinatePick={onCoordinatePick} />
        <MapViewport waypoints={validWaypoints} />
        <MapResizeHandler />
        {validWaypoints.length > 1 && (
          <Polyline
            positions={validWaypoints.map((waypoint) => [
              waypoint.lat,
              waypoint.lon,
            ])}
            pathOptions={{ color, weight: 2, dashArray: "6, 5" }}
          />
        )}
        {validWaypoints.map((waypoint) => (
          <Marker
            key={`${waypoint.seq}-${waypoint.lat}-${waypoint.lon}`}
            position={[waypoint.lat, waypoint.lon]}
            icon={createWaypointIcon(
              waypoint.seq,
              color,
              waypoint.current,
            )}
          />
        ))}
      </MapContainer>
      <div className="mission-map-hint">
        CLICK MAP TO ADD WAYPOINT
      </div>
    </div>
  );
}

"use client";

import { useEffect, useRef, useState } from "react";
import { MapContainer, TileLayer, FeatureGroup, Polyline, Marker, Tooltip, useMap } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "@geoman-io/leaflet-geoman-free/dist/leaflet-geoman.css";
import L from "leaflet";
import "@geoman-io/leaflet-geoman-free";
import { COPTER_IDS, UAV_AGENT_BY_ID } from "@/config/agents";
import { getColoredIcon } from "@/lib/coloredSvgIcon";
import type { UAVId } from "@/types/telemetry";

export interface SwarmVehicleMarker {
  id: UAVId;
  lat: number;
  lon: number;
  heading: number;
  altitude: number;
  mode?: string;
}

interface SwarmSurveyMapProps {
  onPolygonCreated: (vertices: number[][]) => void;
  onPolygonEdited: (vertices: number[][]) => void;
  onPolygonDeleted: () => void;
  uav3Path?: number[][];
  uav4Path?: number[][];
  vehicles?: SwarmVehicleMarker[];
}

function GeomanControls({ onPolygonCreated, onPolygonEdited, onPolygonDeleted }: Pick<SwarmSurveyMapProps, "onPolygonCreated" | "onPolygonEdited" | "onPolygonDeleted">) {
  const map = useMap();
  const fgRef = useRef<L.FeatureGroup>(null);

  useEffect(() => {
    if (!map) return;

    map.pm.addControls({
      position: "topleft",
      drawMarker: false,
      drawCircleMarker: false,
      drawPolyline: false,
      drawRectangle: true,
      drawPolygon: true,
      drawCircle: false,
      drawText: false,
      editMode: true,
      dragMode: true,
      cutPolygon: false,
      removalMode: true,
    });

    map.pm.setGlobalOptions({
      allowSelfIntersection: false,
      snappable: true,
      layerGroup: map,
    });

    map.on("pm:create", (e) => {
      const layer = e.layer;
      
      // Allow only one polygon
      map.eachLayer((l) => {
        if (l instanceof L.Polygon && l !== layer) {
          map.removeLayer(l);
        }
      });

      const getCoords = (l: any) => {
        const latlngs = l.getLatLngs()[0];
        return latlngs.map((ll: L.LatLng) => [ll.lat, ll.lng]);
      };

      onPolygonCreated(getCoords(layer));

      layer.on("pm:edit", (evt) => {
        onPolygonEdited(getCoords(evt.layer));
      });
      layer.on("pm:dragend", (evt) => {
        onPolygonEdited(getCoords(evt.layer));
      });
    });

    map.on("pm:remove", (e) => {
      onPolygonDeleted();
    });

    return () => {
      map.pm.removeControls();
      map.off("pm:create");
      map.off("pm:remove");
    };
  }, [map, onPolygonCreated, onPolygonEdited, onPolygonDeleted]);

  return <FeatureGroup ref={fgRef} />;
}

function createVehicleIcon(heading: number, iconSource: string, color: string): L.DivIcon {
  const html = `
    <div style="position:relative;transform:rotate(${heading}deg);width:40px;height:40px;display:flex;align-items:center;justify-content:center;">
      <span style="position:absolute;top:-5px;left:50%;width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent;border-bottom:10px solid ${color};transform:translateX(-50%);filter:drop-shadow(0 1px 3px rgba(0,0,0,.9));"></span>
      <img alt="" src="${iconSource}" style="width:40px;height:40px;max-width:40px;max-height:40px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.85));" />
    </div>
  `;
  return L.divIcon({
    className: "swarm-vehicle-icon",
    html,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  });
}

export function SwarmSurveyMap({ onPolygonCreated, onPolygonEdited, onPolygonDeleted, uav3Path, uav4Path, vehicles }: SwarmSurveyMapProps) {
  // Center roughly at UGM or fallback coordinates
  const center: [number, number] = [-7.77126, 110.37765];

  // Load colored copter icons
  const [coloredIcons, setColoredIcons] = useState<Partial<Record<UAVId, string>>>({});

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
          setColoredIcons(Object.fromEntries(entries));
        }
      })
      .catch((error) => console.error("[SwarmSurveyMap] Failed to color copter icon:", error));

    return () => { cancelled = true; };
  }, []);

  return (
    <div style={{ height: "550px", width: "100%", borderRadius: "8px", overflow: "hidden", border: "1px solid #4b5563" }}>
      <MapContainer center={center} zoom={18} maxZoom={24} style={{ height: "100%", width: "100%" }}>
        <TileLayer
          url="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
          maxZoom={24}
          maxNativeZoom={20}
          attribution="&copy; Google Satellite"
        />
        <GeomanControls 
          onPolygonCreated={onPolygonCreated} 
          onPolygonEdited={onPolygonEdited} 
          onPolygonDeleted={onPolygonDeleted} 
        />
        
        {uav3Path && uav3Path.length > 0 && (
          <Polyline positions={uav3Path as [number, number][]} color="#f97316" weight={3} />
        )}
        
        {uav4Path && uav4Path.length > 0 && (
          <Polyline positions={uav4Path as [number, number][]} color="#ec4899" weight={3} />
        )}

        {/* UAV Vehicle Markers */}
        {vehicles && vehicles.map((vehicle) => {
          const agent = UAV_AGENT_BY_ID[vehicle.id];
          const iconSource = coloredIcons[vehicle.id];
          if (!iconSource) return null;

          return (
            <Marker
              key={`swarm-uav-${vehicle.id}`}
              position={[vehicle.lat, vehicle.lon]}
              icon={createVehicleIcon(vehicle.heading, iconSource, agent.color)}
            >
              <Tooltip direction="top" offset={[0, -24]} className="uav-marker-tooltip">
                <strong style={{ color: agent.color }}>{agent.shortLabel}</strong>
                <span>MODE: {vehicle.mode || "--"}</span>
                <span>ALT: {Number.isFinite(vehicle.altitude) ? `${vehicle.altitude.toFixed(1)} m` : "--"}</span>
                <span>HDG: {Number.isFinite(vehicle.heading) ? `${vehicle.heading.toFixed(0)}°` : "--"}</span>
              </Tooltip>
            </Marker>
          );
        })}
      </MapContainer>
    </div>
  );
}


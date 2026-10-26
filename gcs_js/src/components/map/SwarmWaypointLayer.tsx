"use client";

import { useState } from "react";
import L from "leaflet";
import { Circle, Marker, Polyline, Popup, Tooltip, useMapEvents } from "react-leaflet";
import { useSwarmMission } from "@/components/swarm/SwarmMissionContext";
import { UAV_AGENT_BY_ID } from "@/config/agents";

const COLORS: Record<string, string> = { DRAFT: "#94a3b8", PENDING: "#fbbf24", ASSIGNED: "#38bdf8", ACKED: "#38bdf8", EN_ROUTE: "#38bdf8", HELD: "#fbbf24", REACHED: "#34d399", FAILED: "#fb7185", UNKNOWN: "#fb7185", CANCELLED: "#64748b" };

export function SwarmWaypointLayer() {
  const mission = useSwarmMission();
  const [point, setPoint] = useState<L.LatLng | null>(null);
  const [altitude, setAltitude] = useState(10);
  const map = useMapEvents({
    contextmenu(event) {
      const target = event.originalEvent.target;
      if (target instanceof Element && target.closest(".leaflet-control, .leaflet-popup, .leaflet-marker-icon")) return;
      setAltitude(mission.altitude);
      setPoint(event.latlng);
    },
    click(event) {
      // While picking a geofence center, a left-click sets it instead of dismissing the popup.
      if (mission.geoPicking) {
        mission.setGeoDraft({ lat: event.latlng.lat.toFixed(7), lon: event.latlng.lng.toFixed(7) });
        mission.setGeoPicking(false);
        return;
      }
      setPoint(null);
    },
  });
  const safety = mission.state?.safety;
  const [gLat, gLon, gRad] = [Number(mission.geoDraft.lat), Number(mission.geoDraft.lon), Number(mission.geoDraft.radius)];
  const draftValid = [gLat, gLon, gRad].every(Number.isFinite) && Math.abs(gLat) <= 90 && Math.abs(gLon) <= 180 && gRad > 0;
  const geofence = draftValid ? { lat: gLat, lon: gLon, radius: gRad, pending: true }
    : typeof safety?.center_lat === "number" && typeof safety?.center_lon === "number"
      ? { lat: safety.center_lat, lon: safety.center_lon, radius: safety.radius_m, pending: false } : null;
  return <>
    {geofence && <Circle center={[geofence.lat, geofence.lon]} radius={geofence.radius}
      pathOptions={{ color: geofence.pending ? "#fbbf24" : "#38bdf8", weight: 1.5, dashArray: "6,6", fillOpacity: 0.05 }} />}
    {point && <Popup className="swarm-waypoint-popup" key={`${point.lat}-${point.lng}`} position={point} eventHandlers={{ remove: () => setPoint(null) }}>
      <form className="swarm-map-menu" onSubmit={async event => {
        event.preventDefault();
        if (!mission.canAdd || !await mission.add(point.lat, point.lng, altitude)) return;
        setPoint(null);
        map.closePopup();
      }}>
        <strong>{mission.locked ? "Tambah WP saat misi berjalan" : "Add Waypoint Here"}</strong>
        {mission.locked && <span>WP baru masuk antrean setelah diakui kedua UAV. WP lama tetap terkunci.</span>}
        <span>Lat {point.lat.toFixed(7)}</span><span>Lon {point.lng.toFixed(7)}</span>
        <label>Altitude (m, relative home)<input type="number" required step="0.5" min={mission.state?.safety.min_alt_m ?? 1}
          max={mission.state?.safety.max_alt_m ?? 500} value={altitude} disabled={!mission.canAdd} onChange={e => setAltitude(Number(e.target.value))} /></label>
        {!mission.canAdd && <span>{mission.busy || mission.state?.busy ? "Menunggu sinkronisasi…"
          : !mission.token && mission.locked ? "Isi token operator di Pengaturan lanjutan."
          : "Penambahan tersedia saat Aktif/Ditahan, kedua companion mendukungnya, dan total WP kurang dari 200."}</span>}
        {mission.error && <span role="alert">{mission.error}</span>}
        <button type="submit" disabled={!mission.canAdd}>{mission.busy ? "Mengirim…" : mission.locked ? "Tambah ke misi aktif" : "Add Waypoint Here"}</button>
      </form>
    </Popup>}
    {mission.draft.map(wp => {
      const task = !mission.dirty ? mission.state?.tasks.find(t => t.task_id === wp.task_id) : undefined;
      const status = task?.status ?? (mission.state?.append_pending?.waypoints.some(item => item.task_id === wp.task_id) ? "SYNCING" : "DRAFT");
      const owner = task?.owner_drone_id;
      const drone = owner ? mission.state?.drones.find(d => d.drone_id === owner) : undefined;
      const drawLine = owner && drone?.connected && mission.connected && (drone.position_age_s ?? Infinity) <= 2
        && drone.lat != null && drone.lon != null && ["ASSIGNED", "ACKED", "EN_ROUTE", "HELD", "UNKNOWN"].includes(status);
      return <Marker key={wp.task_id} position={[wp.lat, wp.lon]} draggable={!mission.locked}
        icon={L.divIcon({ className: "swarm-waypoint-icon", iconSize: [32, 32], iconAnchor: [16, 16],
          html: `<span style="--waypoint-color:${COLORS[status] ?? COLORS.DRAFT}">${String(wp.sequence).padStart(2, "0")}</span>` })}
        eventHandlers={{
          click() { mission.select(wp.task_id); },
          dragend(event) {
            const position = (event.target as L.Marker).getLatLng();
            mission.edit(mission.draft.map(item => item.task_id === wp.task_id ? { ...item, lat: position.lat, lon: position.lng } : item));
          },
        }}>
        <Tooltip>WP-{String(wp.sequence).padStart(2, "0")} · {status}<br />{wp.lat.toFixed(7)}, {wp.lon.toFixed(7)} · {wp.alt_m} m<br />{owner ? `Assigned: UAV-${owner}` : "Pending"}</Tooltip>
        {drawLine && <Polyline positions={[[drone.lat!, drone.lon!], [wp.lat, wp.lon]]}
          pathOptions={{ color: UAV_AGENT_BY_ID[owner].color, weight: 2, dashArray: status === "UNKNOWN" ? "2,6" : "8,4" }} />}
      </Marker>;
    })}
  </>;
}

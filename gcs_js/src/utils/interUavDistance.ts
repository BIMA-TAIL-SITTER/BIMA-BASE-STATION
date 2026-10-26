import type { MavlinkStatus, TelemetryData } from "@/types/telemetry";

type Position = TelemetryData & { lat: number; lon: number; altitude_m: number };

function hasValidPosition(packet: TelemetryData | null): packet is Position {
  return packet !== null
    && typeof packet.lat === "number" && Number.isFinite(packet.lat) && Math.abs(packet.lat) <= 90
    && typeof packet.lon === "number" && Number.isFinite(packet.lon) && Math.abs(packet.lon) <= 180
    && typeof packet.altitude_m === "number" && Number.isFinite(packet.altitude_m)
    && (packet.gps_fix === undefined || (Number.isFinite(packet.gps_fix) && packet.gps_fix >= 3));
}

/** Current 3D separation from GPS and a shared MSL altitude reference, in meters. */
export function getInterUavDistance(
  first: TelemetryData | null,
  second: TelemetryData | null,
  firstStatus: MavlinkStatus,
  secondStatus: MavlinkStatus,
): number | null {
  // Dashboard link statuses expire after telemetry stops; never reuse cached APF distances.
  if (firstStatus === "DISCONNECTED" || secondStatus === "DISCONNECTED"
    || !hasValidPosition(first) || !hasValidPosition(second)) return null;

  const radians = Math.PI / 180;
  const deltaLat = (second.lat - first.lat) * radians;
  const deltaLon = (second.lon - first.lon) * radians;
  const haversine = Math.sin(deltaLat / 2) ** 2
    + Math.cos(first.lat * radians) * Math.cos(second.lat * radians)
    * Math.sin(deltaLon / 2) ** 2;
  const clamped = Math.min(1, Math.max(0, haversine));
  const horizontal = 6371000 * 2 * Math.atan2(Math.sqrt(clamped), Math.sqrt(1 - clamped));

  return Math.hypot(horizontal, second.altitude_m - first.altitude_m);
}

/** Telemetry data received from the MAVLink WebSocket (/ws/telemetry) */
export interface TelemetryData {
  slot: UAVId;
  timestamp?: number;
  vehicle_id?: number;
  vehicle_name?: string;
  lat?: number;
  lon?: number;
  altitude_m?: number;
  relative_alt_m?: number;
  ground_speed_ms?: number;
  air_speed_ms?: number;
  climb_rate_ms?: number;
  heading_deg?: number;
  roll_deg?: number;
  pitch_deg?: number;
  yaw_deg?: number;
  satellites_visible?: number;
  hdop?: number;
  flight_mode?: string;
  mission_state?: string;
  current_waypoint?: number;
  total_waypoints?: number;
  distance_to_wp_m?: number;
  target_waypoint_lat?: number;
  target_waypoint_lon?: number;
  home_distance_m?: number;
  battery_voltage?: number;
  battery_current?: number;
  battery_remaining_pct?: number;
  armed?: boolean;
  [key: string]: any; // Allow arbitrary raw mavlink fields
}

/** UDP JSON telemetry from the UAV detection pipeline */
export interface UDPTelemetry {
  type: "telemetry";
  timestamp: number;
  fps_inference: number;
  detection: boolean;
  conf?: number;
  frame_size?: [number, number];
  camera_fov?: [number, number];
  lokasi_uav?: {
    lat: number;
    lon: number;
    alt_m: number;
    heading_deg: number;
  };
  lokasi_target?: {
    lat: number;
    lon: number;
    dx_east_m: number;
    dy_north_m: number;
    distance_m: number;
    offset_px: [number, number];
    gsd_x: number;
    gsd_y: number;
  };
  lokasi_deteksi_px?: [number, number];
  bbox_px?: [number, number, number, number];
}

/** Server configuration fetched from /api/config */
export interface GCSConfig {
  ws_host: string;
  tailscale_ip: string;
  yolo_enabled: boolean;
  web_port: number;
}

/** UAV connection setup from the modal */
export interface UAVConnectionConfig {
  streamPort: string;
  tcpIp: string;
  mavlinkPort: string;
  jsonPort: string;
  missionUdpPort: string;   // Port UDP untuk mission protocol GCS↔Raspi
  raspiIp: string;          // IP Raspi (Tailscale) untuk mission upload (udpout)
}

/** Mavlink connection status */
export type MavlinkStatus = "DISCONNECTED" | "ARMED" | "DISARMED";

/** Theme mode */
export type ThemeMode = "dark" | "light";

/** Supported vehicle slots. */
export type UAVId = 1 | 2 | 3 | 4;

/** Vehicle type shown across settings, panels, and map tooltips. */
export type UAVType = "FIXED WING" | "COPTER";

/** Per-slot collection helper. */
export type UAVRecord<T> = Record<UAVId, T>;

/** Custom metric configuration for dynamic grid */
export interface MetricConfig {
  id: string; // Unique ID (e.g. uuid or timestamp) for React keys
  telemetryKey: string;
  label: string;
  format: "number" | "coordinate" | "distance" | "degrees" | "string";
  decimals?: number;
  suffix?: string;
  accent?: boolean;
}

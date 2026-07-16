/** Telemetry data received from the MAVLink WebSocket (/ws/telemetry) */
export interface TelemetryData {
  slot: 1 | 2;
  lat?: number;
  lon?: number;
  altitude_m?: number;
  ground_speed_ms?: number;
  heading_deg?: number;
  roll_deg?: number;
  pitch_deg?: number;
  yaw_deg?: number;
  satellites_visible?: number;
  hdop?: number;
  current_waypoint?: number;
  battery_voltage?: number;
  armed?: boolean;
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
}

/** Mavlink connection status */
export type MavlinkStatus = "DISCONNECTED" | "ARMED" | "DISARMED";

/** Theme mode */
export type ThemeMode = "dark" | "light";

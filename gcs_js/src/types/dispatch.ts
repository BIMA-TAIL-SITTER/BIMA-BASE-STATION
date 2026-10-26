export interface DraftWaypoint {
  task_id: string;
  sequence: number;
  lat: number;
  lon: number;
  alt_m: number;
}

export interface DispatchTask extends DraftWaypoint {
  status: string;
  owner_drone_id: 3 | 4 | null;
  assignment_version: number;
  command_id?: string;
  distance_at_assignment_m?: number;
  reason?: string;
}

export interface DispatchDrone {
  drone_id: 3 | 4;
  connected: boolean;
  capabilities?: string[];
  phase?: string;
  mode?: string;
  armed?: boolean;
  gps_fix?: number;
  battery_pct?: number;
  lat?: number;
  lon?: number;
  alt_m?: number;
  alt_msl_m?: number;
  heading_deg?: number;
  distance_to_target_m?: number | null;
  position_age_s?: number | null;
  heartbeat_age_s?: number | null;
  error?: string;
  safety_hash?: string;
  apf?: { active: boolean; d_ij: number; d_cpa: number; t_cpa: number; offset_m: number } | null;
}

export interface SwarmSafety {
  center_lat: number | null;
  center_lon: number | null;
  radius_m: number;
  min_alt_m: number;
  max_alt_m: number;
  takeoff_alt_m: number;
  min_battery_pct: number;
  min_separation_m: number;
  apf: Record<string, number>;
}

export interface DispatchPlan {
  mission_id: string;
  version: number;
  coordinate_frame: "GLOBAL_RELATIVE_ALT";
  waypoints: DraftWaypoint[];
  endpoints: Record<string, { host: string; port: number }>;
}

export interface DispatchState {
  phase: string;
  plan: Partial<DispatchPlan>;
  tasks: DispatchTask[];
  drones: DispatchDrone[];
  upload: Record<string, string>;
  commands: Record<string, { status: string; operation: string; error?: string; latency_ms?: number }>;
  events: { id: number; at: number; type: string; drone_id?: number; reason?: string; error?: string }[];
  error: string;
  blockers: string[];
  ready_to_start: boolean;
  busy: boolean;
  edit_locked: boolean;
  append_allowed?: boolean;
  append_pending?: { base_version: number; base_hash: string; waypoints: DraftWaypoint[] };
  end_action: string;
  safety: SwarmSafety;
  safety_hash?: string | null;
}

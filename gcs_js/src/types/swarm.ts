/** Swarm orchestration types matching the backend schemas. */

import type { MissionItem } from "@/types/control";

// ─── Enums ────────────────────────────────────────────────────────

export type SwarmPhase =
  | "IDLE"
  | "VALIDATING"
  | "UPLOADING"
  | "VERIFYING"
  | "READY_TO_START"
  | "STARTING"
  | "ARMING"
  | "TAKEOFF"
  | "HOVER_STABILIZING"
  | "AUTO_RUNNING"
  | "COMPLETED"
  | "PARTIAL_UPLOAD"
  | "DEGRADED"
  | "ABORTING"
  | "FAILED";

export type PerUAVUploadStatus =
  | "PENDING"
  | "UPLOADING"
  | "ACCEPTED"
  | "REJECTED"
  | "TIMEOUT"
  | "ERROR";

export type PerUAVFlightPhase =
  | "IDLE"
  | "PRECHECK"
  | "ARMING"
  | "TAKEOFF"
  | "HOVER_STABILIZING"
  | "AUTO_RUNNING"
  | "COMPLETED"
  | "ABORTED"
  | "FAILED";

// ─── Request / Response ──────────────────────────────────────────

export interface MissionBatchUploadRequest {
  mission_uav_3: MissionItem[];
  mission_uav_4: MissionItem[];
}

export interface PerUAVUploadResult {
  slot: number;
  status: PerUAVUploadStatus;
  total: number;
  sent: number;
  result_code?: number | null;
  result_label: string;
  message: string;
}

export interface MissionBatchUploadResponse {
  phase: SwarmPhase;
  uav_3: PerUAVUploadResult;
  uav_4: PerUAVUploadResult;
  ready_to_start: boolean;
  message: string;
}

export interface SwarmStartRequest {
  confirmation: string;
  ip_3?: string;
  port_3?: number;
  ip_4?: string;
  port_4?: number;
}

export interface SwarmStartResponse {
  phase: SwarmPhase;
  accepted: boolean;
  message: string;
  uav_3_phase: PerUAVFlightPhase;
  uav_4_phase: PerUAVFlightPhase;
}

export interface SwarmAbortRequest {
  reason: string;
}

export interface SwarmAbortResponse {
  phase: SwarmPhase;
  message: string;
  uav_3_action: string;
  uav_4_action: string;
}

// ─── Status ──────────────────────────────────────────────────────

export interface APFStatus {
  active: boolean;
  d_ij: number;
  d_cpa: number;
  t_cpa: number;
  uav_3_offset_m: number;
  uav_4_offset_m: number;
  uav_3_avoidance_active: boolean;
  uav_4_avoidance_active: boolean;
  stale: boolean;
  warning: string;
}

export interface SwarmStatusResponse {
  phase: SwarmPhase;
  uav_3_upload: PerUAVUploadStatus;
  uav_4_upload: PerUAVUploadStatus;
  uav_3_flight: PerUAVFlightPhase;
  uav_4_flight: PerUAVFlightPhase;
  ready_to_start: boolean;
  apf: APFStatus;
  interlocks_passed: boolean;
  interlock_failures: string[];
  message: string;
}

// ─── WebSocket Events ────────────────────────────────────────────

export interface SwarmAPFStatusEvent {
  type: "swarm_apf_status";
  d_ij: number;
  d_cpa: number;
  t_cpa: number;
  uav_3_avoidance: boolean;
  uav_4_avoidance: boolean;
  uav_3_offset_m: number;
  uav_4_offset_m: number;
  stale: boolean;
}

export interface SwarmStatusEvent extends SwarmStatusResponse {
  type: "swarm_status";
}

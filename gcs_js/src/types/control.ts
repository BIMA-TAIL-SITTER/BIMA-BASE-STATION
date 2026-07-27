/** Mission, parameter, and future flight-control API contracts. */

import type { UAVId } from "@/types/telemetry";

export type ControlCommand =
  | "ARM"
  | "DISARM"
  | "SET_MODE"
  | "RTL"
  | "TAKEOFF"
  | "GOTO"
  | "MISSION_UPLOAD";

export interface ArmDisarmRequest {
  force?: boolean;
}

export interface ModeChangeRequest {
  mode: string;
}

export interface GotoRequest {
  latitude_deg: number;
  longitude_deg: number;
  altitude_m: number;
}

export interface TakeoffRequest {
  altitude_m: number;
}

export interface MissionItem {
  seq: number;
  command: number;
  command_name?: string | null;
  frame: number;
  frame_name?: string | null;
  lat: number;
  lon: number;
  alt: number;
  param1: number;
  param2: number;
  param3: number;
  param4: number;
  current: boolean;
  autocontinue: boolean;
}

export interface MissionUploadRequest {
  items: MissionItem[];
}

export interface MissionUploadResponse {
  slot: UAVId;
  success: boolean;
  total: number;
  sent: number;
  result_code?: number | null;
  result_label: string;
  message: string;
}

export interface CommandAckResponse {
  slot: UAVId;
  command_id: number;
  result_code: number;
  result_label: string;
  accepted: boolean;
  message?: string | null;
}

export interface ParamValue {
  param_id: string;
  type: number;
  type_name: string;
  value: number;
  index: number;
  count: number;
}

export type ParamFetchStatus =
  | "idle"
  | "fetching"
  | "retrying"
  | "complete"
  | "incomplete"
  | "error";

export interface ParamFetchProgress {
  slot: UAVId;
  status: ParamFetchStatus;
  received: number;
  total: number;
  missing_indices: number[];
  parameter?: ParamValue | null;
  message?: string | null;
}

export interface ParamSnapshot extends ParamFetchProgress {
  parameters: ParamValue[];
}

export interface ParamSetRequest {
  value: number;
  param_type?: number;
}

export interface ParamSetResponse {
  slot: UAVId;
  success: boolean;
  param_id: string;
  old_value?: number | null;
  requested_value: number;
  confirmed_value?: number | null;
  type: number;
  type_name: string;
  message: string;
}

export interface MissionUploadProgressEvent {
  type: "mission_upload_progress";
  slot: UAVId;
  status: "starting" | "sending" | "complete" | "error";
  sent: number;
  total: number;
  message: string;
  result_code?: number | null;
  result_label?: string | null;
}

export interface MissionDownloadProgressEvent {
  type: "mission_download_progress";
  slot?: UAVId;
  status: "requesting" | "receiving" | "complete" | "error";
  received: number;
  total: number;
  message: string;
}

export interface ParamProgressEvent extends ParamFetchProgress {
  type: "param_fetch_progress" | "param_fetch_complete";
}

export interface ParamSnapshotEvent extends ParamSnapshot {
  type: "param_snapshot";
}

export interface ParamSetResultEvent extends Omit<ParamSetResponse, "type"> {
  type: "param_set_result";
  param_type: number;
}

export type ControlWebSocketEvent =
  | MissionUploadProgressEvent
  | MissionDownloadProgressEvent
  | ParamProgressEvent
  | ParamSnapshotEvent
  | ParamSetResultEvent;

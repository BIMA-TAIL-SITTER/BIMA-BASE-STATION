/**
 * Future per-slot flight-control hook.
 *
 * It exposes the intended action shape without API calls, local state, or ACK
 * subscription logic in the scaffolding task.
 */

"use client";

import type {
  ArmDisarmRequest,
  CommandAckResponse,
  GotoRequest,
  MissionUploadRequest,
  MissionUploadResponse,
  ModeChangeRequest,
  TakeoffRequest,
} from "@/types/control";
import type { UAVId } from "@/types/telemetry";
import {
  arm as armRequest,
  disarm as disarmRequest,
  setMode as setModeRequest,
  uploadMission as uploadMissionRequest,
} from "@/lib/controlApi";

export interface UavControlActions {
  arm: (request?: ArmDisarmRequest) => Promise<CommandAckResponse>;
  disarm: (request?: ArmDisarmRequest) => Promise<CommandAckResponse>;
  setMode: (request: ModeChangeRequest) => Promise<CommandAckResponse>;
  rtl: () => Promise<CommandAckResponse>;
  takeoff: (request: TakeoffRequest) => Promise<CommandAckResponse>;
  goto: (request: GotoRequest) => Promise<CommandAckResponse>;
  uploadMission: (
    request: MissionUploadRequest,
  ) => Promise<MissionUploadResponse>;
}

const TODO_MESSAGE = "TODO: implement in control feature task";

export function useUavControl(slot: UAVId): UavControlActions {
  return {
    arm: async (request?: ArmDisarmRequest) => {
      return armRequest(slot, request);
    },
    disarm: async (request?: ArmDisarmRequest) => {
      return disarmRequest(slot, request);
    },
    setMode: async (request: ModeChangeRequest) => {
      return setModeRequest(slot, request);
    },
    rtl: async () => {
      throw new Error(TODO_MESSAGE);
    },
    takeoff: async () => {
      throw new Error(TODO_MESSAGE);
    },
    goto: async () => {
      throw new Error(TODO_MESSAGE);
    },
    uploadMission: (request) => uploadMissionRequest(slot, request),
  };
}


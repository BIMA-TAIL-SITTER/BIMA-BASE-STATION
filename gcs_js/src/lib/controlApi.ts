/** REST and WebSocket URL helpers for mission and parameter control. */

import type {
  ArmDisarmRequest,
  CommandAckResponse,
  GotoRequest,
  MissionItem,
  MissionUploadRequest,
  MissionUploadResponse,
  ModeChangeRequest,
  ParamSetRequest,
  ParamSetResponse,
  ParamSnapshot,
  TakeoffRequest,
} from "@/types/control";
import type { UAVId } from "@/types/telemetry";

export const CONTROL_API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ControlApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ControlApiError";
    this.status = status;
  }
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${CONTROL_API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  const payload = (await response.json().catch(() => null)) as
    | { detail?: string; error?: string }
    | T
    | null;
  if (!response.ok) {
    const errorPayload = payload as { detail?: string; error?: string } | null;
    throw new ControlApiError(
      errorPayload?.detail
        || errorPayload?.error
        || `Control API request failed (${response.status})`,
      response.status,
    );
  }
  return payload as T;
}

export function getControlWebSocketUrl(slot: UAVId): string {
  const base = new URL(CONTROL_API_BASE);
  base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
  base.pathname = `/ws/control/${slot}`;
  base.search = "";
  base.hash = "";
  return base.toString();
}

export async function fetchMission(slot: UAVId): Promise<MissionItem[]> {
  const response = await requestJson<{
    waypoints: MissionItem[];
    error?: string;
  }>(`/api/telemetry/mission/${slot}`);
  if (response.error) {
    throw new ControlApiError(response.error, 502);
  }
  return response.waypoints;
}

export async function uploadMission(
  slot: UAVId,
  request: MissionUploadRequest,
): Promise<MissionUploadResponse> {
  return requestJson<MissionUploadResponse>(
    `/api/control/${slot}/mission/upload`,
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

export async function fetchParameterSnapshot(
  slot: UAVId,
): Promise<ParamSnapshot> {
  return requestJson<ParamSnapshot>(`/api/control/${slot}/params`);
}

export async function startParameterFetch(
  slot: UAVId,
): Promise<ParamSnapshot> {
  return requestJson<ParamSnapshot>(`/api/control/${slot}/params/fetch`, {
    method: "POST",
  });
}

export async function retryMissingParameters(
  slot: UAVId,
): Promise<ParamSnapshot> {
  return requestJson<ParamSnapshot>(
    `/api/control/${slot}/params/retry-missing`,
    { method: "POST" },
  );
}

export async function setParameter(
  slot: UAVId,
  paramId: string,
  request: ParamSetRequest,
): Promise<ParamSetResponse> {
  return requestJson<ParamSetResponse>(
    `/api/control/${slot}/params/${encodeURIComponent(paramId)}`,
    {
      method: "POST",
      body: JSON.stringify(request),
    },
  );
}

const TODO_MESSAGE = "TODO: implement in control feature task";

function notImplemented(): never {
  throw new Error(TODO_MESSAGE);
}

export async function arm(
  slot: UAVId,
  request: ArmDisarmRequest = {},
): Promise<CommandAckResponse> {
  void slot;
  void request;
  return notImplemented();
}

export async function disarm(
  slot: UAVId,
  request: ArmDisarmRequest = {},
): Promise<CommandAckResponse> {
  void slot;
  void request;
  return notImplemented();
}

export async function setMode(
  slot: UAVId,
  request: ModeChangeRequest,
): Promise<CommandAckResponse> {
  void slot;
  void request;
  return notImplemented();
}

export async function rtl(slot: UAVId): Promise<CommandAckResponse> {
  void slot;
  return notImplemented();
}

export async function takeoff(
  slot: UAVId,
  request: TakeoffRequest,
): Promise<CommandAckResponse> {
  void slot;
  void request;
  return notImplemented();
}

export async function goTo(
  slot: UAVId,
  request: GotoRequest,
): Promise<CommandAckResponse> {
  void slot;
  void request;
  return notImplemented();
}

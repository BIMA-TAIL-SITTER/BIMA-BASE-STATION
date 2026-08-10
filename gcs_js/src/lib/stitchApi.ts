import type {
  StitchConfig,
  StitchIntermediateList,
  StitchSessionStatus,
  StitchSessionSummary,
  StitchStreamSource,
} from "@/types/stitching";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const STITCH_API_BASE =
  `${API_BASE.replace(/\/$/, "")}/api/stitching`;

export class StitchApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "StitchApiError";
    this.status = status;
  }
}

function apiUrl(path: string): string {
  const normalizedPath = path.replace(/^\/+/, "");
  return new URL(
    normalizedPath,
    `${STITCH_API_BASE.replace(/\/$/, "")}/`,
  ).toString();
}

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const isFormData = typeof FormData !== "undefined"
    && init?.body instanceof FormData;
  if (init?.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(apiUrl(path), {
    ...init,
    cache: "no-store",
    headers,
  });
  const payload = (await response.json().catch(() => null)) as
    | { detail?: string; error?: string }
    | T
    | null;
  if (!response.ok) {
    const errorPayload = payload as { detail?: string; error?: string } | null;
    throw new StitchApiError(
      errorPayload?.detail
        || errorPayload?.error
        || `Base station stitching request failed (${response.status})`,
      response.status,
    );
  }
  return payload as T;
}

export async function listSessions(): Promise<StitchSessionSummary[]> {
  const response = await requestJson<{ sessions: StitchSessionSummary[] }>(
    "/sessions",
  );
  return response.sessions;
}

export async function createSession(config: StitchConfig): Promise<{
  status: string;
  session_id: string;
  image_count: number;
  folder_monitoring: boolean;
}> {
  return requestJson("/session/create", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export async function toggleMonitoring(
  sessionId: string,
  enable: boolean,
): Promise<{ status: string }> {
  return requestJson(
    `/session/${encodeURIComponent(sessionId)}/toggle-monitoring?enable=${enable}`,
    { method: "POST" },
  );
}

export async function toggleAutoStitch(
  sessionId: string,
  enable: boolean,
): Promise<{ status: string; threshold: number }> {
  return requestJson(
    `/session/${encodeURIComponent(sessionId)}/toggle-auto-stitch?enable=${enable}`,
    { method: "POST" },
  );
}

export async function uploadImages(
  sessionId: string,
  files: File[],
): Promise<{ uploaded: number; total: number; session_id: string }> {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return requestJson(`/session/${encodeURIComponent(sessionId)}/upload`, {
    method: "POST",
    body,
  });
}

export async function captureStreamImage(
  sessionId: string,
  source: StitchStreamSource,
): Promise<{
  captured: number;
  file: string;
  total: number;
  session_id: string;
  stream_port: number;
  json_port: number | null;
  uav_id: number | null;
}> {
  return requestJson(`/session/${encodeURIComponent(sessionId)}/capture-stream`, {
    method: "POST",
    body: JSON.stringify({
      streamPort: source.streamPort,
      jsonPort: source.jsonPort,
      uavId: source.uavId,
    }),
  });
}

export async function triggerStitch(
  sessionId: string,
): Promise<{ status: string; image_count?: number }> {
  return requestJson(`/session/${encodeURIComponent(sessionId)}/stitch`, {
    method: "POST",
  });
}

export function getResultImageUrl(
  sessionId: string,
  revision?: number,
): string {
  const url = new URL(apiUrl(`/session/${encodeURIComponent(sessionId)}/result`));
  if (revision !== undefined) {
    url.searchParams.set("v", String(revision));
  }
  return url.toString();
}

export async function listIntermediates(
  sessionId: string,
): Promise<StitchIntermediateList> {
  return requestJson(
    `/session/${encodeURIComponent(sessionId)}/intermediates`,
  );
}

export function getIntermediateImageUrl(
  sessionId: string,
  fileName: string,
): string {
  return apiUrl(
    `/session/${encodeURIComponent(sessionId)}/intermediates/${encodeURIComponent(fileName)}`,
  );
}

export async function getSessionStatus(
  sessionId: string,
): Promise<StitchSessionStatus> {
  return requestJson(`/session/${encodeURIComponent(sessionId)}/status`);
}

export function getStitchWebSocketUrl(sessionId: string): string {
  const url = new URL(API_BASE);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `/ws/stitching/${encodeURIComponent(sessionId)}`;
  url.search = "";
  url.hash = "";
  return url.toString();
}

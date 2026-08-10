"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import { getStitchWebSocketUrl } from "@/lib/stitchApi";
import type { StitchWsEvent } from "@/types/stitching";

export type StitchWebSocketState = "disconnected" | "connecting" | "live";

interface UseStitchWebSocketOptions {
  sessionId: string | null;
  onEvent: (event: StitchWsEvent) => void;
  onError?: (message: string) => void;
}

function isStitchEvent(value: unknown): value is StitchWsEvent {
  if (!value || typeof value !== "object") return false;
  const type = (value as { type?: unknown }).type;
  return type === "file_detected"
    || type === "stitching_started"
    || type === "stitching_completed";
}

export function useStitchWebSocket({
  sessionId,
  onEvent,
  onError,
}: UseStitchWebSocketOptions): StitchWebSocketState {
  const [connection, setConnection] = useState<{
    sessionId: string | null;
    state: StitchWebSocketState;
  }>({ sessionId: null, state: "disconnected" });
  const sessionRef = useRef(sessionId);
  const eventHandler = useRef(onEvent);
  const errorHandler = useRef(onError);

  useEffect(() => {
    sessionRef.current = sessionId;
    eventHandler.current = onEvent;
    errorHandler.current = onError;
  }, [onError, onEvent, sessionId]);

  const handleMessage = useCallback((payload: string) => {
    try {
      const parsed = JSON.parse(payload) as unknown;
      if (isStitchEvent(parsed)) {
        eventHandler.current(parsed);
        return;
      }
      if (
        parsed
        && typeof parsed === "object"
        && typeof (parsed as { error?: unknown }).error === "string"
      ) {
        errorHandler.current?.((parsed as { error: string }).error);
      }
    } catch {
      errorHandler.current?.("Received an invalid stitching event.");
    }
  }, []);

  const handleOpen = useCallback(() => {
    setConnection({ sessionId: sessionRef.current, state: "live" });
  }, []);
  const handleClose = useCallback(() => {
    setConnection({ sessionId: sessionRef.current, state: "connecting" });
  }, []);

  useWebSocket({
    url: sessionId ? getStitchWebSocketUrl(sessionId) : "",
    enabled: Boolean(sessionId),
    onMessage: handleMessage,
    onOpen: handleOpen,
    onClose: handleClose,
  });

  if (!sessionId) return "disconnected";
  return connection.sessionId === sessionId ? connection.state : "connecting";
}

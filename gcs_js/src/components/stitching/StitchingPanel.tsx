"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { UAV_AGENT_BY_ID, UAV_IDS } from "@/config/agents";
import { useGCSStore } from "@/hooks/useGCSStore";
import { useStitchWebSocket } from "@/hooks/useStitchWebSocket";
import {
  captureStreamImage,
  createSession,
  getSessionStatus,
  listIntermediates,
  listSessions,
  toggleAutoStitch,
  toggleMonitoring,
  triggerStitch,
  uploadImages,
} from "@/lib/stitchApi";
import type {
  StitchConfig,
  StitchEventRecord,
  StitchSessionStatus,
  StitchSessionSummary,
  StitchStreamSource,
  StitchWsEvent,
} from "@/types/stitching";
import { StitchingEventLog } from "./StitchingEventLog";
import { StitchingResultViewer } from "./StitchingResultViewer";
import { StitchingSessionControl } from "./StitchingSessionControl";

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "The base station stitching request failed.";
}

export function StitchingPanel() {
  const { uavs } = useGCSStore();
  const [sessions, setSessions] = useState<StitchSessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState<StitchSessionStatus | null>(null);
  const [intermediates, setIntermediates] = useState<string[]>([]);
  const [events, setEvents] = useState<StitchEventRecord[]>([]);
  const [resultRevision, setResultRevision] = useState(0);
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const eventId = useRef(0);

  const streamSources: StitchStreamSource[] = useMemo(() => (
    UAV_IDS.flatMap((uavId) => {
      const agent = UAV_AGENT_BY_ID[uavId];
      const connection = uavs[uavId];
      if (!agent.hasVideo || !connection?.streamPort) return [];
      const streamPort = Number.parseInt(connection.streamPort, 10);
      if (!Number.isInteger(streamPort) || streamPort < 1 || streamPort > 65_535) {
        return [];
      }
      const jsonPort = Number.parseInt(connection.jsonPort, 10);
      return [{
        uavId,
        label: agent.label,
        streamPort,
        jsonPort: Number.isInteger(jsonPort) && jsonPort >= 1 && jsonPort <= 65_535
          ? jsonPort
          : undefined,
      }];
    })
  ), [uavs]);

  const refreshSessions = useCallback(async (preferredSessionId?: string) => {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
    setSelectedSessionId((current) => {
      if (
        preferredSessionId
        && nextSessions.some((session) => session.session_id === preferredSessionId)
      ) {
        return preferredSessionId;
      }
      if (current && nextSessions.some((session) => session.session_id === current)) {
        return current;
      }
      return nextSessions[0]?.session_id ?? null;
    });
  }, []);

  const refreshSessionDetails = useCallback(async (sessionId: string) => {
    const [nextStatus, nextIntermediates] = await Promise.all([
      getSessionStatus(sessionId),
      listIntermediates(sessionId),
    ]);
    setStatus(nextStatus);
    setIntermediates(nextIntermediates.files);
  }, []);

  useEffect(() => {
    let active = true;
    const loadInitialSessions = async () => {
      try {
        const nextSessions = await listSessions();
        if (!active) return;
        setSessions(nextSessions);
        setSelectedSessionId(nextSessions[0]?.session_id ?? null);
      } catch (loadError) {
        if (active) setError(errorMessage(loadError));
      } finally {
        if (active) setIsInitialLoading(false);
      }
    };
    void loadInitialSessions();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!selectedSessionId) return;

    let active = true;
    const load = async () => {
      try {
        const [nextStatus, nextIntermediates] = await Promise.all([
          getSessionStatus(selectedSessionId),
          listIntermediates(selectedSessionId),
        ]);
        if (active) {
          setStatus(nextStatus);
          setIntermediates(nextIntermediates.files);
        }
      } catch (loadError) {
        if (active) setError(errorMessage(loadError));
      }
    };
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [selectedSessionId]);

  const handleSelectSession = useCallback((sessionId: string) => {
    setSelectedSessionId(sessionId);
    setEvents([]);
    setStatus(null);
    setIntermediates([]);
    setResultRevision((current) => current + 1);
    setError(null);
    setNotice(null);
  }, []);

  const handleStitchEvent = useCallback((event: StitchWsEvent) => {
    const record: StitchEventRecord = {
      ...event,
      id: ++eventId.current,
      receivedAt: new Date().toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
    };
    setEvents((current) => [record, ...current].slice(0, 100));
    if (selectedSessionId) {
      void refreshSessionDetails(selectedSessionId).catch(() => undefined);
    }
    if (event.type === "stitching_completed" && event.success) {
      setResultRevision((current) => current + 1);
      setNotice(`Orthomosaic completed in ${event.elapsed_time.toFixed(2)} seconds.`);
    } else if (event.type === "stitching_completed" && !event.success) {
      setError(event.error_message || "Stitching failed.");
    }
  }, [refreshSessionDetails, selectedSessionId]);

  const connectionState = useStitchWebSocket({
    sessionId: selectedSessionId,
    onEvent: handleStitchEvent,
    onError: setError,
  });

  const runAction = async (
    name: string,
    action: () => Promise<void>,
  ) => {
    setPendingAction(name);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (actionError) {
      setError(errorMessage(actionError));
    } finally {
      setPendingAction(null);
    }
  };

  const handleCreate = async (config: StitchConfig) => {
    await runAction("create", async () => {
      const response = await createSession(config);
      handleSelectSession(response.session_id);
      await refreshSessions(response.session_id);
      await refreshSessionDetails(response.session_id);
      setNotice(`${response.session_id} is ready for image intake.`);
    });
  };

  const handleToggleMonitoring = async (enable: boolean) => {
    if (!selectedSessionId) return;
    await runAction("monitoring", async () => {
      await toggleMonitoring(selectedSessionId, enable);
      await refreshSessionDetails(selectedSessionId);
      setNotice(`Folder monitoring ${enable ? "enabled" : "disabled"}.`);
    });
  };

  const handleToggleAutoStitch = async (enable: boolean) => {
    if (!selectedSessionId) return;
    await runAction("auto-stitch", async () => {
      await toggleAutoStitch(selectedSessionId, enable);
      await refreshSessionDetails(selectedSessionId);
      setNotice(`Auto-stitch ${enable ? "enabled" : "disabled"}.`);
    });
  };

  const handleUpload = async (files: File[]) => {
    if (!selectedSessionId) return;
    await runAction("upload", async () => {
      const response = await uploadImages(selectedSessionId, files);
      await refreshSessionDetails(selectedSessionId);
      await refreshSessions(selectedSessionId);
      setNotice(`${response.uploaded} image${response.uploaded === 1 ? "" : "s"} uploaded.`);
    });
  };

  const handleCaptureStream = async (source: StitchStreamSource) => {
    if (!selectedSessionId) return;
    await runAction("capture-stream", async () => {
      const response = await captureStreamImage(selectedSessionId, source);
      await refreshSessionDetails(selectedSessionId);
      await refreshSessions(selectedSessionId);
      setNotice(
        `${response.file} captured from ${source.label} stream port ${source.streamPort}.`,
      );
    });
  };

  const handleTrigger = async () => {
    if (!selectedSessionId) return;
    await runAction("stitch", async () => {
      const response = await triggerStitch(selectedSessionId);
      await refreshSessionDetails(selectedSessionId);
      setNotice(response.status);
    });
  };

  return (
    <div className="stitching-workspace">
      <header className="operations-page-header">
        <div>
          <h1>Live Image Stitching</h1>
        </div>
        <div className="operations-page-code">
          STITCH
          <span>BASE API / UI STREAM PORT</span>
        </div>
      </header>

      {error && <div className="operations-message is-error">{error}</div>}
      {notice && <div className="operations-message">{notice}</div>}

      {isInitialLoading ? (
        <section className="operations-section">
          <div className="operations-loading-state">
            <span />
            <span />
            <span />
            <strong>Connecting to base station stitching</strong>
          </div>
        </section>
      ) : (
        <>
          <StitchingSessionControl
            sessions={sessions}
            selectedSessionId={selectedSessionId}
            status={status}
            pendingAction={pendingAction}
            onSelect={handleSelectSession}
            onCreate={handleCreate}
            onToggleMonitoring={handleToggleMonitoring}
            onToggleAutoStitch={handleToggleAutoStitch}
            onUpload={handleUpload}
            streamSources={streamSources}
            onCaptureStream={handleCaptureStream}
          />

          <div className="stitching-output-grid">
            <StitchingResultViewer
              sessionId={selectedSessionId}
              status={status}
              intermediates={intermediates}
              resultRevision={resultRevision}
              pendingAction={pendingAction}
              onTrigger={handleTrigger}
            />
            <StitchingEventLog
              events={events}
              connectionState={connectionState}
            />
          </div>
        </>
      )}
    </div>
  );
}

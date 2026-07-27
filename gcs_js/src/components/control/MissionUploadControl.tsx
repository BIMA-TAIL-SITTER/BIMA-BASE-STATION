/** Complete mission read, edit, map, reorder, and upload workspace. */

"use client";

import dynamic from "next/dynamic";
import {
  useCallback,
  useEffect,
  useState,
  type CSSProperties,
} from "react";
import { UAV_AGENT_BY_ID } from "@/config/agents";
import { createEmptyMissionItem } from "@/config/mission";
import { useWebSocket } from "@/hooks/useWebSocket";
import {
  fetchMission,
  getControlWebSocketUrl,
  uploadMission,
} from "@/lib/controlApi";
import type {
  ControlWebSocketEvent,
  MissionItem,
  MissionUploadProgressEvent,
  MissionUploadResponse,
} from "@/types/control";
import type { UAVId } from "@/types/telemetry";
import { MissionTable } from "./MissionTable";
import { UavSelector } from "./UavSelector";

const MissionMap = dynamic(() => import("./MissionMap"), { ssr: false });

function normalizeSequence(items: MissionItem[]): MissionItem[] {
  return items.map((item, index) => ({ ...item, seq: index }));
}

function parseControlEvent(payload: string): ControlWebSocketEvent | null {
  try {
    return JSON.parse(payload) as ControlWebSocketEvent;
  } catch {
    return null;
  }
}

export function MissionUploadControl() {
  const [slot, setSlot] = useState<UAVId>(1);
  const [draftMission, setDraftMission] = useState<MissionItem[]>([]);
  const [hasUnuploadedChanges, setHasUnuploadedChanges] = useState(false);
  const [showFetchConfirmation, setShowFetchConfirmation] = useState(false);
  const [isFetching, setIsFetching] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] =
    useState<MissionUploadProgressEvent | null>(null);
  const [uploadResult, setUploadResult] =
    useState<MissionUploadResponse | null>(null);

  const agent = UAV_AGENT_BY_ID[slot];

  const handleControlMessage = useCallback(
    (payload: string) => {
      const event = parseControlEvent(payload);
      if (
        event?.type === "mission_upload_progress"
        && event.slot === slot
      ) {
        setUploadProgress(event);
        if (event.status === "error") {
          setError(event.message);
        }
      }
    },
    [slot],
  );

  useWebSocket({
    url: getControlWebSocketUrl(slot),
    onMessage: handleControlMessage,
  });

  const changeSlot = useCallback((nextSlot: UAVId) => {
    setSlot(nextSlot);
    setDraftMission([]);
    setUploadProgress(null);
    setUploadResult(null);
    setError(null);
    setNotice(null);
    setHasUnuploadedChanges(false);
    setShowFetchConfirmation(false);
  }, []);

  useEffect(() => {
    if (!showFetchConfirmation) return;

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isFetching) {
        setShowFetchConfirmation(false);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isFetching, showFetchConfirmation]);

  const fetchAndLoadMission = async () => {
    setShowFetchConfirmation(false);
    setIsFetching(true);
    setError(null);
    setNotice(null);
    try {
      const waypoints = await fetchMission(slot);
      const normalizedMission = normalizeSequence(waypoints);
      setDraftMission(normalizedMission.map((item) => ({ ...item })));
      setHasUnuploadedChanges(false);
      setNotice(
        waypoints.length
          ? `Received ${waypoints.length} mission items from ${agent.shortLabel} and loaded them into the local editor.`
          : `${agent.shortLabel} returned an empty mission. The local editor was cleared.`,
      );
    } catch (fetchError) {
      setError(
        fetchError instanceof Error
          ? fetchError.message
          : "Mission fetch failed.",
      );
    } finally {
      setIsFetching(false);
    }
  };

  const handleFetch = () => {
    if (hasUnuploadedChanges) {
      setShowFetchConfirmation(true);
      return;
    }
    void fetchAndLoadMission();
  };

  const handleCoordinatePick = useCallback((lat: number, lon: number) => {
    setDraftMission((current) => {
      const sequence = current.length;
      return normalizeSequence([
        ...current,
        {
          ...createEmptyMissionItem(sequence),
          lat,
          lon,
        },
      ]);
    });
    setHasUnuploadedChanges(true);
    setError(null);
    setNotice("Waypoint added from the map. Edit its parameters in Mission Editor.");
  }, []);

  const updateWaypoint = (
    index: number,
    update: Partial<Omit<MissionItem, "seq">>,
  ) => {
    setDraftMission((current) => normalizeSequence(
      current.map((item, itemIndex) => {
        if (itemIndex !== index) {
          return update.current ? { ...item, current: false } : item;
        }
        return { ...item, ...update };
      }),
    ));
    setHasUnuploadedChanges(true);
    setNotice(`Waypoint ${index} updated in the local editor.`);
  };

  const moveWaypoint = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= draftMission.length) return;
    setDraftMission((current) => {
      const reordered = [...current];
      [reordered[index], reordered[target]] = [
        reordered[target],
        reordered[index],
      ];
      return normalizeSequence(reordered);
    });
    setHasUnuploadedChanges(true);
  };

  const removeWaypoint = (index: number) => {
    setDraftMission((current) => normalizeSequence(
      current.filter((_, itemIndex) => itemIndex !== index),
    ));
    setHasUnuploadedChanges(true);
  };

  const handleUpload = async () => {
    if (!draftMission.length) {
      setError("Add at least one mission item before uploading.");
      return;
    }
    setIsUploading(true);
    setError(null);
    setNotice(null);
    setUploadResult(null);
    setUploadProgress({
      type: "mission_upload_progress",
      slot,
      status: "starting",
      sent: 0,
      total: draftMission.length,
      message: "Preparing mission upload",
    });
    try {
      const result = await uploadMission(slot, {
        items: normalizeSequence(draftMission),
      });
      setUploadResult(result);
      setUploadProgress({
        type: "mission_upload_progress",
        slot,
        status: result.success ? "complete" : "error",
        sent: result.sent,
        total: result.total,
        message: result.message,
        result_code: result.result_code,
        result_label: result.result_label,
      });
      if (result.success) {
        setHasUnuploadedChanges(false);
        setNotice(result.message);
      } else {
        setError(result.message);
      }
    } catch (uploadError) {
      const message = uploadError instanceof Error
        ? uploadError.message
        : "Mission upload failed.";
      setUploadProgress((current) => ({
        type: "mission_upload_progress",
        slot,
        status: "error",
        sent: current?.sent ?? 0,
        total: current?.total ?? draftMission.length,
        message,
      }));
      setError(message);
    } finally {
      setIsUploading(false);
    }
  };

  const progressPercent = uploadProgress?.total
    ? Math.min(
        100,
        Math.round(
          (uploadProgress.sent / uploadProgress.total) * 100,
        ),
      )
    : 0;

  return (
    <div
      className="mission-workspace"
      style={{
        "--agent-color": agent.color,
        "--agent-color-rgb": agent.colorRgb,
      } as CSSProperties}
    >
      <UavSelector
        value={slot}
        onChange={changeSlot}
        disabled={isFetching || isUploading}
      />

      <section className="operations-command-bar">
        <div>
          <strong>{agent.shortLabel}</strong>
          <span>{agent.type} MISSION CHANNEL</span>
        </div>
        <div className="operations-command-actions">
          <button
            type="button"
            className="operations-button"
            onClick={handleFetch}
            disabled={isFetching || isUploading}
          >
            {isFetching ? "FETCHING MISSION" : "FETCH MISSION FROM UAV"}
          </button>
          <button
            type="button"
            className="operations-button is-primary"
            onClick={handleUpload}
            disabled={!draftMission.length || isUploading}
          >
            {isUploading ? "UPLOADING MISSION" : "UPLOAD MISSION TO UAV"}
          </button>
        </div>
      </section>

      {(uploadProgress || uploadResult) && (
        <section
          className={`operations-progress ${
            uploadProgress?.status === "error" ? "is-error" : ""
          }`}
          aria-live="polite"
        >
          <div>
            <strong>
              {uploadProgress?.message || uploadResult?.message}
            </strong>
            <span>
              {uploadProgress?.sent ?? uploadResult?.sent ?? 0}
              {" / "}
              {uploadProgress?.total ?? uploadResult?.total ?? 0}
              {" ITEMS"}
            </span>
          </div>
          <div className="operations-progress-meter" aria-hidden="true">
            <span style={{ width: `${progressPercent}%` }} />
          </div>
        </section>
      )}

      {(error || notice) && (
        <div
          className={`operations-message ${error ? "is-error" : "is-ok"}`}
          role={error ? "alert" : "status"}
        >
          {error || notice}
        </div>
      )}

      <div className="mission-control-grid">
        <section className="operations-section mission-map-section">
          <header className="operations-section-heading">
            <div>
              <h2>ROUTE PREVIEW</h2>
              <span>
                {hasUnuploadedChanges
                  ? "LOCAL CHANGES NOT UPLOADED"
                  : "MISSION EDITOR ROUTE"}
              </span>
            </div>
            <strong>{draftMission.length} WP</strong>
          </header>
          <MissionMap
            waypoints={draftMission}
            color={agent.color}
            onCoordinatePick={handleCoordinatePick}
          />
        </section>

        <section className="operations-section mission-editor-section">
          <header className="operations-section-heading">
            <div>
              <h2>MISSION EDITOR</h2>
              <span>
                {hasUnuploadedChanges
                  ? "LOCAL CHANGES NOT UPLOADED"
                  : `FETCHED FROM ${agent.shortLabel}`}
              </span>
            </div>
            <strong>{draftMission.length} ITEMS</strong>
          </header>
          <MissionTable
            items={draftMission}
            label={`Mission editor for ${agent.shortLabel}`}
            editable
            onMove={moveWaypoint}
            onRemove={removeWaypoint}
            onUpdate={updateWaypoint}
          />
        </section>
      </div>

      {showFetchConfirmation && (
        <div
          className="operations-dialog-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !isFetching) {
              setShowFetchConfirmation(false);
            }
          }}
        >
          <section
            className="operations-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="fetch-overwrite-title"
            aria-describedby="fetch-overwrite-description"
          >
            <span className="operations-dialog-warning">
              LOCAL CHANGES
            </span>
            <h2 id="fetch-overwrite-title">OVERWRITE LOCAL EDITOR?</h2>
            <p id="fetch-overwrite-description">
              The local editor has changes that have not been uploaded.
              Replace them with the mission from {agent.shortLabel}?
            </p>
            <div className="operations-dialog-actions">
              <button
                type="button"
                className="operations-button is-secondary"
                onClick={() => setShowFetchConfirmation(false)}
                disabled={isFetching}
                autoFocus
              >
                CANCEL
              </button>
              <button
                type="button"
                className="operations-button is-danger"
                onClick={() => void fetchAndLoadMission()}
                disabled={isFetching}
              >
                FETCH AND REPLACE
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

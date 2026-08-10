"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import type {
  StitchConfig,
  StitchSessionStatus,
  StitchSessionSummary,
  StitchStreamSource,
} from "@/types/stitching";

interface StitchingSessionControlProps {
  sessions: StitchSessionSummary[];
  selectedSessionId: string | null;
  status: StitchSessionStatus | null;
  pendingAction: string | null;
  onSelect: (sessionId: string) => void;
  onCreate: (config: StitchConfig) => Promise<void>;
  onToggleMonitoring: (enable: boolean) => Promise<void>;
  onToggleAutoStitch: (enable: boolean) => Promise<void>;
  onUpload: (files: File[]) => Promise<void>;
  streamSources: StitchStreamSource[];
  onCaptureStream: (source: StitchStreamSource) => Promise<void>;
}

function streamSourceKey(source: StitchStreamSource): string {
  return `${source.uavId}:${source.streamPort}:${source.jsonPort ?? ""}`;
}

export function StitchingSessionControl({
  sessions,
  selectedSessionId,
  status,
  pendingAction,
  onSelect,
  onCreate,
  onToggleMonitoring,
  onToggleAutoStitch,
  onUpload,
  streamSources,
  onCaptureStream,
}: StitchingSessionControlProps) {
  const [sessionName, setSessionName] = useState("");
  const [threshold, setThreshold] = useState(5);
  const [files, setFiles] = useState<File[]>([]);
  const [selectedStreamKey, setSelectedStreamKey] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setSelectedStreamKey((current) => {
      if (current && streamSources.some((source) => streamSourceKey(source) === current)) {
        return current;
      }
      return streamSources[0] ? streamSourceKey(streamSources[0]) : "";
    });
  }, [streamSources]);

  const selectedStream = streamSources.find(
    (source) => streamSourceKey(source) === selectedStreamKey,
  );

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = sessionName.trim();
    if (!normalizedName) return;
    await onCreate({
      sessionId: normalizedName,
      auto_stitch_threshold: threshold,
      auto_stitch_enabled: false,
      folder_monitoring_enabled: false,
      output_name: "finalResult.png",
    });
    setSessionName("");
  };

  const handleUpload = async () => {
    if (!files.length) return;
    await onUpload(files);
    setFiles([]);
  };

  return (
    <section className="operations-section stitching-session-section">
      <div className="operations-section-heading">
        <div>
          <h2>Stitching Session</h2>
          <span>Manage image intake and automatic mosaic generation.</span>
        </div>
        <strong>{status ? `${status.image_count} IMAGES` : "NO SESSION"}</strong>
      </div>

      <div className="stitching-session-body">
        <div className="stitching-session-select-row">
          <label className="operations-field">
            <span>Active session</span>
            <select
              value={selectedSessionId ?? ""}
              onChange={(event) => onSelect(event.target.value)}
              disabled={!sessions.length || Boolean(pendingAction)}
            >
              {!sessions.length && <option value="">No sessions available</option>}
              {sessions.map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {session.session_id} ({session.image_count})
                </option>
              ))}
            </select>
          </label>

          <form className="stitching-create-form" onSubmit={handleCreate}>
            <label className="operations-field">
              <span>New session ID</span>
              <input
                value={sessionName}
                onChange={(event) => setSessionName(event.target.value)}
                placeholder="survey_north"
                pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}"
                maxLength={64}
                required
              />
            </label>
            <label className="operations-field">
              <span>Auto threshold</span>
              <input
                type="number"
                min={1}
                max={10000}
                value={threshold}
                onChange={(event) => setThreshold(Number(event.target.value))}
                required
              />
            </label>
            <button
              type="submit"
              className="operations-button is-primary"
              disabled={Boolean(pendingAction)}
            >
              Create Session
            </button>
          </form>
        </div>

        <div className="stitching-status-strip" aria-label="Session status">
          <div>
            <span>Images</span>
            <strong>{status?.image_count ?? 0}</strong>
          </div>
          <div>
            <span>Since stitch</span>
            <strong>{status?.images_since_last_stitch ?? 0}</strong>
          </div>
          <div>
            <span>Threshold</span>
            <strong>{status?.auto_stitch_threshold ?? threshold}</strong>
          </div>
          <div>
            <span>Engine</span>
            <strong className={status?.is_stitching ? "is-busy" : ""}>
              {status?.is_stitching ? "PROCESSING" : "READY"}
            </strong>
          </div>
        </div>

        <div className="stitching-stream-intake-row">
          <label className="operations-field">
            <span>Live stream source</span>
            <select
              value={selectedStreamKey}
              onChange={(event) => setSelectedStreamKey(event.target.value)}
              disabled={!streamSources.length || Boolean(pendingAction)}
            >
              {!streamSources.length && (
                <option value="">No configured stream ports</option>
              )}
              {streamSources.map((source) => (
                <option key={streamSourceKey(source)} value={streamSourceKey(source)}>
                  {source.label} - UDP {source.streamPort}
                </option>
              ))}
            </select>
          </label>
          <div className="stitching-stream-action">
            <span>
              {selectedStream
                ? `Stream ${selectedStream.streamPort}`
                : "Stream unavailable"}
            </span>
            <button
              type="button"
              className="operations-button is-primary"
              onClick={() => {
                if (selectedStream) void onCaptureStream(selectedStream);
              }}
              disabled={
                !selectedSessionId
                || !selectedStream
                || Boolean(pendingAction)
              }
            >
              {pendingAction === "capture-stream" ? "Capturing" : "Capture Frame"}
            </button>
          </div>
        </div>

        <div className="stitching-intake-row">
          <div className="stitching-toggle-stack">
            <label className="stitching-toggle">
              <input
                type="checkbox"
                checked={status?.folder_monitoring_enabled ?? false}
                onChange={(event) => void onToggleMonitoring(event.target.checked)}
                disabled={!selectedSessionId || Boolean(pendingAction)}
              />
              <span>
                <strong>Folder monitoring</strong>
                <small>Watch the session image directory.</small>
              </span>
            </label>
            <label className="stitching-toggle">
              <input
                type="checkbox"
                checked={status?.auto_stitch_enabled ?? false}
                onChange={(event) => void onToggleAutoStitch(event.target.checked)}
                disabled={!selectedSessionId || Boolean(pendingAction)}
              />
              <span>
                <strong>Auto-stitch</strong>
                <small>Run after the configured image threshold.</small>
              </span>
            </label>
          </div>

          <div className="stitching-upload-control">
            <label className="operations-field">
              <span>Manual image upload</span>
              <input
                id="manual-file-upload"
                ref={fileInputRef}
                key={files.map((file) => file.name).join("|") || "empty"}
                className="stitching-file-input"
                type="file"
                accept=".jpg,.jpeg,.png,.tif,.tiff,image/*"
                multiple
                onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
                disabled={!selectedSessionId || Boolean(pendingAction)}
              />
            </label>
            {files.length ? (
              <button
                type="button"
                className="operations-button"
                onClick={() => void handleUpload()}
                disabled={!selectedSessionId || Boolean(pendingAction)}
              >
                Upload {files.length} Image{files.length === 1 ? "" : "s"}
              </button>
            ) : (
              <label
                htmlFor="manual-file-upload"
                className="operations-button"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  cursor: (!selectedSessionId || Boolean(pendingAction)) ? "not-allowed" : "pointer",
                  opacity: (!selectedSessionId || Boolean(pendingAction)) ? 0.5 : 1
                }}
              >
                Select Images
              </label>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

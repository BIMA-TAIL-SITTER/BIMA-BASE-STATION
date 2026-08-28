"use client";

import { memo, useState, useCallback } from "react";
import type { MavlinkStatus, UAVId } from "@/types/telemetry";
import { useUavControl } from "@/hooks/useUavControl";

interface MavlinkHeaderProps {
  panelId: UAVId;
  mavlinkStatus: MavlinkStatus;
}

function MavlinkHeaderInner({ panelId, mavlinkStatus }: MavlinkHeaderProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [feedbackMsg, setFeedbackMsg] = useState<{
    text: string;
    type: "success" | "error";
  } | null>(null);
  const control = useUavControl(panelId);

  const isConnected =
    mavlinkStatus === "ARMED" || mavlinkStatus === "DISARMED";
  const isArmed = mavlinkStatus === "ARMED";

  const statusPresentation = (): { className: string; text: string } => {
    switch (mavlinkStatus) {
      case "ARMED":
        return { className: "is-armed", text: "ARMED" };
      case "DISARMED":
        return { className: "is-disarmed", text: "DISARMED" };
      default:
        return {
          className: "is-disconnected",
          text: "No Mavlink Detected",
        };
    }
  };

  const status = statusPresentation();

  const handleForceAction = useCallback(() => {
    setShowConfirm(true);
  }, []);

  const handleConfirm = useCallback(async () => {
    setIsLoading(true);
    setShowConfirm(false);
    try {
      if (isArmed) {
        await control.disarm({ force: true });
        setFeedbackMsg({ text: "Force Disarm sent!", type: "success" });
      } else {
        await control.arm({ force: true });
        setFeedbackMsg({ text: "Force Arm sent!", type: "success" });
      }
    } catch (err) {
      setFeedbackMsg({
        text: err instanceof Error ? err.message : "Command failed",
        type: "error",
      });
    } finally {
      setIsLoading(false);
      setTimeout(() => setFeedbackMsg(null), 3000);
    }
  }, [isArmed, control]);

  const handleCancel = useCallback(() => {
    setShowConfirm(false);
  }, []);

  return (
    <>
      <div className="mavlink-header">
        <div className="mavlink-status-row">
          {isConnected ? (
            <div className="mavlink-status-split">
              <div
                id={`mavlink-status-${panelId}`}
                className={`mavlink-status mavlink-status-main ${status.className}`}
              >
                {status.text}
              </div>
              <button
                id={`mavlink-force-${panelId}`}
                className={`mavlink-force-btn ${isArmed ? "force-disarm" : "force-arm"}`}
                onClick={handleForceAction}
                disabled={isLoading}
              >
                {isLoading
                  ? "..."
                  : isArmed
                    ? "FORCE DISARM"
                    : "FORCE ARM"}
              </button>
            </div>
          ) : (
            <div
              id={`mavlink-status-${panelId}`}
              className={`mavlink-status ${status.className}`}
            >
              {status.text}
            </div>
          )}
        </div>

        {feedbackMsg && (
          <div className={`mavlink-feedback mavlink-feedback-${feedbackMsg.type}`}>
            {feedbackMsg.text}
          </div>
        )}
      </div>

      {showConfirm && (
        <div className="force-confirm-overlay" onClick={handleCancel}>
          <div
            className="force-confirm-modal"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="force-confirm-icon">
              {isArmed ? "⚠" : "⚡"}
            </div>
            <h3 className="force-confirm-title">
              {isArmed ? "Force Disarm?" : "Force Arm?"}
            </h3>
            <p className="force-confirm-desc">
              {isArmed
                ? `Apakah anda yakin ingin FORCE DISARM UAV ${panelId}? Motor akan langsung berhenti!`
                : `Apakah anda yakin ingin FORCE ARM UAV ${panelId}? Motor akan mulai berputar!`}
            </p>
            <div className="force-confirm-actions">
              <button
                className="force-confirm-cancel"
                onClick={handleCancel}
              >
                Batal
              </button>
              <button
                className={`force-confirm-proceed ${isArmed ? "is-danger" : "is-warning"}`}
                onClick={handleConfirm}
              >
                {isArmed ? "Ya, Force Disarm" : "Ya, Force Arm"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export const MavlinkHeader = memo(MavlinkHeaderInner);

"use client";

import { useState, useCallback } from "react";
import type { UAVId } from "@/types/telemetry";
import { useUavControl } from "@/hooks/useUavControl";

/** Common ArduCopter flight modes. */
export const COPTER_FLIGHT_MODES = [
  "STABILIZE",
  "ACRO",
  "ALT_HOLD",
  "AUTO",
  "GUIDED",
  "LOITER",
  "RTL",
  "CIRCLE",
  "LAND",
  "DRIFT",
  "SPORT",
  "FLIP",
  "AUTOTUNE",
  "POSHOLD",
  "BRAKE",
  "THROW",
  "AVOID_ADSB",
  "GUIDED_NOGPS",
  "SMART_RTL",
  "FLOWHOLD",
  "FOLLOW",
  "ZIGZAG",
  "SYSTEMID",
  "AUTOROTATE",
  "AUTO_RTL",
];

/** Common ArduPlane & VTOL flight modes. */
export const PLANE_FLIGHT_MODES = [
  "MANUAL",
  "CIRCLE",
  "STABILIZE",
  "TRAINING",
  "ACRO",
  "FLY_BY_WIRE_A",
  "FLY_BY_WIRE_B",
  "CRUISE",
  "AUTOTUNE",
  "AUTO",
  "RTL",
  "LOITER",
  "TAKEOFF",
  "AVOID_ADSB",
  "GUIDED",
  "INITIALISING",
  "QSTABILIZE",
  "QHOVER",
  "QLOITER",
  "QLAND",
  "QRTL",
  "QAUTOTUNE",
  "QACRO",
  "THERMAL"
];

interface ModeSelectorProps {
  panelId: UAVId;
  currentMode: string;
  isConnected: boolean;
  availableModes: string[];
}

export function ModeSelector({
  panelId,
  currentMode,
  isConnected,
  availableModes
}: ModeSelectorProps) {
  const [selectedMode, setSelectedMode] = useState<string>("");
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [feedback, setFeedback] = useState<{
    text: string;
    type: "success" | "error";
  } | null>(null);
  const control = useUavControl(panelId);

  const handleSetMode = useCallback(async () => {
    if (!selectedMode || selectedMode === currentMode) return;
    setIsLoading(true);
    try {
      await control.setMode({ mode: selectedMode });
      setFeedback({ text: `Mode → ${selectedMode}`, type: "success" });
      setSelectedMode("");
      setIsOpen(false);
    } catch (err) {
      setFeedback({
        text: err instanceof Error ? err.message : "Set mode failed",
        type: "error",
      });
    } finally {
      setIsLoading(false);
      setTimeout(() => setFeedback(null), 3000);
    }
  }, [selectedMode, currentMode, control]);

  if (!isConnected) {
    return (
      <div className="copter-metric is-accent">
        <span className="copter-metric-label">MODE</span>
        <span className="copter-metric-value">--</span>
      </div>
    );
  }

  return (
    <div className="mode-selector-cell" onClick={() => setIsOpen(!isOpen)}>
      <div className="mode-selector-current">
        <span className="copter-metric-label">MODE</span>
        <span className="copter-metric-value mode-current-value">
          {currentMode || "--"}
          <svg
            className={`mode-chevron ${isOpen ? "is-open" : ""}`}
            width="8"
            height="8"
            viewBox="0 0 10 10"
          >
            <path d="M2 4 L5 7 L8 4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </div>

      {isOpen && (
        <div className="mode-dropdown">
          <div className="mode-dropdown-list">
            {availableModes.map((mode) => (
              <button
                key={mode}
                className={`mode-dropdown-item ${mode === currentMode ? "is-current" : ""} ${mode === selectedMode ? "is-selected" : ""}`}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedMode(mode);
                }}
              >
                {mode}
                {mode === currentMode && (
                  <span className="mode-current-badge">AKTIF</span>
                )}
              </button>
            ))}
          </div>
          {selectedMode && selectedMode !== currentMode && (
            <button
              className="mode-set-btn"
              onClick={(e) => {
                e.stopPropagation();
                handleSetMode();
              }}
              disabled={isLoading}
            >
              {isLoading ? "SETTING..." : `SET MODE → ${selectedMode}`}
            </button>
          )}
        </div>
      )}

      {feedback && (
        <div className={`mode-feedback mode-feedback-${feedback.type}`}>
          {feedback.text}
        </div>
      )}
    </div>
  );
}

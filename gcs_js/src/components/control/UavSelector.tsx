/** Shared four-slot selector with the dashboard's agent color registry. */

"use client";

import type { CSSProperties } from "react";
import { UAV_AGENTS } from "@/config/agents";
import type { UAVId } from "@/types/telemetry";

interface UavSelectorProps {
  value: UAVId;
  onChange: (slot: UAVId) => void;
  disabled?: boolean;
}

export function UavSelector({
  value,
  onChange,
  disabled = false,
}: UavSelectorProps) {
  return (
    <div className="uav-selector" role="group" aria-label="Select UAV slot">
      {UAV_AGENTS.map((agent) => (
        <button
          key={agent.id}
          type="button"
          className={`uav-selector-button ${
            value === agent.id ? "is-active" : ""
          }`}
          style={{
            "--agent-color": agent.color,
            "--agent-color-rgb": agent.colorRgb,
          } as CSSProperties}
          onClick={() => onChange(agent.id)}
          aria-pressed={value === agent.id}
          disabled={disabled}
        >
          <span>{agent.shortLabel}</span>
          <small>{agent.type}</small>
        </button>
      ))}
    </div>
  );
}

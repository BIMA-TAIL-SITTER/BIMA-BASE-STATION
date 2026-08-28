"use client";

import type { CSSProperties, ReactNode } from "react";
import { UAV_AGENTS } from "@/config/agents";
import type { UAVConnectionConfig, UAVId, UAVRecord } from "@/types/telemetry";

export type ConnectionFieldKey = keyof UAVConnectionConfig;

interface ConnectionFieldDefinition {
  key: ConnectionFieldKey;
  label: string;
  type: "number" | "text";
  icon: ReactNode;
}

const portIcon = (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </svg>
);

const videoIcon = (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polygon points="23 7 16 12 23 17 23 7" />
    <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
  </svg>
);

const serverIcon = (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
    <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
    <line x1="6" y1="6" x2="6.01" y2="6" />
    <line x1="6" y1="18" x2="6.01" y2="18" />
  </svg>
);

const codeIcon = (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </svg>
);

const missionIcon = (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 2L2 7l10 5 10-5-10-5z" />
    <path d="M2 17l10 5 10-5" />
    <path d="M2 12l10 5 10-5" />
  </svg>
);

const fcIcon = (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="4" y="4" width="16" height="16" rx="2" />
    <line x1="9" y1="4" x2="9" y2="20" />
    <line x1="15" y1="4" x2="15" y2="20" />
    <line x1="4" y1="9" x2="20" y2="9" />
    <line x1="4" y1="15" x2="20" y2="15" />
  </svg>
);

export const CONNECTION_FIELDS: readonly ConnectionFieldDefinition[] = [
  { key: "streamPort", label: "STREAM PORT", type: "number", icon: videoIcon },
  { key: "tcpIp", label: "UDP IP", type: "text", icon: serverIcon },
  { key: "mavlinkPort", label: "MAVLINK PORT", type: "number", icon: portIcon },
  { key: "jsonPort", label: "JSON PORT", type: "number", icon: codeIcon },
];

const raspiIcon = (
  <svg aria-hidden="true" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="5" y="2" width="14" height="20" rx="2" />
    <circle cx="12" cy="12" r="3" />
    <line x1="12" y1="2" x2="12" y2="6" />
    <line x1="12" y1="18" x2="12" y2="22" />
  </svg>
);

/** Mission control fields — only shown for COPTER type UAVs */
const MISSION_FIELDS: readonly ConnectionFieldDefinition[] = [
  { key: "raspiIp", label: "RASPI IP", type: "text", icon: raspiIcon },
  { key: "missionUdpPort", label: "MISSION UDP PORT", type: "number", icon: missionIcon },
];

const COPTER_BASE_FIELDS = CONNECTION_FIELDS.filter(
  (field) => field.key !== "streamPort" && field.key !== "jsonPort",
);

export function connectionFieldsFor(hasVideo: boolean): readonly ConnectionFieldDefinition[] {
  return hasVideo ? CONNECTION_FIELDS : COPTER_BASE_FIELDS;
}

export function missionFieldsFor(hasVideo: boolean): readonly ConnectionFieldDefinition[] {
  return hasVideo ? [] : MISSION_FIELDS;
}

export function connectionFieldId(uavId: UAVId, key: ConnectionFieldKey): string {
  return `uav-${uavId}-${key}`;
}

interface UAVConnectionCardGridProps {
  values: UAVRecord<UAVConnectionConfig>;
  errors?: Record<string, boolean>;
  onChange: (uavId: UAVId, key: ConnectionFieldKey, value: string) => void;
  onEnter?: () => void;
}

export default function UAVConnectionCardGrid({
  values,
  errors = {},
  onChange,
  onEnter,
}: UAVConnectionCardGridProps) {
  return (
    <div className="setup-cards-grid">
      {UAV_AGENTS.map((agent) => {
        const cardStyle = {
          "--card-accent": agent.color,
          "--card-accent-rgb": agent.colorRgb,
        } as CSSProperties;
        const connectionFields = connectionFieldsFor(agent.hasVideo);
        const missionFields = missionFieldsFor(agent.hasVideo);

        return (
          <section
            className="setup-card"
            key={agent.id}
            style={cardStyle}
            aria-labelledby={`uav-card-title-${agent.id}`}
          >
            <div className="setup-card-header">
              <span
                className="uav-color-dot"
                style={{ backgroundColor: agent.color }}
                aria-hidden="true"
              />
              <span className="uav-label" id={`uav-card-title-${agent.id}`}>
                {agent.label}
              </span>
              <span className="uav-type">{agent.type}</span>
            </div>
            <div className="setup-card-body">
              {connectionFields.map((field) => {
                const id = connectionFieldId(agent.id, field.key);
                const placeholder = `e.g. ${agent.defaultConnection[field.key]}`;
                return (
                  <div className="setup-field-group" key={field.key}>
                    <label className="setup-field-label" htmlFor={id}>
                      {field.icon}
                      {field.label}
                    </label>
                    <input
                      type={field.type}
                      id={id}
                      className={`setup-field-input ${errors[id] ? "is-error" : ""}`}
                      placeholder={placeholder}
                      value={values[agent.id][field.key] || ""}
                      onChange={(event) => onChange(agent.id, field.key, event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") onEnter?.();
                      }}
                      aria-invalid={errors[id] || undefined}
                    />
                  </div>
                );
              })}
              {missionFields.length > 0 && (
                <>
                  <div className="setup-field-separator" aria-hidden="true">
                    <span>MISSION CONTROL</span>
                  </div>
                  {missionFields.map((field) => {
                    const id = connectionFieldId(agent.id, field.key);
                    const placeholder = `e.g. ${agent.defaultConnection[field.key]}`;
                    return (
                      <div className="setup-field-group" key={field.key}>
                        <label className="setup-field-label" htmlFor={id}>
                          {field.icon}
                          {field.label}
                        </label>
                        <input
                          type={field.type}
                          id={id}
                          className={`setup-field-input ${errors[id] ? "is-error" : ""}`}
                          placeholder={placeholder}
                          value={values[agent.id][field.key]}
                          onChange={(event) => onChange(agent.id, field.key, event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") onEnter?.();
                          }}
                          aria-invalid={errors[id] || undefined}
                        />
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          </section>
        );
      })}
    </div>
  );
}

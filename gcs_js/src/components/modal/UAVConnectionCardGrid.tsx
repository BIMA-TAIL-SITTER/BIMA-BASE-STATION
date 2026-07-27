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

export const CONNECTION_FIELDS: readonly ConnectionFieldDefinition[] = [
  { key: "streamPort", label: "STREAM PORT", type: "number", icon: videoIcon },
  { key: "tcpIp", label: "TCP IP", type: "text", icon: serverIcon },
  { key: "mavlinkPort", label: "MAVLINK PORT", type: "number", icon: portIcon },
  { key: "jsonPort", label: "JSON PORT", type: "number", icon: codeIcon },
];

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
    <div className="setup-cards">
      {UAV_AGENTS.map((agent) => {
        const cardStyle = {
          "--card-accent": agent.color,
          "--card-accent-rgb": agent.colorRgb,
        } as CSSProperties;

        return (
          <section
            className="setup-card"
            key={agent.id}
            style={cardStyle}
            aria-labelledby={`uav-card-title-${agent.id}`}
          >
            <div className="setup-card-header">
              <span className="setup-card-indicator" aria-hidden="true" />
              <span className="setup-card-label" id={`uav-card-title-${agent.id}`}>
                {agent.label}
              </span>
              <span className="setup-card-type">{agent.type}</span>
            </div>
            <div className="setup-card-body">
              {CONNECTION_FIELDS.map((field) => {
                const id = connectionFieldId(agent.id, field.key);
                const placeholder = `e.g. ${agent.defaultConnection[field.key]}`;
                return (
                  <div className="setup-field" key={field.key}>
                    <label className="setup-field-label" htmlFor={id}>
                      {field.icon}
                      {field.label}
                    </label>
                    <input
                      type={field.type}
                      id={id}
                      className={`setup-input ${errors[id] ? "invalid" : ""}`}
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
            </div>
          </section>
        );
      })}
    </div>
  );
}

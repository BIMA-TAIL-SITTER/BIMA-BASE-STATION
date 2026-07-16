"use client";

import { useState, useCallback } from "react";
import { useGCSStore } from "@/hooks/useGCSStore";
import type { UAVConnectionConfig } from "@/types/telemetry";

interface FieldDef {
  id: string;
  label: string;
  type: "port" | "ip";
  placeholder: string;
  icon: React.ReactNode;
}

const portIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
  </svg>
);
const videoIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polygon points="23 7 16 12 23 17 23 7" />
    <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
  </svg>
);
const serverIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
    <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
    <line x1="6" y1="6" x2="6.01" y2="6" />
    <line x1="6" y1="18" x2="6.01" y2="18" />
  </svg>
);
const codeIcon = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </svg>
);

const uavFields: (uavId: number) => FieldDef[] = (uavId) => [
  { id: `stream-port-${uavId}`, label: "STREAM PORT", type: "port", placeholder: uavId === 1 ? "e.g. 5600" : "e.g. 5601", icon: videoIcon },
  { id: `tcp-ip-${uavId}`, label: "TCP IP", type: "ip", placeholder: uavId === 1 ? "e.g. 192.168.1.10" : "e.g. 192.168.1.11", icon: serverIcon },
  { id: `mavlink-port-${uavId}`, label: "MAVLINK PORT", type: "port", placeholder: uavId === 1 ? "e.g. 5761" : "e.g. 5762", icon: portIcon },
  { id: `json-port-${uavId}`, label: "JSON PORT", type: "port", placeholder: uavId === 1 ? "e.g. 5001" : "e.g. 5002", icon: codeIcon },
];

export default function ConnectionSetupModal() {
  const { markConfigured, setUAVConfig } = useGCSStore();
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, boolean>>({});
  const [validationMsg, setValidationMsg] = useState("");
  const [showValidation, setShowValidation] = useState(false);

  const handleChange = useCallback((id: string, val: string) => {
    setValues((prev) => ({ ...prev, [id]: val }));
    setErrors((prev) => ({ ...prev, [id]: false }));
  }, []);

  const handleConnect = useCallback(() => {
    setShowValidation(false);
    const newErrors: Record<string, boolean> = {};
    let firstError = "";

    // Group fields by UAV and check
    const uavValid: (boolean | null)[] = [];

    for (const uavId of [1, 2]) {
      const fields = uavFields(uavId);
      const fieldValues = fields.map((f) => (values[f.id] || "").trim());
      const filledCount = fieldValues.filter((v) => v.length > 0).length;

      if (filledCount === 0) {
        uavValid.push(null); // empty = skip
        continue;
      }

      let groupOk = true;
      for (const field of fields) {
        const val = (values[field.id] || "").trim();
        if (!val) {
          newErrors[field.id] = true;
          groupOk = false;
          if (!firstError) firstError = `${field.label} is required`;
          continue;
        }
        if (field.type === "port") {
          const num = parseInt(val, 10);
          if (isNaN(num) || num < 1 || num > 65535) {
            newErrors[field.id] = true;
            groupOk = false;
            if (!firstError) firstError = `${field.label}: invalid port (1-65535)`;
          }
        }
        if (field.type === "ip") {
          const ipRegex = /^(\d{1,3}\.){3}\d{1,3}$|^[a-zA-Z0-9.-]+$/;
          if (!ipRegex.test(val)) {
            newErrors[field.id] = true;
            groupOk = false;
            if (!firstError) firstError = `${field.label}: invalid IP address`;
          }
        }
      }
      uavValid.push(groupOk);
    }

    setErrors(newErrors);

    const hasErrors = uavValid.some((v) => v === false);
    const anyValid = uavValid.some((v) => v === true);

    if (hasErrors && firstError) {
      setValidationMsg(firstError);
      setShowValidation(true);
      return;
    }
    if (!anyValid) {
      setValidationMsg("Configure at least 1 UAV to continue");
      setShowValidation(true);
      return;
    }

    // Save config for each valid UAV
    for (const uavId of [1, 2] as const) {
      const fields = uavFields(uavId);
      const fieldValues = fields.map((f) => (values[f.id] || "").trim());
      const filledCount = fieldValues.filter((v) => v.length > 0).length;

      if (filledCount === fields.length) {
        const cfg: UAVConnectionConfig = {
          streamPort: values[`stream-port-${uavId}`]!.trim(),
          tcpIp: values[`tcp-ip-${uavId}`]!.trim(),
          mavlinkPort: values[`mavlink-port-${uavId}`]!.trim(),
          jsonPort: values[`json-port-${uavId}`]!.trim(),
        };
        setUAVConfig(uavId, cfg);
      }
    }

    markConfigured();
  }, [values, setUAVConfig, markConfigured]);

  const renderUAVCard = (uavId: number, accent?: string) => {
    const fields = uavFields(uavId);
    return (
      <div className="setup-card" key={uavId}>
        <div className="setup-card-header">
          <div className="setup-card-indicator" style={accent ? { "--card-accent": accent } as React.CSSProperties : undefined} />
          <span className="setup-card-label">UAV {uavId}</span>
          <span className="setup-card-type">FIXED WING</span>
        </div>
        <div className="setup-card-body">
          {fields.map((field) => (
            <div className="setup-field" key={field.id}>
              <label className="setup-field-label" htmlFor={field.id}>
                {field.icon}
                {field.label}
              </label>
              <input
                type={field.type === "port" ? "number" : "text"}
                id={field.id}
                className={`setup-input ${errors[field.id] ? "invalid" : ""}`}
                placeholder={field.placeholder}
                value={values[field.id] || ""}
                onChange={(e) => handleChange(field.id, e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleConnect()}
              />
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="setup-overlay">
      <div className="setup-modal">
        {/* Header */}
        <div className="setup-header">
          <div className="setup-icon">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <h2 className="setup-title">CONNECTION SETUP</h2>
          <p className="setup-subtitle">
            Configure UAV connection parameters before accessing the ground station
          </p>
        </div>

        {/* UAV Cards */}
        <div className="setup-cards">
          {renderUAVCard(1)}
          {renderUAVCard(2, "#40C4FF")}
        </div>

        {/* Validation */}
        {showValidation && (
          <div className="setup-validation">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{validationMsg}</span>
          </div>
        )}

        {/* Action */}
        <div className="setup-actions">
          <button className="setup-btn-primary" onClick={handleConnect}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14" />
              <path d="M12 5l7 7-7 7" />
            </svg>
            CONNECT &amp; ENTER
          </button>
        </div>

        {/* Footer */}
        <div className="setup-footer">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
          </svg>
          Configuration is saved for this session. Reload to reconfigure.
        </div>
      </div>
    </div>
  );
}

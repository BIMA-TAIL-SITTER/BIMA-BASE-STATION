"use client";

import { useCallback, useState } from "react";
import { createEmptyConnectionRecord, UAV_IDS } from "@/config/agents";
import { useGCSStore } from "@/hooks/useGCSStore";
import type { UAVConnectionConfig, UAVId } from "@/types/telemetry";
import UAVConnectionCardGrid, {
  CONNECTION_FIELDS,
  connectionFieldId,
  type ConnectionFieldKey,
} from "./UAVConnectionCardGrid";

function isValidHost(value: string): boolean {
  return /^(\d{1,3}\.){3}\d{1,3}$|^[a-zA-Z0-9.-]+$/.test(value);
}

export default function ConnectionSetupModal() {
  const { markConfigured, setUAVConfig } = useGCSStore();
  const [values, setValues] = useState(createEmptyConnectionRecord);
  const [errors, setErrors] = useState<Record<string, boolean>>({});
  const [validationMsg, setValidationMsg] = useState("");

  const handleChange = useCallback(
    (uavId: UAVId, key: ConnectionFieldKey, value: string) => {
      setValues((current) => ({
        ...current,
        [uavId]: { ...current[uavId], [key]: value },
      }));
      const id = connectionFieldId(uavId, key);
      setErrors((current) => ({ ...current, [id]: false }));
      setValidationMsg("");
    },
    [],
  );

  const handleConnect = useCallback(() => {
    const newErrors: Record<string, boolean> = {};
    const validUAVs: UAVId[] = [];
    let firstError = "";

    for (const uavId of UAV_IDS) {
      const config = values[uavId];
      const filledCount = CONNECTION_FIELDS.filter(
        (field) => config[field.key].trim().length > 0,
      ).length;

      if (filledCount === 0) continue;

      let groupIsValid = true;
      for (const field of CONNECTION_FIELDS) {
        const value = config[field.key].trim();
        const id = connectionFieldId(uavId, field.key);
        if (!value) {
          newErrors[id] = true;
          groupIsValid = false;
          if (!firstError) firstError = `${field.label} is required for UAV ${uavId}`;
          continue;
        }

        if (field.type === "number") {
          const port = Number.parseInt(value, 10);
          if (!Number.isInteger(port) || port < 1 || port > 65535) {
            newErrors[id] = true;
            groupIsValid = false;
            if (!firstError) firstError = `${field.label} must be between 1 and 65535`;
          }
        }

        if (field.key === "tcpIp" && !isValidHost(value)) {
          newErrors[id] = true;
          groupIsValid = false;
          if (!firstError) firstError = `${field.label} is not a valid host`;
        }
      }

      if (groupIsValid) validUAVs.push(uavId);
    }

    setErrors(newErrors);
    if (firstError) {
      setValidationMsg(firstError);
      return;
    }
    if (validUAVs.length === 0) {
      setValidationMsg("Configure at least 1 UAV to continue");
      return;
    }

    for (const uavId of validUAVs) {
      const config: UAVConnectionConfig = {
        streamPort: values[uavId].streamPort.trim(),
        tcpIp: values[uavId].tcpIp.trim(),
        mavlinkPort: values[uavId].mavlinkPort.trim(),
        jsonPort: values[uavId].jsonPort.trim(),
      };
      setUAVConfig(uavId, config);
    }

    markConfigured();
  }, [markConfigured, setUAVConfig, values]);

  return (
    <div className="setup-overlay">
      <div className="setup-modal" role="dialog" aria-modal="true" aria-labelledby="connection-setup-title">
        <div className="setup-header">
          <div className="setup-icon" aria-hidden="true">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <h2 className="setup-title" id="connection-setup-title">CONNECTION SETUP</h2>
          <p className="setup-subtitle">
            Configure one or more UAV links before entering the ground station
          </p>
        </div>

        <UAVConnectionCardGrid
          values={values}
          errors={errors}
          onChange={handleChange}
          onEnter={handleConnect}
        />

        {validationMsg && (
          <div className="setup-validation" role="alert">
            <svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span>{validationMsg}</span>
          </div>
        )}

        <div className="setup-actions">
          <button className="setup-btn-primary" onClick={handleConnect}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 12h14" />
              <path d="M12 5l7 7-7 7" />
            </svg>
            CONNECT &amp; ENTER
          </button>
        </div>

        <div className="setup-footer">
          <svg aria-hidden="true" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 16v-4" />
            <path d="M12 8h.01" />
          </svg>
          Saved connections persist locally and are restored on reload.
        </div>
      </div>
    </div>
  );
}

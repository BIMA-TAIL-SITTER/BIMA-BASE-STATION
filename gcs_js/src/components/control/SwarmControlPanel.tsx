/**
 * SwarmControlPanel — Dual-copter swarm control dashboard.
 *
 * Features:
 *   - Dual mission editors (UAV-3 & UAV-4) with file load/save
 *   - "Upload to Both UAVs" button with per-UAV progress
 *   - Readiness barrier with safety interlocks display
 *   - "Start Coordinated Mission" with confirmation dialog
 *   - Real-time APF collision avoidance status
 *   - Emergency abort button
 *   - Phase state machine display
 */

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { COPTER_IDS, UAV_AGENT_BY_ID } from "@/config/agents";
import { createEmptyMissionItem } from "@/config/mission";
import { useGCSStore } from "@/hooks/useGCSStore";
import type { MissionItem } from "@/types/control";
import type {
  MissionBatchUploadResponse,
  PerUAVUploadStatus,
  SwarmPhase,
  SwarmStatusResponse,
  SwarmStartResponse,
  SwarmAbortResponse,
} from "@/types/swarm";
import type { UAVId } from "@/types/telemetry";
import {
  fetchSwarmStatus,
  uploadBatchMission,
  startSwarmMission,
  abortSwarmMission,
  resetSwarm,
  generateSwarmMission,
  SWARM_API_BASE,
} from "@/lib/swarmApi";
import dynamic from "next/dynamic";
import type { SwarmVehicleMarker } from "@/components/map/SwarmSurveyMap";

const SwarmSurveyMap = dynamic(
  () => import("@/components/map/SwarmSurveyMap").then((mod) => mod.SwarmSurveyMap),
  { ssr: false }
);


function normalizeSequence(items: MissionItem[]): MissionItem[] {
  return items.map((item, index) => ({ ...item, seq: index }));
}

const PHASE_COLORS: Record<string, string> = {
  IDLE: "#6b7280",
  VALIDATING: "#3b82f6",
  UPLOADING: "#f59e0b",
  VERIFYING: "#8b5cf6",
  READY_TO_START: "#10b981",
  STARTING: "#06b6d4",
  ARMING: "#f97316",
  TAKEOFF: "#f97316",
  HOVER_STABILIZING: "#eab308",
  AUTO_RUNNING: "#22c55e",
  COMPLETED: "#10b981",
  PARTIAL_UPLOAD: "#f59e0b",
  DEGRADED: "#ef4444",
  ABORTING: "#ef4444",
  FAILED: "#ef4444",
};

const UPLOAD_STATUS_LABEL: Record<PerUAVUploadStatus, string> = {
  PENDING: "PENDING",
  UPLOADING: "UPLOADING…",
  ACCEPTED: "✓ ACCEPTED",
  REJECTED: "✗ REJECTED",
  TIMEOUT: "⏱ TIMEOUT",
  ERROR: "✗ ERROR",
};

function parseWaypointsFile(text: string): MissionItem[] | null {
  const lines = text.trim().split(/\r?\n/).filter((l) => l.trim() !== "");
  if (!lines[0]?.startsWith("QGC WPL")) return null;
  const items: MissionItem[] = [];
  for (let i = 1; i < lines.length; i++) {
    const cols = lines[i].split("\t");
    if (cols.length < 12) continue;
    items.push({
      seq: parseInt(cols[0], 10),
      current: cols[1] === "1",
      frame: parseInt(cols[2], 10),
      command: parseInt(cols[3], 10),
      param1: parseFloat(cols[4]),
      param2: parseFloat(cols[5]),
      param3: parseFloat(cols[6]),
      param4: parseFloat(cols[7]),
      lat: parseFloat(cols[8]),
      lon: parseFloat(cols[9]),
      alt: parseFloat(cols[10]),
      autocontinue: cols[11] === "1",
    });
  }
  return items.length > 0 ? items : null;
}

export function SwarmControlPanel() {
  // --- State ---
  const [missionA, setMissionA] = useState<MissionItem[]>([]);
  const [missionB, setMissionB] = useState<MissionItem[]>([]);
  const [swarmStatus, setSwarmStatus] = useState<SwarmStatusResponse | null>(null);
  const [uploadResult, setUploadResult] = useState<MissionBatchUploadResponse | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isStarting, setIsStarting] = useState(false);
  const [showStartConfirm, setShowStartConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  
  const { uavs, setSwarmPaths } = useGCSStore();

  // --- Auto-Generate State ---
  type PlanningState = "EMPTY" | "EDITING" | "GENERATING" | "VALID" | "INVALID" | "DIRTY";
  const [planningState, setPlanningState] = useState<PlanningState>("EMPTY");
  const [polygon, setPolygon] = useState<number[][] | null>(null);
  const [altitudeM, setAltitudeM] = useState(30.0);
  const [speedMs, setSpeedMs] = useState(5.0);
  const [laneSpacingM, setLaneSpacingM] = useState(20.0);
  const [safetyMarginM, setSafetyMarginM] = useState(5.0);
  const [sweepAngleDeg, setSweepAngleDeg] = useState<string>(""); 
  
  const [uav3Path, setUav3Path] = useState<number[][]>([]);
  const [uav4Path, setUav4Path] = useState<number[][]>([]);
  const [generationMsg, setGenerationMsg] = useState<string | null>(null);
  const [workloadDiff, setWorkloadDiff] = useState<number | null>(null);
  const [isInitialized, setIsInitialized] = useState(false);
  
  const fileInputA = useRef<HTMLInputElement>(null);
  const fileInputB = useRef<HTMLInputElement>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const agentA = UAV_AGENT_BY_ID[3];
  const agentB = UAV_AGENT_BY_ID[4];

  // --- Vehicle Telemetry for Map Icons ---
  const MAP_CENTER_LAT = -7.77126;
  const MAP_CENTER_LON = 110.37765;
  const [vehicleMarkers, setVehicleMarkers] = useState<SwarmVehicleMarker[]>(() =>
    COPTER_IDS.map((id, idx) => ({
      id,
      lat: MAP_CENTER_LAT + (idx === 0 ? 0.0003 : -0.0003),
      lon: MAP_CENTER_LON + (idx === 0 ? -0.0003 : 0.0003),
      heading: 0,
      altitude: 0,
      mode: "--",
    }))
  );

  // Poll latest telemetry for copter positions
  useEffect(() => {
    const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    let active = true;

    const fetchVehiclePositions = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/telemetry/latest`);
        const data = await res.json();
        if (!active || data.error) return;

        const markers: SwarmVehicleMarker[] = COPTER_IDS.map((id, idx) => {
          const slot = data[`slot_${id}`] || data[String(id)] || {};
          const lat = slot.lat ?? slot.latitude ?? null;
          const lon = slot.lon ?? slot.longitude ?? null;
          return {
            id,
            lat: lat && lat !== 0 ? lat : MAP_CENTER_LAT + (idx === 0 ? 0.0003 : -0.0003),
            lon: lon && lon !== 0 ? lon : MAP_CENTER_LON + (idx === 0 ? -0.0003 : 0.0003),
            heading: slot.heading_deg ?? slot.heading ?? 0,
            altitude: slot.relative_alt_m ?? slot.altitude ?? 0,
            mode: slot.mode ?? slot.flight_mode ?? "--",
          };
        });
        setVehicleMarkers(markers);
      } catch {
        // Silently fail — keep existing markers
      }
    };

    void fetchVehiclePositions();
    const interval = setInterval(fetchVehiclePositions, 2000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);


  // --- Persistence ---
  useEffect(() => {
    const saved = sessionStorage.getItem("bima_swarm_planner_state");
    if (saved) {
      try {
        const s = JSON.parse(saved);
        if (s.missionA && s.missionA.length > 0) setMissionA(s.missionA);
        if (s.missionB && s.missionB.length > 0) setMissionB(s.missionB);
        if (s.planningState && s.planningState !== "EMPTY") setPlanningState(s.planningState);
        if (s.polygon) setPolygon(s.polygon);
        if (s.altitudeM) setAltitudeM(s.altitudeM);
        if (s.speedMs) setSpeedMs(s.speedMs);
        if (s.laneSpacingM) setLaneSpacingM(s.laneSpacingM);
        if (s.safetyMarginM !== undefined) setSafetyMarginM(s.safetyMarginM);
        if (s.sweepAngleDeg !== undefined) setSweepAngleDeg(s.sweepAngleDeg);
        if (s.uav3Path && s.uav3Path.length > 0) setUav3Path(s.uav3Path);
        if (s.uav4Path && s.uav4Path.length > 0) setUav4Path(s.uav4Path);
        if (s.generationMsg) setGenerationMsg(s.generationMsg);
        if (s.workloadDiff !== undefined) setWorkloadDiff(s.workloadDiff);
      } catch (e) {
        console.error("Failed to restore swarm state", e);
      }
    }
    setIsInitialized(true);
  }, []);

  useEffect(() => {
    if (!isInitialized) return;
    
    const state = {
      missionA, missionB, planningState, polygon,
      altitudeM, speedMs, laneSpacingM, safetyMarginM, sweepAngleDeg,
      uav3Path, uav4Path, generationMsg, workloadDiff
    };
    sessionStorage.setItem("bima_swarm_planner_state", JSON.stringify(state));
  }, [
    missionA, missionB, planningState, polygon,
    altitudeM, speedMs, laneSpacingM, safetyMarginM, sweepAngleDeg,
    uav3Path, uav4Path, generationMsg, workloadDiff, isInitialized
  ]);

  // --- Polling ---
  const pollStatus = useCallback(async () => {
    try {
      const status = await fetchSwarmStatus();
      setSwarmStatus(status);
    } catch {
      // Silently fail polling
    }
  }, []);

  useEffect(() => {
    void pollStatus();
    pollRef.current = setInterval(pollStatus, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [pollStatus]);

  // --- File Handlers ---
  const handleLoadFile = useCallback(
    (setter: typeof setMissionA, pathSetter: typeof setUav3Path) =>
      (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (evt) => {
          const text = evt.target?.result as string;
          const items = parseWaypointsFile(text);
          if (items) {
            const normalized = normalizeSequence(items);
            setter(normalized);
            const path = normalized.filter((i) => i.lat !== 0 && i.lon !== 0).map((i) => [i.lat, i.lon]);
            pathSetter(path);
            setNotice(`Loaded ${items.length} waypoints from ${file.name}`);
            setError(null);
            setPlanningState("DIRTY");
          } else {
            setError("Invalid .waypoints file format.");
          }
        };
        reader.readAsText(file);
        e.target.value = "";
      },
    [],
  );

  // --- Auto-Generate ---
  const handleGenerate = async () => {
    if (!polygon || polygon.length < 3) {
      setError("Please draw a valid polygon on the map.");
      return;
    }
    
    setPlanningState("GENERATING");
    setError(null);
    setGenerationMsg(null);
    
    try {
      const payload = {
        area: { vertices: polygon },
        altitude_m: altitudeM,
        speed_ms: speedMs,
        lane_spacing_m: laneSpacingM,
        safety_margin_m: safetyMarginM,
        sweep_angle_deg: sweepAngleDeg === "" ? null : parseFloat(sweepAngleDeg),
        min_horizontal_sep_m: 10.0
      };
      
      const data = await generateSwarmMission(payload);
      
      if (data.success) {
        setMissionA(data.uav_3_route.mission_items);
        setMissionB(data.uav_4_route.mission_items);
        setUav3Path(data.uav_3_route.mission_items.map((i: any) => [i.lat, i.lon]));
        setUav4Path(data.uav_4_route.mission_items.map((i: any) => [i.lat, i.lon]));
        setWorkloadDiff(data.workload_difference_pct);
        setGenerationMsg(data.message);
        setPlanningState(data.predicted_conflicts.length > 0 ? "INVALID" : "VALID");
        
        if (data.predicted_conflicts.length > 0) {
          setError(`Conflict detected! Min separation: ${data.min_horizontal_sep_m.toFixed(1)}m. Upload blocked.`);
        }
      } else {
        setError(data.error || data.message || "Generation failed.");
        setPlanningState("INVALID");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "API request failed");
      setPlanningState("INVALID");
    }
  };

  const handlePolygonChange = useCallback((vertices: number[][]) => {
    setPolygon(vertices);
    setPlanningState("EDITING");
  }, []);


  // --- Upload Both ---
  const handleUploadBoth = async () => {
    if (!missionA.length || !missionB.length) {
      setError("Both UAV missions must have at least 1 waypoint.");
      return;
    }
    setIsUploading(true);
    setError(null);
    setNotice(null);
    setUploadResult(null);
    try {
      const uav3 = uavs[3];
      const uav4 = uavs[4];
      
      const result = await uploadBatchMission({
        mission_uav_3: normalizeSequence(missionA),
        mission_uav_4: normalizeSequence(missionB),
        ip_3: uav3?.raspiIp,
        port_3: uav3?.missionUdpPort ? parseInt(uav3.missionUdpPort) : undefined,
        ip_4: uav4?.raspiIp,
        port_4: uav4?.missionUdpPort ? parseInt(uav4.missionUdpPort) : undefined,
      });
      setUploadResult(result);
      if (result.ready_to_start) {
        setNotice("Both missions accepted — READY TO START");
        // Publish to main map after a successful upload so the operator sees the plan before starting
        const p3 = missionA.filter(i => i.lat !== 0 && i.lon !== 0).map(i => [i.lat, i.lon]);
        const p4 = missionB.filter(i => i.lat !== 0 && i.lon !== 0).map(i => [i.lat, i.lon]);
        if (p3.length > 0 || p4.length > 0) {
          setSwarmPaths({ uav3Path: p3, uav4Path: p4 });
        }
      } else {
        setError(result.message);
      }
      void pollStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setIsUploading(false);
    }
  };

  // --- Start ---
  const handleStart = async () => {
    setShowStartConfirm(false);
    setIsStarting(true);
    setError(null);
    try {
      const uav3 = uavs[3];
      const uav4 = uavs[4];
      
      const result = await startSwarmMission({ 
        confirmation: "CONFIRM_START",
        ip_3: uav3?.raspiIp,
        port_3: uav3?.missionUdpPort ? parseInt(uav3.missionUdpPort) : undefined,
        ip_4: uav4?.raspiIp,
        port_4: uav4?.missionUdpPort ? parseInt(uav4.missionUdpPort) : undefined,
      });
      if (result.accepted) {
        setNotice("Coordinated start accepted — mission running");
        // Publish swarm paths to global store for main map display
        const p3 = missionA.filter(i => i.lat !== 0 && i.lon !== 0).map(i => [i.lat, i.lon]);
        const p4 = missionB.filter(i => i.lat !== 0 && i.lon !== 0).map(i => [i.lat, i.lon]);
        if (p3.length > 0 || p4.length > 0) {
          setSwarmPaths({ uav3Path: p3, uav4Path: p4 });
        }
      } else {
        setError(result.message);
      }
      void pollStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Start failed");
    } finally {
      setIsStarting(false);
    }
  };

  // --- Abort ---
  const handleAbort = async () => {
    setError(null);
    try {
      const result = await abortSwarmMission({ reason: "User emergency abort" });
      setNotice(`Abort: ${result.message}`);
      void pollStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Abort failed");
    }
  };

  // --- Reset ---
  const handleReset = async () => {
    setError(null);
    setNotice(null);
    setUploadResult(null);
    try {
      await resetSwarm();
      setNotice("Swarm state reset to IDLE");
      void pollStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    }
  };

  const phase = swarmStatus?.phase ?? "IDLE";
  const phaseColor = PHASE_COLORS[phase] ?? "#6b7280";
  const readyToStart = swarmStatus?.ready_to_start ?? false;
  const apf = swarmStatus?.apf;

  return (
    <div className="swarm-control-panel">
      {/* ─── Phase Banner ─── */}
      <section className="swarm-phase-banner" style={{ borderColor: phaseColor }}>
        <div className="swarm-phase-indicator" style={{ background: phaseColor }} />
        <div className="swarm-phase-text">
          <strong>SWARM PHASE</strong>
          <span>{phase.replace(/_/g, " ")}</span>
        </div>
        <div className="swarm-phase-actions">
          <button
            type="button"
            className="operations-button is-danger swarm-abort-btn"
            onClick={handleAbort}
            disabled={phase === "IDLE"}
          >
            ⚠ ABORT
          </button>
          <button
            type="button"
            className="operations-button"
            onClick={handleReset}
          >
            ↺ RESET
          </button>
        </div>
      </section>

      {/* ─── Messages ─── */}
      {(error || notice) && (
        <div className={`operations-message ${error ? "is-error" : "is-ok"}`} role={error ? "alert" : "status"}>
          {error || notice}
        </div>
      )}

      {/* ─── APF Status ─── */}
      {apf && (phase === "AUTO_RUNNING" || phase === "ARMING" || phase === "TAKEOFF" || phase === "HOVER_STABILIZING") && (
        <section className="swarm-apf-panel">
          <h3>COLLISION AVOIDANCE (APF)</h3>
          <div className="swarm-apf-grid">
            <div className="swarm-apf-metric">
              <span className="swarm-apf-label">DISTANCE</span>
              <span className={`swarm-apf-value ${apf.d_ij < 10 ? "is-warning" : ""}`}>
                {apf.d_ij === Infinity ? "—" : `${apf.d_ij.toFixed(1)} m`}
              </span>
            </div>
            <div className="swarm-apf-metric">
              <span className="swarm-apf-label">PREDICTED MIN</span>
              <span className={`swarm-apf-value ${apf.d_cpa < 10 ? "is-warning" : ""}`}>
                {apf.d_cpa === Infinity ? "—" : `${apf.d_cpa.toFixed(1)} m`}
              </span>
            </div>
            <div className="swarm-apf-metric">
              <span className="swarm-apf-label">TIME TO CPA</span>
              <span className="swarm-apf-value">{apf.t_cpa.toFixed(1)} s</span>
            </div>
            <div className="swarm-apf-metric">
              <span className="swarm-apf-label">AVOIDANCE</span>
              <span className={`swarm-apf-value ${apf.active ? "is-active" : ""}`}>
                {apf.active ? "⚡ ACTIVE" : "STANDBY"}
              </span>
            </div>
          </div>
          {apf.stale && (
            <div className="operations-message is-error">⚠ STALE TELEMETRY — APF degraded</div>
          )}
        </section>
      )}

      {/* ─── Safety Interlocks ─── */}
      {swarmStatus && swarmStatus.interlock_failures.length > 0 && (
        <section className="swarm-interlocks">
          <h3>⚠ SAFETY INTERLOCKS FAILED</h3>
          <ul>
            {swarmStatus.interlock_failures.map((f, i) => (
              <li key={i}>{f}</li>
            ))}
          </ul>
        </section>
      )}

      {/* ─── Mission Auto-Generation ─── */}
      <section className="swarm-survey-planner" style={{ marginTop: "1rem", padding: "1rem", background: "#1f2937", borderRadius: "8px" }}>
        <h3>MISSION AUTO-GENERATION</h3>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: "1rem", marginTop: "1rem" }}>
          <div>
            <SwarmSurveyMap 
              onPolygonCreated={handlePolygonChange}
              onPolygonEdited={handlePolygonChange}
              onPolygonDeleted={() => { setPolygon(null); setPlanningState("EMPTY"); }}
              uav3Path={uav3Path}
              uav4Path={uav4Path}
              vehicles={vehicleMarkers}
            />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            <label>
              Altitude (m):
              <input type="number" value={altitudeM} onChange={e => {setAltitudeM(parseFloat(e.target.value)); setPlanningState("DIRTY");}} style={{ width: "100%", padding: "4px", marginTop: "4px" }} />
            </label>
            <label>
              Speed (m/s):
              <input type="number" value={speedMs} onChange={e => {setSpeedMs(parseFloat(e.target.value)); setPlanningState("DIRTY");}} style={{ width: "100%", padding: "4px", marginTop: "4px" }} />
            </label>
            <label>
              Lane Spacing (m):
              <input type="number" value={laneSpacingM} onChange={e => {setLaneSpacingM(parseFloat(e.target.value)); setPlanningState("DIRTY");}} style={{ width: "100%", padding: "4px", marginTop: "4px" }} />
            </label>
            <label>
              Safety Margin (m):
              <input type="number" value={safetyMarginM} onChange={e => {setSafetyMarginM(parseFloat(e.target.value)); setPlanningState("DIRTY");}} style={{ width: "100%", padding: "4px", marginTop: "4px" }} />
            </label>
            <label>
              Sweep Angle (deg, optional):
              <input type="text" placeholder="Auto" value={sweepAngleDeg} onChange={e => {setSweepAngleDeg(e.target.value); setPlanningState("DIRTY");}} style={{ width: "100%", padding: "4px", marginTop: "4px" }} />
            </label>
            
            <button 
              type="button" 
              className="operations-button is-primary" 
              style={{ marginTop: "1rem", width: "100%" }}
              disabled={!polygon || planningState === "GENERATING"}
              onClick={handleGenerate}
            >
              {planningState === "GENERATING" ? "GENERATING..." : "GENERATE WAYPOINTS"}
            </button>
            
            {generationMsg && (
              <div style={{ fontSize: "12px", color: planningState === "VALID" ? "#10b981" : "#ef4444", marginTop: "4px" }}>
                {generationMsg}
                {workloadDiff !== null && <br/>}
                {workloadDiff !== null && `Workload Diff: ${workloadDiff.toFixed(1)}%`}
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ─── Dual Mission Editors ─── */}
      <div className="swarm-dual-editor">
        {/* UAV-3 */}
        <section className="swarm-uav-section" style={{ borderColor: agentA.color }}>
          <header>
            <div className="swarm-uav-header">
              <span className="swarm-uav-dot" style={{ background: agentA.color }} />
              <strong>{agentA.shortLabel}</strong>
              <span className="swarm-uav-wp-count">{missionA.length} WP</span>
            </div>
            <div className="swarm-uav-upload-status">
              {swarmStatus && (
                <span className={`swarm-upload-badge ${swarmStatus.uav_3_upload === "ACCEPTED" ? "is-ok" : swarmStatus.uav_3_upload === "PENDING" ? "" : "is-error"}`}>
                  {UPLOAD_STATUS_LABEL[swarmStatus.uav_3_upload]}
                </span>
              )}
            </div>
          </header>
          <div className="swarm-uav-actions">
            <button
              type="button"
              className="operations-button"
              onClick={() => fileInputA.current?.click()}
              style={{ fontSize: "10px", padding: "4px 10px" }}
            >
              📂 LOAD .waypoints
            </button>
            <input ref={fileInputA} type="file" accept=".waypoints" style={{ display: "none" }} onChange={handleLoadFile(setMissionA, setUav3Path)} />
          </div>
          {missionA.length > 0 && (
            <div className="swarm-wp-list">
              {missionA.map((wp, i) => (
                <div key={i} className="swarm-wp-row">
                  <span className="swarm-wp-seq">{wp.seq}</span>
                  <span className="swarm-wp-coord">{wp.lat.toFixed(6)}, {wp.lon.toFixed(6)}</span>
                  <span className="swarm-wp-alt">{wp.alt}m</span>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* UAV-4 */}
        <section className="swarm-uav-section" style={{ borderColor: agentB.color }}>
          <header>
            <div className="swarm-uav-header">
              <span className="swarm-uav-dot" style={{ background: agentB.color }} />
              <strong>{agentB.shortLabel}</strong>
              <span className="swarm-uav-wp-count">{missionB.length} WP</span>
            </div>
            <div className="swarm-uav-upload-status">
              {swarmStatus && (
                <span className={`swarm-upload-badge ${swarmStatus.uav_4_upload === "ACCEPTED" ? "is-ok" : swarmStatus.uav_4_upload === "PENDING" ? "" : "is-error"}`}>
                  {UPLOAD_STATUS_LABEL[swarmStatus.uav_4_upload]}
                </span>
              )}
            </div>
          </header>
          <div className="swarm-uav-actions">
            <button
              type="button"
              className="operations-button"
              onClick={() => fileInputB.current?.click()}
              style={{ fontSize: "10px", padding: "4px 10px" }}
            >
              📂 LOAD .waypoints
            </button>
            <input ref={fileInputB} type="file" accept=".waypoints" style={{ display: "none" }} onChange={handleLoadFile(setMissionB, setUav4Path)} />
          </div>
          {missionB.length > 0 && (
            <div className="swarm-wp-list">
              {missionB.map((wp, i) => (
                <div key={i} className="swarm-wp-row">
                  <span className="swarm-wp-seq">{wp.seq}</span>
                  <span className="swarm-wp-coord">{wp.lat.toFixed(6)}, {wp.lon.toFixed(6)}</span>
                  <span className="swarm-wp-alt">{wp.alt}m</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      {/* ─── Action Buttons ─── */}
      <div style={{ display: "flex", gap: "12px", marginTop: "16px", marginBottom: "16px" }}>
        <button
          type="button"
          className="operations-button"
          onClick={handleUploadBoth}
          disabled={isUploading || !missionA.length || !missionB.length || planningState === "INVALID" || planningState === "DIRTY"}
          style={{ flex: 1, padding: "12px", fontSize: "14px", fontWeight: 600, letterSpacing: "0.5px" }}
        >
          {isUploading ? "UPLOADING..." : "UPLOAD MISSION"}
        </button>

        <button
          type="button"
          className="operations-button is-primary"
          onClick={() => setShowStartConfirm(true)}
          disabled={!readyToStart || isStarting}
          style={{ 
            flex: 1, 
            padding: "12px", 
            fontSize: "14px", 
            fontWeight: 600, 
            letterSpacing: "0.5px",
            opacity: (!readyToStart || isStarting) ? 0.5 : 1
          }}
        >
          {isStarting ? "STARTING..." : "START MISSION"}
        </button>
      </div>

      {/* ─── Upload Results ─── */}
      {uploadResult && (
        <section className="swarm-upload-results">
          <h3>UPLOAD RESULTS</h3>
          <div className="swarm-upload-results-grid">
            <div>
              <strong>{agentA.shortLabel}:</strong> {uploadResult.uav_3.message}
            </div>
            <div>
              <strong>{agentB.shortLabel}:</strong> {uploadResult.uav_4.message}
            </div>
          </div>
        </section>
      )}

      {/* ─── Start Confirmation Dialog ─── */}
      {showStartConfirm && (
        <div
          className="operations-dialog-backdrop"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setShowStartConfirm(false);
          }}
        >
          <section className="operations-dialog" role="dialog" aria-modal="true">
            <span className="operations-dialog-warning">CONFIRM START</span>
            <h2>START COORDINATED MISSION?</h2>
            <p>
              Both UAVs will ARM, TAKEOFF, stabilize in HOVER, then switch
              to AUTO mode. APF collision avoidance will be active during flight.
            </p>
            {swarmStatus && swarmStatus.interlock_failures.length > 0 && (
              <div className="operations-message is-error" style={{ marginBottom: 12 }}>
                ⚠ {swarmStatus.interlock_failures.length} interlock(s) failed — start blocked
              </div>
            )}
            <div className="operations-dialog-actions">
              <button
                type="button"
                className="operations-button is-secondary"
                onClick={() => setShowStartConfirm(false)}
              >
                CANCEL
              </button>
              <button
                type="button"
                className="operations-button is-primary"
                onClick={handleStart}
                disabled={!readyToStart}
                style={{ background: "#10b981" }}
              >
                CONFIRM START
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}

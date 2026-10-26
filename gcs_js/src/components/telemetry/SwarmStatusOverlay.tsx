/**
 * SwarmStatusOverlay — Real-time swarm status panel for the main dashboard.
 *
 * Uses live dashboard telemetry for distance and polls /api/swarm/status every 2 seconds for:
 *   - Swarm phase indicator
 *   - Predicted closest approach (d_cpa)
 *   - Time to CPA
 *   - APF avoidance status
 *   - Compact per-UAV telemetry cards
 *
 * Collapses to a slim pill when IDLE, expands when swarming is active.
 */

"use client";

import { memo, useEffect, useState, type ReactNode } from "react";
import { UAV_AGENT_BY_ID } from "@/config/agents";
import { fetchSwarmStatus } from "@/lib/swarmApi";
import type { SwarmStatusResponse } from "@/types/swarm";
import type { MavlinkStatus, TelemetryData } from "@/types/telemetry";
import { getInterUavDistance } from "@/utils/interUavDistance";
import { useSwarmMission } from "@/components/swarm/SwarmMissionContext";

const POLL_INTERVAL_MS = 2000;

/** Phase is considered "active" when the swarm is doing something non-trivial. */
function isActivePhase(phase: string): boolean {
  return ![
    "IDLE",
    "COMPLETED",
    "FAILED",
  ].includes(phase);
}

const PHASE_COLORS: Record<string, string> = {
  IDLE: "var(--text-muted)", DRAFT: "var(--text-muted)", DISCONNECTED: "var(--text-muted)",
  VALIDATING: "var(--info)", VERIFYING: "var(--info)", STARTING: "var(--info)", APPENDING: "var(--warning)",
  UPLOADING: "var(--warning)", PARTIAL_UPLOAD: "var(--warning)", PARTIAL: "var(--warning)",
  ARMING: "var(--warning)", TAKEOFF: "var(--warning)", HOVER_STABILIZING: "var(--warning)",
  PREPARING: "var(--warning)", HELD: "var(--warning)",
  READY_TO_START: "var(--success)", UPLOADED: "var(--success)", ACTIVE: "var(--success)",
  AUTO_RUNNING: "var(--success)", COMPLETED: "var(--success)",
  DEGRADED: "var(--danger)", ABORTING: "var(--danger)", FAILED: "var(--danger)",
  HOLD_REQUIRED: "var(--danger)", RECOVERY_REQUIRED: "var(--danger)",
};

const PHASE_LABELS: Record<string, string> = {
  IDLE: "Siaga", DRAFT: "Draft", DISCONNECTED: "Terputus", UPLOADING: "Mengunggah", APPENDING: "Sinkronisasi WP",
  UPLOADED: "Terunggah", READY_TO_START: "Siap mulai", PREPARING: "Persiapan",
  STARTING: "Memulai", PRECHECK: "Precheck", ARMING: "Arming", TAKEOFF: "Takeoff",
  HOVER_STABILIZING: "Stabilisasi", ACTIVE: "Aktif", AUTO_RUNNING: "Aktif",
  AVAILABLE: "Tersedia", BUSY: "Bertugas", HELD: "Ditahan", HOLD_REQUIRED: "Perlu ditahan",
  RECOVERY_REQUIRED: "Pemulihan", RESUMING: "Melanjutkan", ENDING: "Mengakhiri",
  COMPLETED: "Selesai", ABORTING: "Menghentikan", ABORTED: "Dihentikan",
  FAILED: "Gagal", FAULT: "Gangguan", PARTIAL: "Upload parsial", PARTIAL_UPLOAD: "Upload parsial",
  FAILED_UPLOAD: "Upload gagal", FINISHED_HOLD: "Tahan akhir",
};
const PLAN_LABELS: Record<string, string> = {
  UAV_ACK: "Plan ✓", ACCEPTED: "Plan ✓", SERVER_ACCEPTED: "Plan dikirim", UPLOADING: "Upload plan",
  FAILED: "Plan gagal", ERROR: "Plan gagal", REJECTED: "Plan ditolak", TIMEOUT: "Plan timeout", UNKNOWN: "Plan belum pasti",
};

interface SwarmStatusOverlayProps {
  children?: ReactNode;
  telemetry3: TelemetryData | null;
  telemetry4: TelemetryData | null;
  mavlinkStatus3: MavlinkStatus;
  mavlinkStatus4: MavlinkStatus;
}

function SwarmStatusOverlayInner({
  children,
  telemetry3,
  telemetry4,
  mavlinkStatus3,
  mavlinkStatus4,
}: SwarmStatusOverlayProps) {
  const dispatch = useSwarmMission();
  const useDispatch = Boolean(dispatch.state?.plan.mission_id);
  const [status, setStatus] = useState<SwarmStatusResponse | null>(null);
  const [collapsedPhase, setCollapsedPhase] = useState<string | null>(null);
  const [pollError, setPollError] = useState(false);
  useEffect(() => {
    if (useDispatch) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const data = await fetchSwarmStatus();
        if (!disposed) {
          setStatus(data);
          setPollError(false);
        }
      } catch {
        if (!disposed) setPollError(true);
      } finally {
        if (!disposed) timer = setTimeout(poll, POLL_INTERVAL_MS);
      }
    };
    timer = setTimeout(poll, 0);
    return () => {
      disposed = true;
      clearTimeout(timer);
    };
  }, [useDispatch]);

  const phase = useDispatch ? dispatch.connected ? dispatch.state?.phase : "DISCONNECTED" : status?.phase;
  const phaseLabel = phase ? PHASE_LABELS[phase] ?? phase.replace(/_/g, " ") : pollError ? "Terputus" : "Memuat…";
  const drone3 = dispatch.state?.drones.find(d => d.drone_id === 3);
  const drone4 = dispatch.state?.drones.find(d => d.drone_id === 4);
  const apf = useDispatch ? {
    active: Boolean(drone3?.apf?.active || drone4?.apf?.active),
    d_cpa: drone3?.apf?.d_cpa ?? -1, t_cpa: drone3?.apf?.t_cpa ?? -1,
    uav_3_offset_m: drone3?.apf?.offset_m ?? 0, uav_4_offset_m: drone4?.apf?.offset_m ?? 0,
    uav_3_avoidance_active: drone3?.apf?.active, uav_4_avoidance_active: drone4?.apf?.active,
    stale: !dispatch.connected || !drone3?.connected || !drone4?.connected
      || (drone3.position_age_s ?? Infinity) > 2 || (drone4.position_age_s ?? Infinity) > 2,
  } : status?.apf;
  const phaseColor = phase ? PHASE_COLORS[phase] ?? "var(--text-muted)" : "var(--text-muted)";
  const isRunning = phase !== undefined && ["ACTIVE", "PREPARING", "AUTO_RUNNING", "ARMING", "TAKEOFF", "HOVER_STABILIZING", "STARTING"].includes(phase);
  // A new active phase reopens a collapsed panel without coupling distance to polling.
  const isExpanded = collapsedPhase === null
    || (phase !== undefined && isActivePhase(phase) && phase !== collapsedPhase);

  const dij = useDispatch ? getInterUavDistance(
    { slot: 3, lat: drone3?.lat, lon: drone3?.lon, altitude_m: drone3?.alt_msl_m, gps_fix: drone3?.gps_fix },
    { slot: 4, lat: drone4?.lat, lon: drone4?.lon, altitude_m: drone4?.alt_msl_m, gps_fix: drone4?.gps_fix },
    apf?.stale ? "DISCONNECTED" : drone3?.armed ? "ARMED" : "DISARMED",
    apf?.stale ? "DISCONNECTED" : drone4?.armed ? "ARMED" : "DISARMED",
  ) : getInterUavDistance(telemetry3, telemetry4, mavlinkStatus3, mavlinkStatus4);
  const dijDisplay = dij === null ? null : dij.toFixed(1);
  const dijSeverity = dij === null ? "unavailable" : dij < 10 ? "danger" : dij < 20 ? "warning" : "nominal";

  const dcpa = apf?.d_cpa ?? -1;
  const hasPrediction = dij !== null && !(useDispatch ? !dispatch.connected : pollError) && !apf?.stale && Number.isFinite(dcpa) && dcpa >= 0;
  const dcpaDisplay = hasPrediction ? dcpa.toFixed(1) : null;
  const dcpaSeverity = dcpa >= 0 && dcpa < 10 ? "danger" : dcpa >= 0 && dcpa < 20 ? "warning" : "nominal";

  const tcpa = apf?.t_cpa ?? -1;
  const tcpaDisplay = hasPrediction && Number.isFinite(tcpa) && tcpa >= 0 ? tcpa.toFixed(1) : null;
  const apfActive = apf?.active ?? false;
  const apfLabel = hasPrediction ? apfActive ? "Aktif" : "Siaga" : apf?.stale ? "Data usang" : "Menunggu";

  return (
    <div
      className={`swarm-overlay ${isExpanded ? "is-expanded" : "is-collapsed"} ${isRunning ? "is-running" : ""}`}
      aria-label="Swarm status overlay"
    >
      {/* ─── Pill Header (always visible) ─── */}
      <button
        type="button"
        className="swarm-overlay-pill"
        onClick={() => setCollapsedPhase(isExpanded ? phase ?? "LOADING" : null)}
        aria-expanded={isExpanded}
        aria-label={`Status swarm: ${phaseLabel}. ${isExpanded ? "Lipat" : "Buka"} panel.`}
      >
        <span
          className={`swarm-overlay-dot ${isRunning ? "is-pulsing" : ""}`}
          style={{ background: phaseColor }}
        />
        <span className="swarm-overlay-pill-text">SWARM</span>
        <span className="swarm-overlay-pill-phase" style={{ color: phaseColor }}>
          {phaseLabel}
        </span>
        <span className={`swarm-overlay-chevron ${isExpanded ? "is-open" : ""}`}>
          ‹
        </span>
      </button>

      {/* ─── Expanded Panel ─── */}
      {isExpanded && (
        <div className="swarm-overlay-body">
          <section className="operations-section swarm-distance-widget" aria-label="Jarak antar-drone dan APF">
            <div className="swarm-distance-readout">
              <span className="copter-metric-label">Jarak GPS 3D</span>
              <span className={`swarm-overlay-metric-value swarm-distance-primary is-${dijSeverity}`}>
                {dijDisplay === null ? <span className="swarm-metric-empty">Menunggu GPS</span> : <>{dijDisplay}<small> m</small></>}
              </span>
            </div>
            <div className="swarm-distance-readout" title={dcpaDisplay === null ? "Prediksi tersedia setelah telemetry kedua UAV valid." : "Prediksi jarak terdekat antar-drone"}>
              <span className="copter-metric-label">Min. prediksi</span>
              <span className={`swarm-overlay-metric-value ${hasPrediction ? `is-${dcpaSeverity}` : ""}`}>
                {dcpaDisplay !== null ? <>{dcpaDisplay}<small> m</small></> : <span className="swarm-metric-empty">Belum tersedia</span>}
              </span>
            </div>
            <div className="swarm-distance-readout" title={tcpaDisplay === null ? "Waktu CPA belum tersedia." : "Waktu menuju prediksi jarak terdekat"}>
              <span className="copter-metric-label">Waktu CPA</span>
              <span className="swarm-overlay-metric-value">
                {tcpaDisplay !== null ? <>{tcpaDisplay}<small> s</small></> : <span className="swarm-metric-empty">Belum tersedia</span>}
              </span>
            </div>
            <div className="swarm-distance-readout">
              <span className="copter-metric-label">APF</span>
              <span className={`mavlink-status swarm-chip ${hasPrediction ? apfActive ? "is-disarmed" : "is-armed" : ""}`}
                title={hasPrediction ? "Status penghindaran tabrakan dari telemetry aktual." : "Menunggu data APF terbaru dari kedua UAV."}>{apfLabel}</span>
            </div>
          </section>

          {([3, 4] as const).map(slot => {
            const agent = UAV_AGENT_BY_ID[slot];
            const drone = slot === 3 ? drone3 : drone4;
            const telemetry = slot === 3 ? telemetry3 : telemetry4;
            const mavlinkStatus = slot === 3 ? mavlinkStatus3 : mavlinkStatus4;
            const online = useDispatch ? dispatch.connected && Boolean(drone?.connected) : mavlinkStatus !== "DISCONNECTED";
            const heartbeatFresh = online && (!useDispatch || (drone?.heartbeat_age_s != null && drone.heartbeat_age_s <= 2));
            const positionFresh = online && (!useDispatch || (drone?.position_age_s != null && drone.position_age_s <= 2));
            const armed = useDispatch ? drone?.armed : telemetry?.armed;
            const gps = useDispatch ? drone?.gps_fix : telemetry?.gps_fix;
            const battery = useDispatch ? drone?.battery_pct : telemetry?.battery_remaining_pct;
            const mode = useDispatch ? drone?.mode : telemetry?.flight_mode;
            const flight = useDispatch ? drone?.phase : slot === 3 ? status?.uav_3_flight : status?.uav_4_flight;
            const plan = useDispatch ? dispatch.state?.upload[String(slot)] : slot === 3 ? status?.uav_3_upload : status?.uav_4_upload;
            const lat = useDispatch ? drone?.lat : telemetry?.lat;
            const lon = useDispatch ? drone?.lon : telemetry?.lon;
            const altitude = useDispatch ? drone?.alt_m : telemetry?.relative_alt_m;
            const distance = useDispatch ? drone?.distance_to_target_m : telemetry?.distance_to_wp_m;
            const offset = slot === 3 ? apf?.uav_3_offset_m : apf?.uav_4_offset_m;
            const command = dispatch.state?.commands[String(slot)];
            const hasPosition = positionFresh && Number.isFinite(lat) && Number.isFinite(lon)
              && Math.abs(lat!) <= 90 && Math.abs(lon!) <= 180 && (lat !== 0 || lon !== 0);
            const planAccepted = plan === "UAV_ACK" || plan === "ACCEPTED";
            return <section key={slot} className="operations-section swarm-mission-drone" aria-label={agent.shortLabel}>
              <div className="swarm-drone-heading">
                <strong><span className="swarm-overlay-uav-dot" style={{ background: agent.color }} aria-hidden="true" />{agent.shortLabel}</strong>
                <span className={`mavlink-status swarm-chip ${online ? "is-armed" : "is-disconnected"}`}>{online ? "Terhubung" : "Terputus"}</span>
              </div>
              {(heartbeatFresh || online || (plan && PLAN_LABELS[plan])) && <div className="swarm-drone-chips">
                {heartbeatFresh && typeof armed === "boolean" && <span className={`mavlink-status swarm-chip ${armed ? "is-armed" : "is-disarmed"}`}>{armed ? "ARMED" : "DISARMED"}</span>}
                {online && !positionFresh ? <span className="mavlink-status swarm-chip is-disarmed" title="Posisi terakhir belum cukup fresh untuk penugasan.">GPS usang</span>
                  : online && Number.isFinite(gps) && <span className={`mavlink-status swarm-chip ${gps! >= 3 ? "is-armed" : "is-disarmed"}`} title={`GPS fix: ${gps}`}>{gps! >= 3 ? "GPS 3D" : gps === 2 ? "GPS 2D" : "GPS tanpa fix"}</span>}
                {heartbeatFresh && Number.isFinite(battery) && battery! >= 0 && battery! <= 100 && <span className={`mavlink-status swarm-chip ${battery! <= 20 ? "is-disconnected" : battery! <= 30 ? "is-disarmed" : ""}`}>Baterai {battery}%</span>}
                {plan && PLAN_LABELS[plan] && <span className={`mavlink-status swarm-chip ${planAccepted ? "is-armed" : ["SERVER_ACCEPTED", "UPLOADING"].includes(plan) ? "is-disarmed" : "is-disconnected"}`}
                  title={`${useDispatch ? `Plan v${dispatch.state?.plan.version}` : "Plan legacy"}: ${plan}`}>{PLAN_LABELS[plan]}</span>}
              </div>}
              {heartbeatFresh && (mode || flight) && <div className="swarm-drone-detail">
                {mode && mode !== "--" && <span>{mode}</span>}
                {flight && <span>{PHASE_LABELS[flight] ?? flight}</span>}
              </div>}
              {hasPosition && <div className="swarm-drone-detail swarm-drone-position" title={useDispatch ? `Usia posisi ${drone?.position_age_s?.toFixed(1)} s` : "Posisi GPS terbaru"}>
                <span>{lat!.toFixed(6)}, {lon!.toFixed(6)}</span>
                {Number.isFinite(altitude) && <span>{altitude!.toFixed(1)} m</span>}
                {Number.isFinite(distance) && distance! >= 0 && <span>Target {distance!.toFixed(1)} m</span>}
              </div>}
              {hasPrediction && Number.isFinite(offset) && offset !== 0 && <span className="swarm-drone-detail">Offset APF {offset!.toFixed(1)} m</span>}
              {(drone?.error || command?.error) && <span className="mavlink-status swarm-chip is-disconnected" title={drone?.error || command?.error}>Periksa log</span>}
              {command && command.operation !== "PLAN_SYNC" && !command.error && <span className="swarm-drone-detail" title={`${command.operation}: ${command.status}`}>
                {command.status === "UAV_ACK" ? "Perintah diakui" : "Menunggu ACK"}
              </span>
              }
            </section>;
          })}
          {children}
        </div>
      )}
    </div>
  );
}

export const SwarmStatusOverlay = memo(SwarmStatusOverlayInner);

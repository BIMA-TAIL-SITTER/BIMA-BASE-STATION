"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSwarmMission } from "./SwarmMissionContext";
import type { DraftWaypoint } from "@/types/dispatch";

const ACTION_LABELS: Record<string, string> = { upload: "Upload", start: "Mulai", hold: "Tahan", resume: "Lanjut", abort: "Abort / RTL", append: "Ulangi sinkronisasi WP" };
const TASK_LABELS: Record<string, string> = {
  DRAFT: "Draft", PENDING: "Antre", ASSIGNED: "Ditugaskan", ACKED: "ACK", EN_ROUTE: "Menuju",
  HELD: "Ditahan", REACHED: "Tercapai", FAILED: "Gagal", UNKNOWN: "Tak pasti", CANCELLED: "Dibatalkan",
};
const HOLD_PHASES = ["ACTIVE", "PREPARING", "HELD", "HOLD_REQUIRED", "RECOVERY_REQUIRED"];
const MAP_HELP = "Klik kanan peta untuk menambah waypoint. Pilih marker untuk mengedit; base station menentukan drone pelaksana.";

function operatorMessage(message: string) {
  return message.replace(/UAV-(\d+)/g, (_, id: string) => `UAV ${id.padStart(2, "0")}`);
}

function GeofenceSettings() {
  const mission = useSwarmMission();
  const { state, connected, busy, locked, geoDraft, setGeoDraft, geoPicking, setGeoPicking } = mission;
  const safety = state?.safety;
  const configured = typeof safety?.center_lat === "number" && typeof safety?.center_lon === "number";
  const [saved, setSaved] = useState(false);
  // Seed the shared draft from the applied geofence once it arrives, while fields are still untouched.
  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || !safety) return;
    seeded.current = true;
    setGeoDraft({
      lat: typeof safety.center_lat === "number" ? safety.center_lat.toFixed(7) : "",
      lon: typeof safety.center_lon === "number" ? safety.center_lon.toFixed(7) : "",
      radius: String(safety.radius_m ?? 200),
    });
  }, [safety, setGeoDraft]);
  // Picking a point on the map clears the "saved" confirmation so the operator re-saves.
  useEffect(() => { if (geoPicking) setSaved(false); }, [geoPicking]);

  const values = [geoDraft.lat, geoDraft.lon, geoDraft.radius].map(Number);
  const valid = values.every(Number.isFinite) && Math.abs(values[0]) <= 90 && Math.abs(values[1]) <= 180 && values[2] > 0 && values[2] <= 10000;
  const reason = !connected ? "Base station terputus."
    : busy || state?.busy ? "Proses misi masih berlangsung."
    : locked ? "Geofence terkunci selama operasi misi / UAV armed."
    : !mission.token ? "Isi token operator dulu."
    : !valid ? "Lengkapi lintang, bujur, dan radius (1–10000 m) yang valid." : "";

  const edit = (patch: Partial<typeof geoDraft>) => { setGeoDraft(patch); setSaved(false); };
  const fillFrom = (slot: 3 | 4) => {
    const drone = state?.drones.find(d => d.drone_id === slot);
    if (typeof drone?.lat === "number" && typeof drone?.lon === "number" && (drone.lat !== 0 || drone.lon !== 0)) {
      edit({ lat: drone.lat.toFixed(7), lon: drone.lon.toFixed(7) });
    }
  };
  const save = async () => {
    if (reason) return;
    setGeoPicking(false);
    const ok = await mission.updateGeofence(values[0], values[1], values[2]);
    setSaved(ok);
  };

  const piJson = safety && configured ? JSON.stringify({
    center_lat: safety.center_lat, center_lon: safety.center_lon, radius_m: safety.radius_m,
    min_alt_m: safety.min_alt_m, max_alt_m: safety.max_alt_m, takeoff_alt_m: safety.takeoff_alt_m,
    min_battery_pct: safety.min_battery_pct, min_separation_m: safety.min_separation_m, apf: safety.apf,
  }, null, 2) : "";

  return <details className="swarm-disclosure">
    <summary>Geofence lokasi {configured ? "" : "· belum diatur"}</summary>
    <div className="swarm-advanced-content">
      <p className="swarm-append-hint">
        {configured ? `Pusat ${safety!.center_lat!.toFixed(6)}, ${safety!.center_lon!.toFixed(6)} · radius ${safety!.radius_m} m.`
          : "Pusat & radius wajib diisi sebelum upload. Semua waypoint harus di dalam lingkaran ini."}
      </p>
      <button type="button" className={`operations-button ${geoPicking ? "is-primary" : "is-secondary"}`} disabled={locked}
        title={locked ? "Terkunci selama operasi misi" : "Klik pada peta untuk menitik pusat geofence"}
        onClick={() => setGeoPicking(!geoPicking)}>{geoPicking ? "Klik peta untuk menitik pusat… (batal)" : "Pilih pusat di peta"}</button>
      <div className="swarm-waypoint-fields">
        <label className="operations-field"><span>Pusat lintang</span>
          <input type="number" step="any" value={geoDraft.lat} disabled={locked} onChange={e => edit({ lat: e.target.value })} /></label>
        <label className="operations-field"><span>Pusat bujur</span>
          <input type="number" step="any" value={geoDraft.lon} disabled={locked} onChange={e => edit({ lon: e.target.value })} /></label>
        <label className="operations-field"><span>Radius (m)</span>
          <input type="number" min={1} max={10000} value={geoDraft.radius} disabled={locked} onChange={e => edit({ radius: e.target.value })} /></label>
      </div>
      <div className="swarm-mission-actions">
        <button type="button" className="operations-button is-secondary" disabled={locked} title="Isi pusat dari posisi GPS UAV 03" onClick={() => fillFrom(3)}>Posisi UAV 03</button>
        <button type="button" className="operations-button is-secondary" disabled={locked} title="Isi pusat dari posisi GPS UAV 04" onClick={() => fillFrom(4)}>Posisi UAV 04</button>
        <span className="swarm-action-hint" title={reason || "Simpan geofence ke base station"}>
          <button type="button" className="operations-button is-primary" disabled={Boolean(reason)} onClick={save}>Simpan geofence</button>
        </span>
      </div>
      {saved && <p className="swarm-append-hint" role="status">Tersimpan. Salin JSON di bawah ke kedua Pi lalu restart companion agar hash cocok.</p>}
      {configured && <div className="swarm-geofence-sync">
        {([3, 4] as const).map(slot => {
          const drone = state?.drones.find(d => d.drone_id === slot);
          const match = drone?.safety_hash && state?.safety_hash ? drone.safety_hash === state.safety_hash : null;
          return <span key={slot} className={`mavlink-status swarm-chip ${match === true ? "is-armed" : match === false ? "is-disconnected" : "is-disarmed"}`}
            title={match === null ? "Menunggu laporan companion." : match ? "Konfigurasi Pi cocok dengan base station." : "Pi memakai konfigurasi lama; salin JSON lalu restart companion."}>
            UAV {String(slot).padStart(2, "0")}: {match === null ? "Menunggu" : match ? "Cocok" : "Tak cocok"}</span>;
        })}
      </div>}
      {piJson && <details className="swarm-disclosure">
        <summary>JSON untuk companion (--swarm-safety)</summary>
        <pre className="swarm-geofence-json" style={{ overflowX: "auto", fontSize: "0.75rem", whiteSpace: "pre" }}>{piJson}</pre>
        <div className="swarm-mission-actions">
          <button type="button" className="operations-button is-secondary" onClick={() => void navigator.clipboard?.writeText(piJson)}>Salin JSON</button>
        </div>
      </details>}
    </div>
  </details>;
}

export function SwarmMissionPanel() {
  const mission = useSwarmMission();
  const { state, draft, dirty, busy, locked, connected, selected } = mission;
  const [confirm, setConfirm] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const advanced = useRef<HTMLDetailsElement>(null);
  const queue = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (confirm) dialog.current?.showModal();
    else dialog.current?.close();
  }, [confirm]);
  useEffect(() => {
    // A map selection still opens the editor, even though settings start folded.
    if (selected) {
      if (advanced.current) advanced.current.open = true;
      if (queue.current) queue.current.open = true;
    }
  }, [selected]);
  const phase = state?.phase ?? "DRAFT";
  const tasks = state?.tasks ?? [];
  const update = (wp: DraftWaypoint, field: "lat" | "lon" | "alt_m", value: string) => {
    mission.edit(draft.map(item => item.task_id === wp.task_id ? { ...item, [field]: Number(value) } : item));
  };
  const move = (index: number, delta: number) => {
    const next = [...draft];
    [next[index], next[index + delta]] = [next[index + delta], next[index]];
    mission.edit(next);
  };
  const canControl = connected && !busy && !state?.busy && Boolean(mission.token);
  const commonReason = !connected ? "Base station terputus. Tunggu koneksi kembali."
    : busy || state?.busy ? "Proses misi / ACK masih berlangsung."
    : !mission.token ? "Isi token operator di Pengaturan lanjutan." : "";
  const blockers = [...new Set((state?.blockers ?? []).map(operatorMessage))];
  const reasons: Record<string, string> = {
    upload: commonReason || (locked ? "Draft terkunci selama operasi misi." : !draft.length ? "Tambahkan waypoint melalui klik kanan peta." : ""),
    start: commonReason || (dirty ? "Draft berubah. Upload ulang sebelum memulai." : !state?.ready_to_start
      ? blockers.length ? `Interlock belum terpenuhi: ${blockers.join("; ")}` : "Upload plan dan tunggu ACK kedua UAV serta precheck server." : ""),
    hold: commonReason || (!HOLD_PHASES.includes(phase) ? "Tahan tersedia saat persiapan, misi aktif, atau pemulihan." : ""),
    resume: commonReason || (state?.append_pending ? "Selesaikan sinkronisasi WP tambahan sebelum Lanjut." : dirty ? "Draft belum tersinkron." : phase !== "HELD" ? "Tunggu konfirmasi Tahan dari kedua UAV." : ""),
    append: commonReason || (!state?.append_pending ? "Tidak ada tambahan WP yang perlu disinkronkan." : phase !== "HELD" ? "Tunggu konfirmasi Tahan dari kedua UAV." : ""),
    abort: commonReason || (!state?.plan.mission_id ? "Belum ada misi di base station." : ""),
  };
  const synced = !dirty && !state?.append_pending && Boolean(state?.plan.mission_id)
    && [3, 4].every(slot => state?.upload[String(slot)] === "UAV_ACK");
  const counts = dirty ? [] : Object.entries(TASK_LABELS)
    .filter(([status]) => status !== "DRAFT" && status !== "CANCELLED")
    .map(([status, label]) => ({ status, label, count: tasks.filter(t => t.status === status).length }))
    .filter(item => item.count > 0);
  const reached = dirty ? 0 : tasks.filter(task => task.status === "REACHED").length;
  const inFlight = ["ACTIVE", "PREPARING", "RESUMING", "ENDING"].includes(phase);
  const checks = [
    { id: "link", label: "Base station", passed: connected, detail: "Koneksi ke state server aktif." },
    { id: "token", label: "Token terisi", passed: Boolean(mission.token), detail: "Token diisi di Pengaturan lanjutan; otorisasi diverifikasi server saat perintah dikirim." },
    { id: "waypoints", label: "Waypoint tersedia", passed: draft.length > 0, detail: MAP_HELP },
    { id: "sync", label: "ACK kedua UAV", passed: synced, detail: "Plan / versi yang sama telah diakui UAV 03 dan UAV 04." },
    { id: "readiness", label: inFlight ? "Misi aktif" : phase === "HELD" ? "Tahan terkonfirmasi" : "Precheck Start",
      passed: inFlight || phase === "HELD" || Boolean(state?.ready_to_start),
      detail: inFlight ? "Status operasi berasal dari base station." : phase === "HELD" ? "Lanjut memicu validasi ulang di server."
        : blockers.join("; ") || "Upload dan tunggu pemeriksaan terbaru dari server." },
  ];
  const passedChecks = checks.filter(check => check.passed).length;
  const lastError = operatorMessage(mission.error || state?.error || "");
  const actionButton = (action: string, label = ACTION_LABELS[action], tone = "is-secondary") => (
    <span className="swarm-action-hint" title={reasons[action] || label}
      tabIndex={reasons[action] ? 0 : undefined} role={reasons[action] ? "group" : undefined}
      aria-label={reasons[action] ? `${label}: ${reasons[action]}` : undefined}>
      <button type="button" className={`operations-button ${tone}`} data-action={action}
        disabled={Boolean(reasons[action])} aria-controls={action === "upload" ? undefined : "swarm-confirm"}
        aria-describedby={reasons[action] ? `swarm-reason-${action} swarm-interlocks` : undefined}
        onClick={() => action === "upload" ? void mission.operate("upload") : setConfirm(action)}>{label}</button>
      {reasons[action] && <span id={`swarm-reason-${action}`} className="sr-only">{reasons[action]}</span>}
    </span>
  );

  return <section id="swarm-information" className="swarm-mission-panel" aria-label="Swarm Information mission controls">
    <div className="swarm-draft-row" aria-label="Ringkasan draft waypoint">
      <strong className="swarm-draft-name" title={state?.plan.mission_id ?? "Draft baru"}>Draft v{state?.plan.version ?? 0}</strong>
      <span className={`mavlink-status swarm-chip ${synced ? "is-armed" : "is-disarmed"}`}
        title={synced ? "ACK plan / versi terakhir cocok pada kedua UAV." : "Draft belum diakui kedua UAV; upload diperlukan."}>{synced ? "Synced" : "Unsynced"}</span>
      <button type="button" className="header-action-button swarm-info-button" title={MAP_HELP} aria-label={MAP_HELP}>?</button>
      <div className="swarm-draft-meta">
        <span className="swarm-altitude-mode" title="Altitude relatif terhadap home masing-masing UAV">Relative Alt</span>
        <span className="swarm-waypoint-count" title={`${reached} dari ${draft.length} waypoint tercapai`}>{reached}/{draft.length} WP</span>
      </div>
    </div>
    {state?.append_pending ? <div className="swarm-append-notice" role="status">
      <p>{state.append_pending.waypoints.length} WP tambahan menunggu sinkronisasi kedua UAV.
        {phase !== "APPENDING" && " Setelah Hold terkonfirmasi, ulangi sinkronisasi lalu pilih Lanjut."}</p>
      {actionButton("append")}
    </div> : state?.append_allowed && <p className="swarm-append-hint">Klik kanan peta untuk menambah WP ke misi aktif.</p>}
    {counts.length > 0 && <div className="swarm-mission-summary" aria-label="Status waypoint">
      {counts.map(({ status, label, count }) => <span key={status}
        className={`mavlink-status swarm-chip ${["FAILED", "UNKNOWN"].includes(status) ? "is-disconnected" : status === "REACHED" ? "is-armed" : ""}`}>{label} {count}</span>)}
    </div>}

    <details id="swarm-interlocks" className="swarm-disclosure">
      <summary><span>Interlock</span><span className={`operations-state ${passedChecks === checks.length ? "is-ok" : ""}`}>{passedChecks}/{checks.length}</span></summary>
      <ul className="swarm-interlock-list">
        {checks.map(check => <li key={check.id} id={`swarm-check-${check.id}`} title={check.detail}>
          <span className={check.passed ? "swarm-check-pass" : "swarm-check-fail"} aria-label={check.passed ? "Terpenuhi" : "Belum terpenuhi"}>{check.passed ? "✓" : "✕"}</span>
          <span>{check.label}</span>
          <span className="sr-only">{check.detail}</span>
        </li>)}
      </ul>
    </details>

    <div className="swarm-mission-workflow" role="group" aria-label="Upload lalu mulai, kemudian tahan atau lanjutkan misi">
      {actionButton("upload")}
      {actionButton("start", ACTION_LABELS.start, "is-primary")}
      {actionButton(phase === "HELD" ? "resume" : "hold")}
    </div>
    <div className="swarm-mission-emergency" role="group" aria-label="Hentikan misi">
      <div className="swarm-action-feedback" aria-live="polite">
        {(busy || state?.busy) && <span>Menunggu ACK…</span>}
        {lastError && <span className="mavlink-status swarm-chip is-disconnected" title={lastError} role="alert" aria-label={lastError}>Lihat log</span>}
      </div>
      {actionButton("abort", ACTION_LABELS.abort, "is-danger")}
    </div>

    <details ref={advanced} className="swarm-disclosure swarm-advanced">
      <summary>Pengaturan lanjutan</summary>
      <div className="swarm-advanced-content">
        <label className="operations-field"><span>Token operator</span><input type="password" autoComplete="off" value={mission.token} onChange={e => mission.setToken(e.target.value)} /></label>
        <label className="operations-field"><span>Altitude default (m)</span><input type="number" min={state?.safety.min_alt_m ?? 1} max={state?.safety.max_alt_m ?? 500}
          value={mission.altitude} disabled={!mission.canAdd} onChange={e => mission.setAltitude(Number(e.target.value))} /></label>
        <GeofenceSettings />
        <details ref={queue} className="swarm-disclosure swarm-task-queue">
          <summary>Antrean WP ({draft.length})</summary>
          <ol className="swarm-mission-queue">
            {draft.map((wp, index) => {
              const task = !dirty ? tasks.find(t => t.task_id === wp.task_id) : undefined;
              return <li key={wp.task_id} className={selected === wp.task_id ? "is-selected" : ""}>
                <button type="button" className="operations-button is-secondary" onClick={() => mission.select(wp.task_id)}>WP-{String(wp.sequence).padStart(2, "0")} · {state?.append_pending?.waypoints.some(item => item.task_id === wp.task_id) ? "Sinkronisasi" : TASK_LABELS[task?.status ?? "DRAFT"] ?? task?.status}</button>
                {task?.owner_drone_id && <span>Pelaksana: UAV {String(task.owner_drone_id).padStart(2, "0")}</span>}
                {task?.reason && <small>{operatorMessage(task.reason)}</small>}
                <div className="swarm-waypoint-fields">
                  {(["lat", "lon", "alt_m"] as const).map(field => <label className="operations-field" key={field}><span>{field === "alt_m" ? "Altitude (m)" : field === "lat" ? "Lintang" : "Bujur"}</span>
                    <input type="number" step="any" aria-label={`WP-${wp.sequence} ${field}`} value={wp[field]} disabled={locked}
                      onChange={e => update(wp, field, e.target.value)} /></label>)}
                </div>
                <div className="swarm-mission-actions">
                  <button type="button" className="operations-button is-secondary" disabled={locked || index === 0} title={locked ? "Draft terkunci" : "Pindah ke atas"} onClick={() => move(index, -1)} aria-label={`Move WP-${wp.sequence} up`}>↑</button>
                  <button type="button" className="operations-button is-secondary" disabled={locked || index === draft.length - 1} title={locked ? "Draft terkunci" : "Pindah ke bawah"} onClick={() => move(index, 1)} aria-label={`Move WP-${wp.sequence} down`}>↓</button>
                  <button type="button" className="operations-button is-secondary" disabled={locked} title={locked ? "Draft terkunci" : "Hapus waypoint"} onClick={() => mission.edit(draft.filter(t => t.task_id !== wp.task_id))}>Hapus</button>
                </div>
              </li>;
            })}
          </ol>
          <div className="swarm-mission-actions">
            <button type="button" className="operations-button is-secondary" disabled={locked || !draft.length} title={locked ? "Draft terkunci" : !draft.length ? "Draft masih kosong" : "Hapus seluruh draft"} onClick={() => mission.edit([])}>Kosongkan</button>
            <button type="button" className="operations-button is-secondary" disabled={busy} title={busy ? "Proses misi berlangsung" : "Muat plan terakhir dari server"} onClick={mission.reload}>Muat plan</button>
          </div>
        </details>
        {phase === "HELD" && actionButton("hold", "Tahan ulang")}
        <details className="swarm-disclosure">
          <summary>Log perintah</summary>
          {state?.plan.mission_id && <p className="swarm-mission-id">{state.plan.mission_id} · v{state.plan.version}</p>}
          {lastError && <p className="swarm-mission-error">{lastError}</p>}
          {state?.drones.map(drone => {
            const command = state.commands[String(drone.drone_id)];
            return (command || drone.error) && <div key={drone.drone_id} className="swarm-command-detail">
              <strong>UAV {String(drone.drone_id).padStart(2, "0")}</strong>
              {command && <span>{command.operation} · {command.status}</span>}
              {(command?.error || drone.error) && <span>{operatorMessage(command?.error || drone.error || "")}</span>}
            </div>
          })}
          <ol className="swarm-event-log">{state?.events.map(event => <li key={event.id}><time>{new Date(event.at * 1000).toLocaleTimeString()}</time> {event.type} {event.drone_id ? `UAV ${String(event.drone_id).padStart(2, "0")}` : ""} {operatorMessage(event.reason || event.error || "")}</li>)}</ol>
        </details>
        <details className="swarm-disclosure" open={blockers.length > 0}>
          <summary><span>Precheck gagal</span>
            <span className={`operations-state ${blockers.length ? "" : "is-ok"}`}>{blockers.length}</span></summary>
          {blockers.length === 0
            ? <p className="swarm-append-hint">Semua precheck lolos; server tidak melaporkan penghalang.</p>
            : <ul className="swarm-interlock-list swarm-blocker-list">
                {blockers.map(item => <li key={item}>
                  <span className="swarm-check-fail" aria-hidden="true">✕</span><span>{item}</span>
                </li>)}
              </ul>}
        </details>
        <Link className="operations-back-link" href="/swarm/legacy">Planner legacy</Link>
      </div>
    </details>
    <dialog ref={dialog} id="swarm-confirm" className="operations-dialog swarm-confirm-dialog" onCancel={() => setConfirm(null)} aria-labelledby="swarm-confirm-title">
      <h2 id="swarm-confirm-title">{confirm ? ACTION_LABELS[confirm] : "Konfirmasi"} misi?</h2>
      <p>{state?.plan.mission_id} · v{state?.plan.version} · {tasks.length} WP · UAV 03 & UAV 04</p>
      <p>{confirm === "start" ? `Kedua drone akan ARM, TAKEOFF ke ${state?.safety.takeoff_alt_m} m, lalu menunggu penugasan. Aksi akhir: ${state?.end_action}.` : "Perintah berlaku untuk kedua UAV. Status mengikuti ACK dan telemetry aktual."}</p>
      <div className="operations-dialog-actions"><button type="button" className="operations-button is-secondary" autoFocus onClick={() => setConfirm(null)}>Batal</button>
        <span className="swarm-action-hint" title={confirm ? reasons[confirm] : undefined}>
        <button type="button" className={`operations-button ${confirm === "abort" ? "is-danger" : "is-primary"}`}
          disabled={!canControl || Boolean(confirm && reasons[confirm])} onClick={() => {
          if (confirm) void mission.operate(confirm);
          setConfirm(null);
        }}>Konfirmasi {confirm ? ACTION_LABELS[confirm] : ""}</button></span></div>
    </dialog>
  </section>;
}

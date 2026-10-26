"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useGCSStore } from "@/hooks/useGCSStore";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { DispatchState, DraftWaypoint } from "@/types/dispatch";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const CACHE = "bima-nearest-waypoint-draft-v1";
const EDITABLE = ["DRAFT", "UPLOADED", "PARTIAL", "FAILED_UPLOAD", "COMPLETED", "ABORTED"];

interface MissionContext {
  state: DispatchState | null;
  draft: DraftWaypoint[];
  dirty: boolean;
  connected: boolean;
  locked: boolean;
  canAdd: boolean;
  busy: boolean;
  error: string;
  altitude: number;
  selected: string | null;
  token: string;
  setToken: (value: string) => void;
  setAltitude: (value: number) => void;
  select: (id: string | null) => void;
  edit: (items: DraftWaypoint[]) => void;
  add: (lat: number, lon: number, alt: number) => Promise<boolean>;
  operate: (action: string, additions?: DraftWaypoint[]) => Promise<boolean>;
  updateGeofence: (centerLat: number, centerLon: number, radiusM: number) => Promise<boolean>;
  geoDraft: GeoDraft;
  setGeoDraft: (patch: Partial<GeoDraft>) => void;
  geoPicking: boolean;
  setGeoPicking: (value: boolean) => void;
  reload: () => void;
}

interface GeoDraft {
  lat: string;
  lon: string;
  radius: string;
}

const Context = createContext<MissionContext | null>(null);

export function SwarmMissionProvider({ children }: { children: ReactNode }) {
  const { uavs } = useGCSStore();
  const [state, setState] = useState<DispatchState | null>(null);
  const [draft, setDraft] = useState<DraftWaypoint[]>([]);
  const [dirty, setDirty] = useState(false);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [altitude, setAltitude] = useState(10);
  const [selected, select] = useState<string | null>(null);
  const [token, setToken] = useState(""); // operator secret stays in memory only
  const [geoDraft, setGeoDraftState] = useState<GeoDraft>({ lat: "", lon: "", radius: "" });
  const setGeoDraft = useCallback((patch: Partial<GeoDraft>) => setGeoDraftState(prev => ({ ...prev, ...patch })), []);
  const [geoPicking, setGeoPicking] = useState(false);
  const dirtyRef = useRef(false);
  const busyRef = useRef(false);
  const lastSnapshot = useRef(0);
  const snapshot = useCallback((value: DispatchState) => {
    setState(value);
    lastSnapshot.current = Date.now();
    setConnected(true);
    if (!dirtyRef.current && !busyRef.current) setDraft(value.plan.waypoints ?? []);
  }, []);
  const onMessage = useCallback((text: string) => {
    try { snapshot(JSON.parse(text) as DispatchState); } catch { /* incomplete frame */ }
  }, [snapshot]);
  const onClose = useCallback(() => setConnected(false), []);
  const wsUrl = `${API.replace(/^http/, "ws")}/ws/swarm`;
  useWebSocket({ url: wsUrl, onMessage, onClose });

  useEffect(() => {
    let active = true;
    const cached = sessionStorage.getItem(CACHE);
    if (cached) {
      try {
        const items = JSON.parse(cached) as DraftWaypoint[];
        if (Array.isArray(items)) {
          dirtyRef.current = true;
          queueMicrotask(() => { if (active) { setDraft(items); setDirty(true); } });
        }
      } catch { sessionStorage.removeItem(CACHE); }
    }
    fetch(`${API}/api/swarm/state`).then(r => {
      if (!r.ok) throw new Error("Swarm API unavailable");
      return r.json();
    }).then(data => { if (active && lastSnapshot.current === 0) snapshot(data); }).catch(() => {});
    const timer = setInterval(() => {
      if (Date.now() - lastSnapshot.current > 2500) setConnected(false);
    }, 500);
    return () => { active = false; clearInterval(timer); };
  }, [snapshot]);

  const locked = Boolean(state && (state.edit_locked || !EDITABLE.includes(state.phase) || state.drones.some(d => d.armed))) || busy;
  const canAdd = !busy && !state?.busy && (locked ? state?.plan.waypoints?.length ?? 0 : draft.length) < 200
    && (!locked || Boolean(state?.append_allowed && connected && token));
  const edit = useCallback((items: DraftWaypoint[]) => {
    if (locked) return;
    const normalized = items.map((item, index) => ({ ...item, sequence: index + 1 }));
    dirtyRef.current = true;
    setDirty(true);
    setDraft(normalized);
    sessionStorage.setItem(CACHE, JSON.stringify(normalized));
  }, [locked]);
  const add = async (lat: number, lon: number, alt: number) => {
    if (!canAdd || busyRef.current || ![lat, lon, alt].every(Number.isFinite) || alt <= 0) return false;
    const task_id = `wp-${crypto.randomUUID()}`;
    if (locked) {
      return operate("append", [{ task_id, sequence: (state?.plan.waypoints?.length ?? 0) + 1, lat, lon, alt_m: alt }]);
    }
    edit([...draft, { task_id, sequence: draft.length + 1, lat, lon, alt_m: alt }]);
    select(task_id);
    return true;
  };
  const reload = () => {
    dirtyRef.current = false;
    setDirty(false);
    setDraft(state?.plan.waypoints ?? []);
    sessionStorage.removeItem(CACHE);
  };

  const operate = async (action: string, additions?: DraftWaypoint[]) => {
    if (busyRef.current || !connected) return false;
    busyRef.current = true;
    setBusy(true);
    setError("");
    const request = async (path: string, body: unknown): Promise<DispatchState> => {
      const response = await fetch(`${API}/api/swarm/${path}`, {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify(body),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail));
      return value as DispatchState;
    };
    try {
      let current = state;
      if (action === "upload" && (dirtyRef.current || !state?.plan.mission_id)) {
        const endpoints: Record<string, { host: string; port: number }> = {};
        for (const slot of [3, 4] as const) {
          const config = uavs[slot];
          if (!config?.raspiIp || !config.missionUdpPort) throw new Error(`Configure UAV-${slot} companion IP and Mission UDP Port in Edit Connection`);
          endpoints[String(slot)] = { host: config.raspiIp, port: Number(config.missionUdpPort) };
        }
        current = await request("missions", {
          mission_id: state?.plan.mission_id ?? `swarm-${crypto.randomUUID()}`,
          version: (state?.plan.version ?? 0) + 1,
          coordinate_frame: "GLOBAL_RELATIVE_ALT", waypoints: draft, endpoints,
        });
        setState(current);
        dirtyRef.current = false;
        setDirty(false);
        sessionStorage.removeItem(CACHE);
      }
      if (!current?.plan.mission_id) throw new Error("Upload a mission first");
      const result = await request(`missions/${current.plan.mission_id}/${action}`, {
        version: current.plan.version, confirmation: `CONFIRM_${action.toUpperCase()}`,
        ...(action === "append" ? { waypoints: additions ?? current.append_pending?.waypoints ?? [] } : {}),
      });
      setState(result);
      if (!dirtyRef.current) setDraft(result.plan.waypoints ?? []);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Mission request failed");
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const updateGeofence = async (centerLat: number, centerLon: number, radiusM: number) => {
    if (busyRef.current || !connected) return false;
    busyRef.current = true;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/swarm/geofence`, {
        method: "PUT", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ center_lat: centerLat, center_lon: centerLon, radius_m: radiusM }),
      });
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : JSON.stringify(value.detail));
      setState(value as DispatchState);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Geofence update failed");
      return false;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const viewingLive = Boolean(state && (state.edit_locked || !EDITABLE.includes(state.phase)));
  return <Context.Provider value={{ state, draft: viewingLive ? state?.plan.waypoints ?? [] : draft,
    dirty: viewingLive ? false : dirty, connected, locked, canAdd, busy, error, altitude,
    selected, token, setToken, setAltitude, select, edit, add, operate, updateGeofence,
    geoDraft, setGeoDraft, geoPicking, setGeoPicking, reload }}>{children}</Context.Provider>;
}

export function useSwarmMission() {
  const value = useContext(Context);
  if (!value) throw new Error("SwarmMissionProvider required");
  return value;
}

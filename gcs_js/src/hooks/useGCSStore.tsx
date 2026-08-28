"use client";

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { UAV_IDS } from "@/config/agents";
import type {
  UAVConnectionConfig,
  GCSConfig,
  ThemeMode,
  UAVId,
  UAVRecord,
  MetricConfig,
} from "@/types/telemetry";

interface GCSStoreState {
  config: GCSConfig | null;
  uavs: UAVRecord<UAVConnectionConfig | null>;
  uavMetrics: UAVRecord<MetricConfig[]>;
  isConfigured: boolean;
  isEditModalOpen: boolean;
  theme: ThemeMode;
}

interface GCSStoreActions {
  setConfig: (config: GCSConfig) => void;
  setUAVConfig: (uavId: UAVId, config: UAVConnectionConfig) => void;
  setUAVMetrics: (uavId: UAVId, metrics: MetricConfig[]) => void;
  markConfigured: () => void;
  setIsEditModalOpen: (open: boolean) => void;
  toggleTheme: () => void;
}

type GCSStore = GCSStoreState & GCSStoreActions;

const GCSContext = createContext<GCSStore | null>(null);

function createEmptyUAVState(): UAVRecord<UAVConnectionConfig | null> {
  return { 1: null, 2: null, 3: null, 4: null };
}

const DEFAULT_METRICS: MetricConfig[] = [
  { id: "alt_agl", telemetryKey: "relative_alt_m", label: "ALT AGL", format: "number", decimals: 1, suffix: " m" },
  { id: "alt_msl", telemetryKey: "altitude_m", label: "ALT MSL", format: "number", decimals: 1, suffix: " m" },
  { id: "spd", telemetryKey: "ground_speed_ms", label: "SPD", format: "number", decimals: 1, suffix: " m/s" },
  { id: "vspd", telemetryKey: "climb_rate_ms", label: "VSPD", format: "number", decimals: 1, suffix: " m/s" },
  { id: "hdg", telemetryKey: "heading_deg", label: "HDG", format: "degrees" },
  { id: "sat", telemetryKey: "satellites_visible", label: "SAT", format: "number", decimals: 0 },
  { id: "hdop", telemetryKey: "hdop", label: "HDOP", format: "number", decimals: 2 },
  { id: "wp_dist", telemetryKey: "distance_to_wp_m", label: "WP DIST", format: "distance", accent: true },
  { id: "home_dist", telemetryKey: "home_distance_m", label: "HOME DIST", format: "distance" },
];

function createDefaultMetricsState(): UAVRecord<MetricConfig[]> {
  return { 1: [...DEFAULT_METRICS], 2: [...DEFAULT_METRICS], 3: [...DEFAULT_METRICS], 4: [...DEFAULT_METRICS] };
}

export function GCSProvider({ children }: { children: ReactNode }) {
  const [config, setConfigState] = useState<GCSConfig | null>(null);
  const [uavs, setUavs] = useState<UAVRecord<UAVConnectionConfig | null>>(
    createEmptyUAVState,
  );
  const [uavMetrics, setUavMetricsState] = useState<UAVRecord<MetricConfig[]>>(
    createDefaultMetricsState,
  );
  const [isConfigured, setIsConfigured] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>("dark");

  // Auto-load cached connection config after mount to prevent hydration mismatch
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      const configured = localStorage.getItem("bima_gcs_configured");
      if (configured === "true") {
        const cachedUavs = createEmptyUAVState();
        for (const uavId of UAV_IDS) {
          const value = localStorage.getItem(`bima_gcs_uav_${uavId}`);
          if (!value) continue;
          try {
            cachedUavs[uavId] = JSON.parse(value) as UAVConnectionConfig;
          } catch {
            cachedUavs[uavId] = null;
          }
        }
        setUavs(cachedUavs);
        setIsConfigured(true);
      }
      
      const cachedMetrics = createDefaultMetricsState();
      for (const uavId of UAV_IDS) {
        const metricsVal = localStorage.getItem(`bima_gcs_uav_metrics_${uavId}`);
        if (metricsVal) {
          try {
            cachedMetrics[uavId] = JSON.parse(metricsVal) as MetricConfig[];
          } catch {
            // Keep default if parse fails
          }
        }
      }
      setUavMetricsState(cachedMetrics);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const setConfig = useCallback((c: GCSConfig) => {
    setConfigState(c);
  }, []);

  const setUAVConfig = useCallback((uavId: UAVId, cfg: UAVConnectionConfig) => {
    setUavs((current) => ({ ...current, [uavId]: cfg }));
    if (typeof window !== "undefined") {
      localStorage.setItem(`bima_gcs_uav_${uavId}`, JSON.stringify(cfg));
    }
  }, []);

  const setUAVMetrics = useCallback((uavId: UAVId, metrics: MetricConfig[]) => {
    setUavMetricsState((current) => ({ ...current, [uavId]: metrics }));
    if (typeof window !== "undefined") {
      localStorage.setItem(`bima_gcs_uav_metrics_${uavId}`, JSON.stringify(metrics));
    }
  }, []);

  const markConfigured = useCallback(() => {
    setIsConfigured(true);
    if (typeof window !== "undefined") {
      localStorage.setItem("bima_gcs_configured", "true");
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  const store: GCSStore = {
    config, uavs, uavMetrics, isConfigured, isEditModalOpen, theme,
    setConfig, setUAVConfig, setUAVMetrics, markConfigured, setIsEditModalOpen, toggleTheme,
  };
  return <GCSContext.Provider value={store}>{children}</GCSContext.Provider>;
}

export function useGCSStore(): GCSStore {
  const ctx = useContext(GCSContext);
  if (!ctx) throw new Error("useGCSStore must be used within a GCSProvider");
  return ctx;
}

"use client";

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import { UAV_IDS } from "@/config/agents";
import type {
  UAVConnectionConfig,
  GCSConfig,
  ThemeMode,
  UAVId,
  UAVRecord,
} from "@/types/telemetry";

interface GCSStoreState {
  config: GCSConfig | null;
  uavs: UAVRecord<UAVConnectionConfig | null>;
  isConfigured: boolean;
  isEditModalOpen: boolean;
  theme: ThemeMode;
  yoloEnabled: boolean;
}

interface GCSStoreActions {
  setConfig: (config: GCSConfig) => void;
  setUAVConfig: (uavId: UAVId, config: UAVConnectionConfig) => void;
  markConfigured: () => void;
  setIsEditModalOpen: (open: boolean) => void;
  toggleTheme: () => void;
  setYoloEnabled: (enabled: boolean) => void;
}

type GCSStore = GCSStoreState & GCSStoreActions;

const GCSContext = createContext<GCSStore | null>(null);

function createEmptyUAVState(): UAVRecord<UAVConnectionConfig | null> {
  return { 1: null, 2: null, 3: null, 4: null };
}

export function GCSProvider({ children }: { children: ReactNode }) {
  const [config, setConfigState] = useState<GCSConfig | null>(null);
  const [uavs, setUavs] = useState<UAVRecord<UAVConnectionConfig | null>>(
    createEmptyUAVState,
  );
  const [isConfigured, setIsConfigured] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>("dark");
  const [yoloEnabled, setYoloEnabledState] = useState(true);

  // Auto-load cached connection config after mount to prevent hydration mismatch
  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      const configured = localStorage.getItem("bima_gcs_configured");
      if (configured === "true") {
        const cached = createEmptyUAVState();
        for (const uavId of UAV_IDS) {
          const value = localStorage.getItem(`bima_gcs_uav_${uavId}`);
          if (!value) continue;
          try {
            cached[uavId] = JSON.parse(value) as UAVConnectionConfig;
          } catch {
            cached[uavId] = null;
          }
        }
        setUavs(cached);
        setIsConfigured(true);
      }
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
    setYoloEnabledState(c.yolo_enabled);
  }, []);

  const setUAVConfig = useCallback((uavId: UAVId, cfg: UAVConnectionConfig) => {
    setUavs((current) => ({ ...current, [uavId]: cfg }));
    if (typeof window !== "undefined") {
      localStorage.setItem(`bima_gcs_uav_${uavId}`, JSON.stringify(cfg));
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

  const setYoloEnabled = useCallback((enabled: boolean) => {
    setYoloEnabledState(enabled);
  }, []);

  const store: GCSStore = {
    config, uavs, isConfigured, isEditModalOpen, theme, yoloEnabled,
    setConfig, setUAVConfig, markConfigured, setIsEditModalOpen, toggleTheme, setYoloEnabled,
  };

  return <GCSContext.Provider value={store}>{children}</GCSContext.Provider>;
}

export function useGCSStore(): GCSStore {
  const ctx = useContext(GCSContext);
  if (!ctx) throw new Error("useGCSStore must be used within a GCSProvider");
  return ctx;
}

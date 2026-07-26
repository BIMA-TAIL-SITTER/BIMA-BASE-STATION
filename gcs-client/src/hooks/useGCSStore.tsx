"use client";

import { createContext, useContext, useState, useCallback, type ReactNode, useEffect } from "react";
import type { UAVConnectionConfig, GCSConfig, ThemeMode } from "@/types/telemetry";

interface GCSStoreState {
  config: GCSConfig | null;
  uav1: UAVConnectionConfig | null;
  uav2: UAVConnectionConfig | null;
  isConfigured: boolean;
  isEditModalOpen: boolean;
  theme: ThemeMode;
  yoloEnabled: boolean;
}

interface GCSStoreActions {
  setConfig: (config: GCSConfig) => void;
  setUAVConfig: (uavId: 1 | 2, config: UAVConnectionConfig) => void;
  markConfigured: () => void;
  setIsEditModalOpen: (open: boolean) => void;
  toggleTheme: () => void;
  setYoloEnabled: (enabled: boolean) => void;
}

type GCSStore = GCSStoreState & GCSStoreActions;

const GCSContext = createContext<GCSStore | null>(null);

export function GCSProvider({ children }: { children: ReactNode }) {
  const [config, setConfigState] = useState<GCSConfig | null>(null);
  const [uav1, setUav1] = useState<UAVConnectionConfig | null>(null);
  const [uav2, setUav2] = useState<UAVConnectionConfig | null>(null);
  const [isConfigured, setIsConfigured] = useState(false);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [theme, setTheme] = useState<ThemeMode>("dark");
  const [yoloEnabled, setYoloEnabledState] = useState(true);

  // Auto-load cached connection config on launch
  useEffect(() => {
  const configured = localStorage.getItem("bima_gcs_configured");
  if (configured === "true") {
    const c1 = localStorage.getItem("bima_gcs_uav_1");
    const c2 = localStorage.getItem("bima_gcs_uav_2");
    if (c1) {
      try { setUav1(JSON.parse(c1)); } catch {}
    }
    if (c2) {
      try { setUav2(JSON.parse(c2)); } catch {}
    }
    setIsConfigured(true);
  }
}, []);

  const setConfig = useCallback((c: GCSConfig) => {
    setConfigState(c);
    setYoloEnabledState(c.yolo_enabled);
  }, []);

  const setUAVConfig = useCallback((uavId: 1 | 2, cfg: UAVConnectionConfig) => {
    if (uavId === 1) setUav1(cfg);
    else setUav2(cfg);
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
    config, uav1, uav2, isConfigured, isEditModalOpen, theme, yoloEnabled,
    setConfig, setUAVConfig, markConfigured, setIsEditModalOpen, toggleTheme, setYoloEnabled,
  };

  return <GCSContext.Provider value={store}>{children}</GCSContext.Provider>;
}

export function useGCSStore(): GCSStore {
  const ctx = useContext(GCSContext);
  if (!ctx) throw new Error("useGCSStore must be used within a GCSProvider");
  return ctx;
}

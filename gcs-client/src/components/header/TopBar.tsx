"use client";

import { useGCSStore } from "@/hooks/useGCSStore";
import { useCallback } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function TopBar() {
  const { config, theme, toggleTheme, yoloEnabled, setYoloEnabled, setIsEditModalOpen } = useGCSStore();

  const handleYoloToggle = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/video/yolo/toggle`, { method: "POST" });
      const data = await res.json();
      setYoloEnabled(data.enabled);
    } catch {
      console.error("Failed to toggle YOLO");
    }
  }, [setYoloEnabled]);

  return (
    <header id="top-bar">
      {/* Brand */}
      <div className="brand-title">
        BASE STATION
        <span className="pulse-dot" />
      </div>

      {/* Connection info */}
      <div className="header-info">
        <div>
          IP : <span className="accent-text">{config?.tailscale_ip ?? "---"}</span>
        </div>

        {/* Tombol Setting Edit IP & Port UAV */}
        <button
          onClick={() => setIsEditModalOpen(true)}
          className="flex items-center gap-1.5 px-3 py-1 text-xs font-bold rounded bg-[#1A1F2B] hover:bg-[#252C3E] text-[#D5FF40] border border-[#2D3448] transition-colors shadow-sm"
          title="Edit IP dan Port Setiap UAV"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
          <span>EDIT IP / PORT</span>
        </button>

        {/* YOLO Toggle */}
        <div className="toggle-group">
          <span>Yolo :</span>
          <label className="yolo-switch">
            <input
              type="checkbox"
              checked={yoloEnabled}
              onChange={handleYoloToggle}
            />
            <span className="yolo-slider" />
          </label>
        </div>

        {/* Theme Toggle */}
        <div className="toggle-group">
          <span>Theme :</span>
          <label className="theme-switch">
            <input
              type="checkbox"
              checked={theme === "light"}
              onChange={toggleTheme}
            />
            <div className="theme-slider">
              <span className="icon-sun">☀️</span>
              <span className="icon-moon">🌙</span>
              <div className="theme-thumb" />
            </div>
          </label>
        </div>
      </div>
    </header>
  );
}

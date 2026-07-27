"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback } from "react";
import { useGCSStore } from "@/hooks/useGCSStore";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function TopBar() {
  const pathname = usePathname();
  const {
    config,
    theme,
    toggleTheme,
    yoloEnabled,
    setYoloEnabled,
    setIsEditModalOpen,
  } = useGCSStore();

  const handleYoloToggle = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/video/yolo/toggle`, {
        method: "POST",
      });
      const data = (await response.json()) as { enabled: boolean };
      setYoloEnabled(data.enabled);
    } catch {
      console.error("Failed to toggle YOLO");
    }
  }, [setYoloEnabled]);

  return (
    <header id="top-bar">
      <Link href="/" className="brand-title" aria-label="Open dashboard">
        <span>BIMA SWARM UGM</span>
      </Link>

      <nav className="header-nav" aria-label="Primary navigation">
        <Link
          href="/mission"
          className={pathname === "/mission" ? "is-active" : ""}
          aria-current={pathname === "/mission" ? "page" : undefined}
        >
          MISSION
        </Link>
        <Link
          href="/params"
          className={pathname === "/params" ? "is-active" : ""}
          aria-current={pathname === "/params" ? "page" : undefined}
        >
          PARAMS
        </Link>
      </nav>

      <div className="header-info">
        <div>
          IP : <span className="accent-text">{config?.tailscale_ip ?? "---"}</span>
        </div>

        <button
          type="button"
          onClick={() => setIsEditModalOpen(true)}
          className="header-action-button"
          title="Edit IP dan Port Setiap UAV"
        >
          EDIT IP / PORT
        </button>

        <div className="toggle-group">
          <span>Yolo :</span>
          <label className="yolo-switch">
            <input
              type="checkbox"
              checked={yoloEnabled}
              onChange={handleYoloToggle}
              aria-label="Toggle YOLO detection"
            />
            <span className="yolo-slider" />
          </label>
        </div>

        <div className="toggle-group">
          <span>Theme :</span>
          <label className="theme-switch">
            <input
              type="checkbox"
              checked={theme === "light"}
              onChange={toggleTheme}
              aria-label="Toggle light theme"
            />
            <div className="theme-slider">
              <span className="icon-sun" aria-hidden="true">LT</span>
              <span className="icon-moon" aria-hidden="true">DK</span>
              <div className="theme-thumb" />
            </div>
          </label>
        </div>
      </div>
    </header>
  );
}

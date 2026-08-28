"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useGCSStore } from "@/hooks/useGCSStore";



export default function TopBar() {
  const pathname = usePathname();
  const {
    config,
    theme,
    toggleTheme,
    setIsEditModalOpen,
  } = useGCSStore();


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
          Mission
        </Link>
        <Link
          href="/params"
          className={pathname === "/params" ? "is-active" : ""}
          aria-current={pathname === "/params" ? "page" : undefined}
        >
          Params
        </Link>
        <Link
          href="/stitching"
          className={pathname === "/stitching" ? "is-active" : ""}
          aria-current={pathname === "/stitching" ? "page" : undefined}
        >
          Stitching
        </Link>
        <Link
          href="/fulldata"
          className={pathname === "/fulldata" ? "is-active" : ""}
          aria-current={pathname === "/fulldata" ? "page" : undefined}
        >
          Full Data
        </Link>
      </nav>

      <div className="header-info">
        <div>
          IP: <span className="accent-text">{config?.tailscale_ip ?? "---"}</span>
        </div>

        <button
          type="button"
          onClick={() => setIsEditModalOpen(true)}
          className="header-action-button"
          title="Edit IP dan Port Setiap UAV"
        >
          Edit Connection
        </button>


        <div className="toggle-group">
          <span>Theme:</span>
          <label className="theme-switch">
            <input
              type="checkbox"
              checked={theme === "light"}
              onChange={toggleTheme}
              aria-label="Toggle light theme"
            />
            <div className="theme-slider">
              <span className="icon-sun" aria-hidden="true">☀</span>
              <span className="icon-moon" aria-hidden="true">☾</span>
              <div className="theme-thumb" />
            </div>
          </label>
        </div>
      </div>
    </header>
  );
}

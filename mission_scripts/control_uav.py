#!/usr/bin/env python3
"""
control_uav.py — Definisi Misi Manual (Drip-Feed)
══════════════════════════════════════════════════
Satu-satunya tempat user mengedit waypoint.

Cara pakai:
  1. Edit waypoint di fungsi build_mission() di bawah.
  2. Jalankan gcs_mission_client.py → otomatis import dari sini.
  3. Misi akan di-upload ke Raspi. Saat terbang, Raspi akan meng-upload
     waypoint ke FC satu per satu secara adaptive (drip-feed).

Format setiap waypoint (dict):
  - command  : MAVLink command (16 = MAV_CMD_NAV_WAYPOINT, 22 = MAV_CMD_NAV_TAKEOFF, dll)
  - param1   : Hold time (detik) untuk NAV_WAYPOINT; min pitch untuk TAKEOFF
  - param2   : Accept radius (meter)
  - param3   : Pass radius (0 = through waypoint)
  - param4   : Desired yaw angle (NaN = unchanged)
  - x        : Latitude  (derajat, desimal)
  - y        : Longitude (derajat, desimal)
  - z        : Altitude  (meter, relatif terhadap home)
"""

import json
import os

# ─── Konfigurasi Flight ────────────────────────────────────────────────────
DEFAULT_TAKEOFF_ALT = 10  # meter
HOLD_DURATION = 2       # detik per waypoint


def build_mission():
    """
    Bangun daftar mission items yang akan di-upload ke FC.

    ╔══════════════════════════════════════════════════════════════════╗
    ║     EDIT WAYPOINT DI SINI!                                        ║
    ║  Ganti lat/lon/alt sesuai rencana terbang.                     ║
    ║  Waypoint pertama (index 0) = home/takeoff location.           ║
    ╚══════════════════════════════════════════════════════════════════╝

    Returns:
        list[dict]: Daftar waypoint dalam format MAVLink.
    """
    mission = [
        # ── Waypoint 0: Home / Takeoff Location ──────────────────
        # Command 22 = MAV_CMD_NAV_TAKEOFF
        # z = altitude takeoff (meter, relatif terhadap home)
        {
            "command": 22,       # MAV_CMD_NAV_TAKEOFF
            "param1": 0,         # Min pitch (derajat)
            "param2": 0,
            "param3": 0,
            "param4": float("nan"),  # Yaw angle (NaN = current)
            "x": -7.7693580,         # Latitude
            "y": 110.3842498,        # Longitude
            "z": DEFAULT_TAKEOFF_ALT,  # Altitude takeoff (10m)
        },

        # ── Waypoint 1 ───────────────────────────────────────────
        {
            "command": 16,       # MAV_CMD_NAV_WAYPOINT
            "param1": HOLD_DURATION,  # Hold time (detik)
            "param2": 5,         # Accept radius (meter)
            "param3": 0,         # Pass radius
            "param4": float("nan"),
            "x": -7.76966460,
            "y": 110.38496820,
            "z": 10,             # Altitude (meter)
        },

        # ── Waypoint 2 (Landing / Terakhir) ──────────────────────
        # Waypoint terakhir = titik landing. companion_bridge.py akan
        # otomatis set mode LAND saat waypoint ini tercapai.
        {
            "command": 16,       # MAV_CMD_NAV_WAYPOINT
            "param1": 0,         # Tidak hold, langsung land
            "param2": 5,
            "param3": 0,
            "param4": float("nan"),
            "x": -7.76928460,
            "y": 110.38441840,
            "z": 10,
        },
    ]

    return mission


# ─── Self-test: print mission kalau dijalankan langsung ───────────────────
if __name__ == "__main__":
    print("[*] Daftar mission dari control_uav.py:")
    print(f"[*] Takeoff altitude : {DEFAULT_TAKEOFF_ALT} m")
    print(f"[*] Hold per waypoint: {HOLD_DURATION} detik")
    print()
    items = build_mission()
    for i, wp in enumerate(items):
        cmd_name = "TAKEOFF" if wp["command"] == 22 else "WAYPOINT"
        print(f"  [{i}] {cmd_name:10s} | lat={wp['x']:.5f} lon={wp['y']:.5f} alt={wp['z']}m")
    print(f"\n[+] Total: {len(items)} waypoint")

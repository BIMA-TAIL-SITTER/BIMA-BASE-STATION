#!/usr/bin/env python3
"""
gcs_mission_client.py - Sisi GCS (Ground Control Station)
===========================================================
Dijalankan di laptop/PC GCS. Baca misi dari control_uav.py, upload ke
companion_bridge.py (Raspi) lewat MAVLink Mission Protocol, kirim sinyal
"Start Mission" hanya saat user memintanya, dan tampilkan progress real-time.

Koneksi: udpout → companion_bridge.py (udpin)

Cara pakai:
  1. Pastikan companion_bridge.py sudah jalan di Raspi.
  2. Edit waypoint di control_uav.py.
  3. Jalankan: python gcs_mission_client.py
  4. Ikuti instruksi CLI (start / update / exit).

Port/IP dibaca dari mission_config.json (bisa diubah dari Edit Connection page).
"""

import importlib
import json
import math
import os
import sys
import threading
import time

os.environ["MAVLINK20"] = "1"

from pymavlink import mavutil

# ─── Konfigurasi (baca dari mission_config.json) ─────────────────────────

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "mission_config.json")

# Default values jika config file tidak ada
DEFAULT_RASPI_IP = "192.168.1.12"
DEFAULT_MISSION_UDP_PORT = 14560

# MAVLink custom command untuk sinyal "Start Mission"
# MAV_CMD_USER_1 = 31010 — command ID resmi MAVLink untuk custom user commands.
# Dipilih karena: (1) ada COMMAND_ACK, (2) tidak tercampur STATUSTEXT, (3) extensible.
MAV_CMD_USER_1 = 31010


def load_config():
    """Baca konfigurasi koneksi dari mission_config.json."""
    try:
        with open(_CONFIG_PATH, "r") as f:
            cfg = json.load(f)
            gcs = cfg.get("gcs", {})
            return {
                "raspi_ip": gcs.get("raspi_ip", DEFAULT_RASPI_IP),
                "mission_udp_port": gcs.get("mission_udp_port", DEFAULT_MISSION_UDP_PORT),
            }
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[-] Gagal baca mission_config.json: {e}")
        print(f"[*] Menggunakan default: {DEFAULT_RASPI_IP}:{DEFAULT_MISSION_UDP_PORT}")
        return {
            "raspi_ip": DEFAULT_RASPI_IP,
            "mission_udp_port": DEFAULT_MISSION_UDP_PORT,
        }


# ─── Heartbeat Thread ────────────────────────────────────────────────────

def heartbeat_sender(mav_conn, stop_event):
    """
    Kirim heartbeat setiap 1 detik ke Raspi supaya koneksi tetap hidup.
    Thread daemon — otomatis berhenti saat program utama exit.
    """
    while not stop_event.is_set():
        try:
            mav_conn.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,            # type: GCS
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,   # autopilot: N/A
                0, 0, 0                                   # base_mode, custom_mode, system_status
            )
        except Exception:
            pass  # Jangan crash heartbeat thread
        stop_event.wait(1.0)


# ─── Status Receiver Thread ──────────────────────────────────────────────

def status_receiver(mav_conn, stop_event, pause_event):
    """
    Loop recv_match non-blocking yang mem-print STATUSTEXT dari Raspi.
    Berjalan di thread terpisah supaya tidak mengganggu input() user.

    pause_event: saat di-set(), thread ini berhenti membaca dari koneksi
                 agar tidak mengkonsumsi MISSION_REQUEST dll yang ditujukan
                 untuk upload_mission.
    """
    while not stop_event.is_set():
        # Jangan baca dari koneksi saat operasi mission berlangsung
        if pause_event.is_set():
            stop_event.wait(0.1)
            continue

        try:
            msg = mav_conn.recv_match(
                type=["STATUSTEXT", "COMMAND_ACK"],
                blocking=True,
                timeout=1.0
            )
            if msg is None:
                continue

            msg_type = msg.get_type()

            if msg_type == "STATUSTEXT":
                text = msg.text.strip() if hasattr(msg, "text") else str(msg)
                # Print status dari Raspi langsung ke console
                print(f"    {text}")

            elif msg_type == "COMMAND_ACK":
                cmd = msg.command
                result = msg.result
                if cmd == MAV_CMD_USER_1:
                    if result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                        print("[+] Sinyal START MISSION diterima Raspi!")
                    else:
                        result_name = _command_result_name(result)
                        print(f"[-] Sinyal START ditolak Raspi: {result_name}")

        except Exception as e:
            if not stop_event.is_set():
                print(f"[-] Error di status_receiver: {e}")
            time.sleep(0.5)


def _command_result_name(result_code):
    """Konversi COMMAND_ACK result code ke nama readable."""
    names = {
        0: "ACCEPTED",
        1: "TEMPORARILY_REJECTED",
        2: "DENIED",
        3: "UNSUPPORTED",
        4: "FAILED",
        5: "IN_PROGRESS",
    }
    return names.get(result_code, f"UNKNOWN_{result_code}")


# ─── Upload Mission ──────────────────────────────────────────────────────

def upload_mission(mav_conn, mission_items, timeout=5.0, max_retries=3):
    """
    Upload mission ke Raspi via MAVLink Mission Protocol penuh.

    Protocol:
      GCS → MISSION_COUNT(total)
      Raspi → MISSION_REQUEST(_INT)(seq=0)
      GCS → MISSION_ITEM_INT(seq=0)
      Raspi → MISSION_REQUEST(_INT)(seq=1)
      ...
      Raspi → MISSION_ACK

    Args:
        mav_conn: Koneksi pymavlink.
        mission_items: List of dict dari build_mission().
        timeout: Timeout per step (detik).
        max_retries: Jumlah retry jika timeout.

    Returns:
        bool: True jika upload berhasil.
    """
    total = len(mission_items)
    if total == 0:
        print("[-] Tidak ada mission item untuk di-upload!")
        return False

    print(f"[*] Mengirim MISSION_COUNT ({total} item) ke Raspi...")

    for attempt in range(max_retries):
        try:
            # Kirim MISSION_COUNT
            mav_conn.mav.mission_count_send(
                mav_conn.target_system,
                mav_conn.target_component,
                total,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )

            # Tunggu MISSION_REQUEST per item, lalu balas dengan MISSION_ITEM_INT
            sent = set()
            while len(sent) < total:
                msg = mav_conn.recv_match(
                    type=["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"],
                    blocking=True,
                    timeout=timeout
                )
                if msg is None:
                    print(f"[-] Timeout menunggu MISSION_REQUEST (attempt {attempt+1}/{max_retries})")
                    break

                msg_type = msg.get_type()

                if msg_type == "MISSION_ACK":
                    ack_type = msg.type
                    if ack_type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                        print(f"[+] Mission upload berhasil! ({total} item diterima Raspi)")
                        return True
                    else:
                        print(f"[-] Mission upload ditolak: ACK type={ack_type}")
                        return False

                # Kirim mission item yang diminta
                seq = msg.seq
                if seq < 0 or seq >= total:
                    print(f"[-] Raspi minta seq={seq} yang invalid (total={total})")
                    return False

                wp = mission_items[seq]
                _send_mission_item_int(mav_conn, seq, wp, total)
                sent.add(seq)
                print(f"[*] Mengirim waypoint {seq+1}/{total}...")

            # Setelah semua item terkirim, tunggu MISSION_ACK
            if len(sent) >= total:
                msg = mav_conn.recv_match(
                    type=["MISSION_ACK"],
                    blocking=True,
                    timeout=timeout
                )
                if msg is not None:
                    if msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                        print(f"[+] Mission upload berhasil! ({total} item diterima Raspi)")
                        return True
                    else:
                        print(f"[-] Mission upload ditolak: ACK type={msg.type}")
                        return False

        except Exception as e:
            print(f"[-] Error saat upload mission (attempt {attempt+1}): {e}")

        if attempt < max_retries - 1:
            print(f"[*] Retry upload mission ({attempt+2}/{max_retries})...")
            time.sleep(1)

    print("[-] Upload mission gagal setelah semua retry!")
    return False


def _send_mission_item_int(mav_conn, seq, wp, total):
    """Kirim satu mission item dalam format MISSION_ITEM_INT."""
    # Tentukan frame — relative alt untuk semua
    frame = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT

    # current = 1 hanya untuk seq 0 (home/first waypoint)
    current = 1 if seq == 0 else 0

    # autocontinue = 1 untuk semua kecuali waypoint terakhir
    autocontinue = 1

    # Handle NaN di param4 (yaw) — pymavlink butuh float
    param1 = float(wp.get("param1", 0))
    param2 = float(wp.get("param2", 0))
    param3 = float(wp.get("param3", 0))
    param4 = float(wp.get("param4", 0))
    if math.isnan(param4):
        param4 = float("nan")

    mav_conn.mav.mission_item_int_send(
        mav_conn.target_system,
        mav_conn.target_component,
        seq,                    # seq
        frame,                  # frame
        wp["command"],          # command
        current,                # current
        autocontinue,           # autocontinue
        param1,                 # param1
        param2,                 # param2
        param3,                 # param3
        param4,                 # param4
        int(wp["x"] * 1e7),    # x (lat * 1e7)
        int(wp["y"] * 1e7),    # y (lon * 1e7)
        float(wp["z"]),        # z (altitude)
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION
    )


# ─── Kirim Sinyal Start Mission ──────────────────────────────────────────

def send_start_mission(mav_conn):
    """
    Kirim sinyal "Start Mission" ke Raspi via COMMAND_LONG + MAV_CMD_USER_1.

    Target komponen diubah ke ONBOARD_CONTROLLER (191) agar MAVProxy
    meneruskannya ke companion_bridge.py, bukan ke FC.
    """
    print("[*] Mengirim sinyal START MISSION ke Companion Computer...")
    mav_conn.mav.command_long_send(
        mav_conn.target_system,
        mav_conn.target_component,
        MAV_CMD_USER_1,         # command: MAV_CMD_USER_1
        0,                      # confirmation
        1,                      # param1: 1 = start mission
        0, 0, 0, 0, 0, 0       # param2-7: reserved
    )
    # COMMAND_ACK akan ditangkap di status_receiver thread



# ─── Reload & Update Mission ─────────────────────────────────────────────

def reload_and_upload(mav_conn):
    """
    Reload control_uav.py dan upload ulang mission.

    Trade-off importlib.reload():
      + Perubahan di control_uav.py langsung terpakai tanpa restart program.
      - Modul-level variables (DEFAULT_TAKEOFF_ALT, dll) di-reinitialize.
      - Kalau ada syntax error di file, reload gagal tapi program tetap jalan.

    Alternatif: restart gcs_mission_client.py setiap kali edit waypoint.
    Untuk saat ini, reload() lebih praktis untuk development.
    """
    print("[*] Reload control_uav.py...")
    try:
        import control_uav
        importlib.reload(control_uav)
        mission = control_uav.build_mission()
        print(f"[+] Berhasil reload — {len(mission)} waypoint")
        return upload_mission(mav_conn, mission)
    except Exception as e:
        print(f"[-] Gagal reload control_uav.py: {e}")
        print("[-] Pastikan tidak ada syntax error di file!")
        return False


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    print("===================================================")
    print("  GCS Mission Client - BIMA Ground Station")
    print("===================================================")
    print()

    import argparse
    parser = argparse.ArgumentParser(description="GCS Mission Client")
    parser.add_argument("--action", choices=["upload", "start", "interactive"], default="interactive", help="Aksi yang akan dijalankan. Default: interactive.")
    parser.add_argument("--ip", type=str, help="IP Raspi (override mission_config.json)")
    parser.add_argument("--port", type=int, help="Port UDP (override mission_config.json)")
    args = parser.parse_args()

    # Baca konfigurasi koneksi
    config = load_config()
    raspi_ip = args.ip if args.ip else config["raspi_ip"]
    udp_port = args.port if args.port else config["mission_udp_port"]
    
    # Fallback aman untuk udpout: 0.0.0.0 tidak valid untuk destinasi pengiriman
    if raspi_ip in ["0", "0.0.0.0"]:
        print("[!] Peringatan: IP 0.0.0.0 tidak valid untuk pengiriman (udpout). Menggunakan 127.0.0.1 (localhost).")
        raspi_ip = "127.0.0.1"
    
    conn_str = f"udpout:{raspi_ip}:{udp_port}"

    print(f"[*] Konfigurasi koneksi:")
    print(f"    Raspi IP      : {raspi_ip}")
    print(f"    Mission UDP   : {udp_port}")
    print(f"    Connection    : {conn_str}")

    print(f"[*] Menghubungkan ke Raspi ({conn_str})...")
    mav_conn = mavutil.mavlink_connection(conn_str)
    
    # [WINDOWS FIX] Kirim heartbeat berulang sampai menerima balasan 
    # agar socket udpout ter-bind dan udpin di Raspi mengupdate port tujuannya.
    print("[*] Menunggu paket MAVLink masuk dari Raspi (timeout 10 detik)...")
    start_wait = time.time()
    msg = None
    while time.time() - start_wait < 10.0:
        try:
            mav_conn.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0, 0, 0
            )
        except Exception:
            pass
            
        msg = mav_conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if msg is not None:
            break

    if msg is None:
        print("[-] TIMEOUT: Tidak ada heartbeat dari Raspi!")
        print("[-] Pastikan IP dan Port benar, dan companion_bridge.py sudah berjalan di Raspi.")
        sys.exit(1)
        
    mav_conn.target_system = msg.get_srcSystem()
    mav_conn.target_component = msg.get_srcComponent()
    print(f"[+] Terhubung dengan sistem {mav_conn.target_system} (comp {mav_conn.target_component})")
    print()

    # Start threads
    stop_event = threading.Event()
    pause_event = threading.Event()  # Pause status_receiver during mission ops

    hb_thread = threading.Thread(
        target=heartbeat_sender,
        args=(mav_conn, stop_event),
        daemon=True,
        name="gcs-heartbeat"
    )
    hb_thread.start()
    print("[+] Heartbeat thread aktif")

    status_thread = threading.Thread(
        target=status_receiver,
        args=(mav_conn, stop_event, pause_event),
        daemon=True,
        name="gcs-status-receiver"
    )
    status_thread.start()
    print("[+] Status receiver thread aktif")

    # Tunggu sebentar untuk stabilisasi koneksi
    print("[*] Menunggu koneksi stabil (2 detik)...")
    time.sleep(2)

    # Import dan upload mission pertama kali
    try:
        from control_uav import build_mission
        mission = build_mission()
        print(f"[*] Loaded {len(mission)} waypoint dari control_uav.py")
    except ImportError as e:
        print(f"[-] Gagal import control_uav.py: {e}")
        print("[-] Pastikan file control_uav.py ada di direktori yang sama!")
        stop_event.set()
        sys.exit(1)



    if args.action == "upload":
        print()
        print("--- Upload Mission ------------------------")
        pause_event.set()    # Pause status_receiver agar tidak consume MISSION_REQUEST
        time.sleep(0.2)      # Beri waktu thread berhenti
        upload_success = upload_mission(mav_conn, mission)
        pause_event.clear()  # Resume status_receiver
        time.sleep(1.0) # Tunggu ack
        stop_event.set()
        print("[+] Upload selesai.")
        sys.exit(0 if upload_success else 1)
        
    elif args.action == "start":
        print()
        print("--- Start Mission -------------------------")
        send_start_mission(mav_conn)
        time.sleep(1.0) # Tunggu ack
        stop_event.set()
        print("[+] Start signal terkirim.")
        sys.exit(0)

    # CLI loop — interactive mode
    print()
    print("--- Upload Mission Pertama ------------------------")
    pause_event.set()
    time.sleep(0.2)
    upload_success = upload_mission(mav_conn, mission)
    pause_event.clear()
    print()

    if upload_success:
        print("[+] Mission uploaded ke Raspi, menunggu forward ke FC...")
        print("[*] Setelah Raspi konfirmasi FC menerima, ketik 'start' untuk terbang.")
    else:
        print("[-] Upload gagal. Ketik 'update' untuk coba lagi.")

    print()
    while True:
        try:
            cmd = input(
                "[GCS] Ketik 'start' untuk menerbangkan, "
                "'update' untuk upload ulang, atau 'exit': "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n[*] Keluar...")
            break

        if cmd == "start":
            send_start_mission(mav_conn)

        elif cmd == "update":
            print()
            print("--- Update Mission ---------------------------------")
            pause_event.set()
            time.sleep(0.2)
            reload_and_upload(mav_conn)
            pause_event.clear()
            print()

        elif cmd == "exit" or cmd == "quit":
            print("[*] Keluar dari GCS Mission Client...")
            break

        elif cmd == "status":
            print(f"[*] Target: sys={mav_conn.target_system} comp={mav_conn.target_component}")

        elif cmd == "":
            continue

        else:
            print(f"[-] Perintah tidak dikenal: '{cmd}'")
            print("[*] Perintah yang tersedia: start, update, status, exit")

    # Cleanup
    stop_event.set()
    print("[+] GCS Mission Client selesai.")


if __name__ == "__main__":
    main()

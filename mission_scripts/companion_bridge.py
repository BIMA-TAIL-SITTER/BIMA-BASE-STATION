"""
companion_bridge.py — Sisi Raspi (Companion Computer)
═════════════════════════════════════════════════════════
Dijalankan di Raspberry Pi. Menerima misi dari GCS, forward ke FC,
dan menjalankan flight sequence (arm → takeoff → AUTO → monitor → LAND)
hanya setelah menerima sinyal "Start Mission" eksplisit dari GCS.

Koneksi:
  - GCS  : udpin:0.0.0.0:<listen_port>  (terima dari gcs_mission_client.py)
  - FC   : <fc_connection> (serial/udp ke ArduPilot Flight Controller)

Port/IP dibaca dari mission_config.json.

SAFETY GATE:
  Upload mission ≠ mulai terbang!
  Motor TIDAK boleh armed hanya karena upload selesai.
  Harus ada sinyal START eksplisit dari GCS (MAV_CMD_USER_1).
"""

import argparse
import math
import os
import sys
import threading
import time

os.environ["MAVLINK20"] = "1"

from pymavlink import mavutil

# --- Konfigurasi ---------------------------------------------------------

# Defaults
DEFAULT_LISTEN_PORT = 14560
DEFAULT_FC_CONNECTION = "/dev/ttyACM0"
DEFAULT_FC_BAUD = 57600
DEFAULT_TAKEOFF_ALT = 5      # meter
DEFAULT_HOLD_DURATION = 10   # detik per waypoint

# MAV_CMD_USER_1 — sinyal start dari GCS
MAV_CMD_USER_1 = 31010

def parse_args():
    parser = argparse.ArgumentParser(description="Companion Bridge for Raspi")
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT, help="Port UDP untuk mendengarkan koneksi dari GCS")
    parser.add_argument("--fc-connection", type=str, default=DEFAULT_FC_CONNECTION, help="Connection string ke FC (serial/udp)")
    parser.add_argument("--fc-baud", type=int, default=DEFAULT_FC_BAUD, help="Baud rate untuk serial FC")
    parser.add_argument("--takeoff-alt", type=float, default=DEFAULT_TAKEOFF_ALT, help="Altitude takeoff default (meter)")
    parser.add_argument("--hold-duration", type=float, default=DEFAULT_HOLD_DURATION, help="Durasi hold per waypoint (detik)")
    return parser.parse_args()


# ─── State Machine ───────────────────────────────────────────────────────

class BridgeState:
    """
    State utama companion_bridge, diakses dari beberapa thread.
    Lock digunakan untuk mencegah race condition.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.mission_items = []            # Mission items dari GCS
        self.mission_uploaded_to_fc = False # True setelah FC ACK MISSION_ACCEPTED
        self.mission_running = False       # True selama flight sequence berjalan
        self.pending_mission = None        # Antrian mission baru saat terbang
        self.total_waypoints = 0           # Jumlah waypoint yang di-upload ke FC
        self.stop_event = threading.Event()


# ─── Utility: Kirim STATUSTEXT ke GCS ────────────────────────────────────

def send_status_to_gcs(gcs_conn, text, severity=6):
    """
    Kirim STATUSTEXT ke GCS untuk feedback real-time.
    severity: 6=INFO, 4=WARNING, 3=ERROR (MAV_SEVERITY enum)
    """
    try:
        # STATUSTEXT hanya mendukung 50 karakter
        text = text[:50]
        gcs_conn.mav.statustext_send(severity, text.encode("utf-8"))
    except Exception:
        pass


# ─── Heartbeat ke GCS ────────────────────────────────────────────────────

def heartbeat_sender_gcs(gcs_conn, state):
    """Kirim heartbeat ke GCS setiap 1 detik."""
    while not state.stop_event.is_set():
        try:
            gcs_conn.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_ONBOARD_CONTROLLER,  # type: companion
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0, 0, 0
            )
        except Exception:
            pass
        state.stop_event.wait(1.0)


# ─── Terima Mission dari GCS ─────────────────────────────────────────────

def receive_mission_from_gcs(gcs_conn, count, state):
    """
    Terima mission items dari GCS setelah MISSION_COUNT diterima.

    Protocol:
      GCS → MISSION_COUNT(total)        [sudah diterima sebelum fungsi ini dipanggil]
      Raspi → MISSION_REQUEST_INT(seq=0)
      GCS → MISSION_ITEM_INT(seq=0)
      ...
      Raspi → MISSION_ACK
    """
    print(f"[*] Menerima {count} mission items dari GCS...")
    mission_items = [None] * count

    for seq in range(count):
        # Kirim request untuk setiap item
        gcs_conn.mav.mission_request_int_send(
            gcs_conn.target_system,
            gcs_conn.target_component,
            seq,
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )

        # Tunggu MISSION_ITEM_INT
        msg = gcs_conn.recv_match(
            type=["MISSION_ITEM_INT", "MISSION_ITEM"],
            blocking=True,
            timeout=5.0
        )
        if msg is None:
            print(f"[-] Timeout menunggu mission item seq={seq}")
            # Kirim NACK ke GCS
            gcs_conn.mav.mission_ack_send(
                gcs_conn.target_system,
                gcs_conn.target_component,
                mavutil.mavlink.MAV_MISSION_ERROR,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )
            return None

        # Simpan mission item
        is_int = msg.get_type() == "MISSION_ITEM_INT"
        lat = msg.x / 1e7 if is_int else msg.x
        lon = msg.y / 1e7 if is_int else msg.y

        mission_items[seq] = {
            "seq": seq,
            "command": msg.command,
            "frame": msg.frame,
            "current": msg.current,
            "autocontinue": msg.autocontinue,
            "param1": msg.param1,
            "param2": msg.param2,
            "param3": msg.param3,
            "param4": msg.param4,
            "x": lat,
            "y": lon,
            "z": msg.z,
        }
        print(f"[*] Diterima waypoint {seq+1}/{count}")

    # Kirim ACK ke GCS
    gcs_conn.mav.mission_ack_send(
        gcs_conn.target_system,
        gcs_conn.target_component,
        mavutil.mavlink.MAV_MISSION_ACCEPTED,
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION
    )

    print(f"[+] Semua {count} mission items diterima dari GCS!")
    return mission_items


# ─── Upload Mission ke FC ─────────────────────────────────────────────────

def upload_mission_to_fc(fc_conn, mission_items, gcs_conn, state):
    """
    Forward-upload mission items dari GCS ke Flight Controller.
    Setelah berhasil, set mission_uploaded_to_fc = True.
    TIDAK arm atau takeoff — hanya upload.
    """
    total = len(mission_items)
    print(f"[*] Forward-upload {total} mission items ke FC...")
    send_status_to_gcs(gcs_conn, f"[*] Upload {total} wp ke FC...")

    try:
        # Kirim MISSION_COUNT ke FC
        fc_conn.mav.mission_count_send(
            fc_conn.target_system,
            fc_conn.target_component,
            total,
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )

        sent = set()
        while len(sent) < total:
            msg = fc_conn.recv_match(
                type=["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"],
                blocking=True,
                timeout=5.0
            )
            if msg is None:
                print("[-] Timeout menunggu MISSION_REQUEST dari FC")
                send_status_to_gcs(gcs_conn, "[-] Timeout upload ke FC")
                return False

            msg_type = msg.get_type()

            if msg_type == "MISSION_ACK":
                if msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                    print(f"[+] FC menerima mission! ({total} waypoint)")
                    send_status_to_gcs(gcs_conn, f"[+] FC terima {total} wp - ACCEPTED")
                    with state.lock:
                        state.mission_uploaded_to_fc = True
                        state.total_waypoints = total
                    return True
                else:
                    print(f"[-] FC tolak mission: ACK type={msg.type}")
                    send_status_to_gcs(gcs_conn, f"[-] FC tolak mission: {msg.type}")
                    return False

            seq = msg.seq
            if seq < 0 or seq >= total:
                print(f"[-] FC minta seq={seq} invalid (total={total})")
                return False

            wp = mission_items[seq]
            _send_item_to_fc(fc_conn, seq, wp, total)
            sent.add(seq)
            print(f"[*] Kirim wp {seq+1}/{total} ke FC")

        # Tunggu ACK final
        msg = fc_conn.recv_match(type=["MISSION_ACK"], blocking=True, timeout=5.0)
        if msg and msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
            print(f"[+] FC menerima mission! ({total} waypoint)")
            send_status_to_gcs(gcs_conn, f"[+] FC terima {total} wp - ACCEPTED")
            with state.lock:
                state.mission_uploaded_to_fc = True
                state.total_waypoints = total
            return True
        else:
            ack_type = msg.type if msg else "TIMEOUT"
            print(f"[-] FC tolak/timeout mission ACK: {ack_type}")
            send_status_to_gcs(gcs_conn, f"[-] FC error: {ack_type}")
            return False

    except Exception as e:
        print(f"[-] Error upload ke FC: {e}")
        send_status_to_gcs(gcs_conn, f"[-] Error upload FC: {str(e)[:30]}")
        return False


def _send_item_to_fc(fc_conn, seq, wp, total):
    """Kirim satu mission item ke FC dalam format MISSION_ITEM_INT."""
    frame = wp.get("frame", mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)
    current = 1 if seq == 0 else 0
    autocontinue = wp.get("autocontinue", 1)

    param4 = float(wp.get("param4", 0))

    fc_conn.mav.mission_item_int_send(
        fc_conn.target_system,
        fc_conn.target_component,
        seq,
        frame,
        wp["command"],
        current,
        autocontinue,
        float(wp.get("param1", 0)),
        float(wp.get("param2", 0)),
        float(wp.get("param3", 0)),
        param4,
        int(wp["x"] * 1e7),
        int(wp["y"] * 1e7),
        float(wp["z"]),
        mavutil.mavlink.MAV_MISSION_TYPE_MISSION
    )


# ─── Flight Sequence (reuse logic copter_control.py) ─────────────────────

def execute_flight_sequence(fc_conn, gcs_conn, state, config):
    """
    Jalankan urutan terbang secara drip-feed (adaptive waypoint upload).
    """
    takeoff_alt = config["takeoff_alt_m"]
    hold_duration = config["hold_duration_s"]

    with state.lock:
        mission_items = state.mission_items[:]

    total_wp = len(mission_items)
    if total_wp < 2:
        print("[-] Mission tidak valid (butuh minimal 2 wp)")
        send_status_to_gcs(gcs_conn, "[-] Error: Butuh min 2 wp")
        with state.lock:
            state.mission_running = False
        return

    print(f"[*] ═══ MEMULAI FLIGHT SEQUENCE (DRIP-FEED) ═══")
    print(f"[*] Takeoff alt: {takeoff_alt}m | Hold: {hold_duration}s | WP: {total_wp}")
    send_status_to_gcs(gcs_conn, "[*] Memulai flight sequence...")

    try:
        # Loop drip feed untuk setiap target waypoint (mulai dari seq=1)
        for wp_idx in range(1, total_wp):
            print(f"[*] --- DRIP-FEED: WP {wp_idx}/{total_wp-1} ---")
            send_status_to_gcs(gcs_conn, f"[*] Menuju WP {wp_idx}/{total_wp-1}")

            # Buat mini-mission: [Home, Target]
            mini_mission = [mission_items[0], mission_items[wp_idx]]
            if not upload_mission_to_fc(fc_conn, mini_mission, gcs_conn, state):
                print(f"[-] Gagal upload mini-mission untuk WP {wp_idx}")
                send_status_to_gcs(gcs_conn, f"[-] Gagal upload WP {wp_idx}")
                return

            if wp_idx == 1:
                # ── Step 1: Set mode GUIDED ──
                if not _set_mode(fc_conn, "GUIDED"):
                    print("[-] Gagal set mode GUIDED!")
                    return

                # ── Step 2: Arm (retry 3x) ──
                if not _arm_vehicle(fc_conn, max_retries=3):
                    print("[-] Gagal arm copter!")
                    return

                # ── Step 3: Takeoff ──
                fc_conn.mav.command_long_send(
                    fc_conn.target_system, fc_conn.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                    0, 0, 0, 0, 0, 0, 0, takeoff_alt
                )
                if not _wait_for_altitude(fc_conn, takeoff_alt, timeout=30):
                    print("[-] Timeout menunggu altitude takeoff!")
                    return
                print(f"[+] Altitude {takeoff_alt}m tercapai!")

            # ── Step 4: Set MISSION_CURRENT = 1 (Target) ──
            fc_conn.mav.mission_set_current_send(
                fc_conn.target_system,
                fc_conn.target_component,
                1
            )

            # ── Step 5: Set mode AUTO ──
            if not _set_mode(fc_conn, "AUTO"):
                print("[-] Gagal set mode AUTO!")
                return

            # Khusus wp pertama, kirim MISSION_START
            if wp_idx == 1:
                fc_conn.mav.command_long_send(
                    fc_conn.target_system, fc_conn.target_component,
                    mavutil.mavlink.MAV_CMD_MISSION_START,
                    0, 0, 0, 0, 0, 0, 0, 0
                )

            # ── Step 6: Tunggu sampai sampai WP (seq=1) ──
            if not _wait_for_wp_reached(fc_conn, gcs_conn, state):
                print("[-] Penerbangan dibatalkan/disarm!")
                return

            print(f"[+] Waypoint {wp_idx} tercapai!")
            send_status_to_gcs(gcs_conn, f"[+] WP {wp_idx}/{total_wp-1} reached")

            # ── Step 7: Cek apakah WP terakhir ──
            if wp_idx == total_wp - 1:
                print("[*] Waypoint terakhir tercapai! Landing...")
                send_status_to_gcs(gcs_conn, "[*] WP terakhir - LANDING")
                _set_mode(fc_conn, "LAND")
                _wait_for_disarm(fc_conn, gcs_conn, state)
                return

            # ── Step 8: Hold sejenak sebelum upload berikutnya ──
            if hold_duration > 0:
                print(f"[*] Hold {hold_duration}s di WP {wp_idx} (GUIDED)...")
                send_status_to_gcs(gcs_conn, f"[*] Hold {hold_duration}s...")
                _set_mode(fc_conn, "GUIDED")

                # Tunggu selama durasi hold (di mode GUIDED drone akan anteng tanpa perlu RC override)
                hold_end = time.time() + hold_duration
                while time.time() < hold_end and not state.stop_event.is_set():
                    time.sleep(0.5)

    except Exception as e:
        print(f"[-] Error dalam flight sequence: {e}")
        send_status_to_gcs(gcs_conn, f"[-] Error: {str(e)[:40]}")

    finally:
        with state.lock:
            state.mission_running = False
        print("[*] Flight sequence selesai, kembali IDLE")
        print("[+] ===========================================")
        print("[+] Masuk ke mode LISTEN: Menunggu misi baru...")
        print()
        print("═══════════════════════════════════════════════════")
        print("  Companion Bridge READY — menunggu perintah GCS")
        print("  Upload mission ≠ mulai terbang (safety gate)")
        print("═══════════════════════════════════════════════════")
        print()
        send_status_to_gcs(gcs_conn, "[*] Kembali IDLE (LISTEN MODE)")
        _check_pending_mission(fc_conn, gcs_conn, state)


def _set_mode(fc_conn, mode_name, timeout=5.0):
    """Set flight mode di FC. Returns True jika berhasil."""
    mode_mapping = {
        "STABILIZE": 0, "ACRO": 1, "ALT_HOLD": 2, "AUTO": 3,
        "GUIDED": 4, "LOITER": 5, "RTL": 6, "CIRCLE": 7,
        "LAND": 9, "DRIFT": 11, "POSHOLD": 16,
    }
    mode_id = mode_mapping.get(mode_name.upper())
    if mode_id is None:
        print(f"[-] Mode tidak dikenal: {mode_name}")
        return False

    fc_conn.mav.set_mode_send(
        fc_conn.target_system,
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
        mode_id
    )

    # Tunggu konfirmasi mode berubah via HEARTBEAT
    start = time.time()
    while time.time() - start < timeout:
        msg = fc_conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if msg and msg.custom_mode == mode_id:
            return True
    return False


def _arm_vehicle(fc_conn, max_retries=3, timeout=5.0):
    """Arm vehicle dengan retry. Returns True jika berhasil."""
    for attempt in range(max_retries):
        fc_conn.mav.command_long_send(
            fc_conn.target_system,
            fc_conn.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1,    # param1: 1=arm
            0, 0, 0, 0, 0, 0
        )

        # Tunggu COMMAND_ACK
        msg = fc_conn.recv_match(type="COMMAND_ACK", blocking=True, timeout=timeout)
        if msg and msg.command == mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM:
            if msg.result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                return True
            else:
                print(f"[-] Arm ditolak (attempt {attempt+1}): result={msg.result}")

        if attempt < max_retries - 1:
            print(f"[*] Retry arm ({attempt+2}/{max_retries})...")
            time.sleep(2)

    return False


def _wait_for_altitude(fc_conn, target_alt, timeout=30, threshold=0.8):
    """Tunggu sampai altitude mencapai threshold * target_alt."""
    start = time.time()
    while time.time() - start < timeout:
        msg = fc_conn.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=1.0)
        if msg:
            current_alt = msg.relative_alt / 1000.0  # mm → m
            if current_alt >= target_alt * threshold:
                return True
    return False


def _wait_for_wp_reached(fc_conn, gcs_conn, state):
    """
    Tunggu sampai FC mengirim MISSION_ITEM_REACHED seq=1.
    Return False jika disarmed di tengah jalan.
    """
    while not state.stop_event.is_set():
        msg = fc_conn.recv_match(
            type=["MISSION_ITEM_REACHED", "HEARTBEAT"],
            blocking=True,
            timeout=1.0
        )
        if msg is None:
            continue

        msg_type = msg.get_type()

        if msg_type == "MISSION_ITEM_REACHED":
            if msg.seq == 1:
                return True

        elif msg_type == "HEARTBEAT":
            armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0
            if not armed and state.mission_running:
                print(f"[*] Copter DISARMED — mission dianggap selesai")
                send_status_to_gcs(gcs_conn, "[*] DISARMED - mission batal")
                return False

    return False


def _wait_for_disarm(fc_conn, gcs_conn, state, timeout=60):
    """Tunggu sampai FC disarm setelah landing."""
    print("[*] Menunggu disarm setelah landing...")
    send_status_to_gcs(gcs_conn, "[*] Menunggu disarm...")
    start = time.time()
    while time.time() - start < timeout and not state.stop_event.is_set():
        msg = fc_conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if msg:
            armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0
            if not armed:
                print("[+] Copter DISARMED! Mission selesai!")
                send_status_to_gcs(gcs_conn, "[+] DISARMED! Mission SELESAI!")
                return True
    print("[-] Timeout menunggu disarm")
    send_status_to_gcs(gcs_conn, "[-] Timeout disarm")
    return False


# ─── Adaptive Update: Antrian Mission Baru ────────────────────────────────

def _check_pending_mission(fc_conn, gcs_conn, state):
    """
    Cek apakah ada mission baru yang di-queue saat terbang.
    Jika ada, upload otomatis ke FC setelah mission selesai/disarm.

    PILIHAN DESAIN: Antrian (queue), bukan MISSION_WRITE_PARTIAL_LIST.
    ALASAN:
      - Full-reload ke FC saat mission berjalan bisa reset current_seq
        dan membingungkan autopilot (copter bisa jump ke waypoint salah).
      - MISSION_WRITE_PARTIAL_LIST butuh tracking seq yang sedang dieksekusi
        secara real-time dan rawan race condition saat autopilot di tengah maneuver.
      - Queue lebih aman: mission baru di-upload SETELAH landing/disarm, saat FC idle.
      - Mission dari antrian TIDAK otomatis start — tetap butuh sinyal 'start'
        eksplisit lagi dari GCS.
    """
    pending = None
    with state.lock:
        if state.pending_mission is not None:
            pending = state.pending_mission
            state.pending_mission = None

    if pending:
        print(f"[*] Ada pending mission ({len(pending)} wp), upload ke FC...")
        send_status_to_gcs(gcs_conn, f"[*] Upload pending {len(pending)} wp ke FC")
        upload_mission_to_fc(fc_conn, pending, gcs_conn, state)
        send_status_to_gcs(gcs_conn, "[*] Pending mission uploaded, ketik 'start'")


# ─── GCS Listener Thread ─────────────────────────────────────────────────

def gcs_listener_thread(gcs_conn, fc_conn, state, config):
    """
    Thread utama yang mendengarkan semua pesan dari GCS.

    Menangani:
      1. MISSION_COUNT → terima mission items dari GCS → forward ke FC
      2. COMMAND_LONG (MAV_CMD_USER_1) → trigger start mission
      3. HEARTBEAT → konfirmasi GCS masih aktif
    """
    print("[+] GCS listener thread aktif")

    while not state.stop_event.is_set():
        try:
            msg = gcs_conn.recv_match(blocking=True, timeout=1.0)
            if msg is None:
                continue

            msg_type = msg.get_type()

            # ── Terima Mission dari GCS ──
            if msg_type == "MISSION_COUNT":
                count = msg.count
                print(f"\n[*] ═══ MISSION_COUNT diterima dari GCS: {count} items ═══")

                # Terima semua mission items
                mission_items = receive_mission_from_gcs(gcs_conn, count, state)
                if mission_items is None:
                    print("[-] Gagal menerima mission dari GCS")
                    continue

                with state.lock:
                    state.mission_items = mission_items

                # Cek apakah mission sedang berjalan
                with state.lock:
                    is_running = state.mission_running

                if is_running:
                    # ── Adaptive Update: queue mission baru ──
                    print("[*] Mission sedang berjalan — mission baru di-queue")
                    send_status_to_gcs(gcs_conn, "[*] Mission berjalan, di-queue")
                    with state.lock:
                        state.pending_mission = mission_items
                else:
                    # Tidak perlu upload ke FC sekarang, tunggu START
                    with state.lock:
                        state.mission_uploaded_to_fc = True  # Tandai sudah siap terbang

            # ── Sinyal Start Mission dari GCS ──
            elif msg_type == "COMMAND_LONG":
                if msg.command == MAV_CMD_USER_1:
                    print("\n[*] ═══ SINYAL START MISSION diterima dari GCS ═══")
                    _handle_start_command(gcs_conn, fc_conn, state, config)

            # ── Heartbeat dari GCS (koneksi hidup) ──
            elif msg_type == "HEARTBEAT":
                pass  # GCS masih aktif, tidak perlu action

        except Exception as e:
            if not state.stop_event.is_set():
                # Abaikan [WinError 10054] yang terjadi di Windows saat GCS client disconnect
                if "10054" not in str(e):
                    print(f"[-] Error di GCS listener: {e}")
                    time.sleep(0.5)


def _handle_start_command(gcs_conn, fc_conn, state, config):
    """
    Handle sinyal START MISSION dari GCS.

    SAFETY GATE:
      - mission_uploaded_to_fc harus True
      - mission_running harus False
    Jika tidak valid, kirim COMMAND_ACK DENIED dan STATUSTEXT error.
    """
    with state.lock:
        uploaded = len(state.mission_items) > 0
        running = state.mission_running

    # Validasi state
    if not uploaded:
        print("[-] START ditolak: belum ada mission diterima dari GCS!")
        send_status_to_gcs(gcs_conn, "[-] START ditolak: belum upload!")
        # Kirim COMMAND_ACK DENIED
        gcs_conn.mav.command_ack_send(
            MAV_CMD_USER_1,
            mavutil.mavlink.MAV_RESULT_DENIED
        )
        return

    if running:
        print("[-] START ditolak: mission sedang berjalan!")
        send_status_to_gcs(gcs_conn, "[-] START ditolak: masih terbang!")
        gcs_conn.mav.command_ack_send(
            MAV_CMD_USER_1,
            mavutil.mavlink.MAV_RESULT_TEMPORARILY_REJECTED
        )
        return

    # Valid — set running dan kirim ACK
    with state.lock:
        state.mission_running = True

    gcs_conn.mav.command_ack_send(
        MAV_CMD_USER_1,
        mavutil.mavlink.MAV_RESULT_ACCEPTED
    )
    print("[+] START MISSION valid — memulai flight sequence!")
    send_status_to_gcs(gcs_conn, "[+] START diterima!")

    # Jalankan flight sequence di thread terpisah
    # supaya GCS listener tetap bisa terima pesan baru
    flight_thread = threading.Thread(
        target=execute_flight_sequence,
        args=(fc_conn, gcs_conn, state, config),
        daemon=True,
        name="flight-sequence"
    )
    flight_thread.start()


# ─── FC Status Forwarder Thread ──────────────────────────────────────────

def fc_status_forwarder(fc_conn, gcs_conn, state):
    """
    Monitor FC dan forward status penting ke GCS via STATUSTEXT.
    Berjalan di thread terpisah, hanya forward — tidak ambil tindakan.

    Yang di-forward:
      - Perubahan mode (GUIDED, AUTO, ALT_HOLD, LAND)
      - Status armed/disarmed
    """
    print("[+] FC status forwarder thread aktif")
    last_mode = None
    last_armed = None

    while not state.stop_event.is_set():
        try:
            # Non-blocking cek — FC messages juga dibaca oleh flight sequence thread,
            # jadi kita hanya perlu cek state secara periodik
            msg = fc_conn.recv_match(type="HEARTBEAT", blocking=True, timeout=2.0)
            if msg is None:
                continue

            # Forward perubahan mode
            mode_mapping = {
                0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO",
                4: "GUIDED", 5: "LOITER", 6: "RTL", 7: "CIRCLE",
                9: "LAND", 11: "DRIFT", 16: "POSHOLD",
            }
            current_mode = mode_mapping.get(msg.custom_mode, f"MODE_{msg.custom_mode}")
            armed = (msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED) != 0

            if current_mode != last_mode:
                last_mode = current_mode
                print(f"[*] FC mode: {current_mode}")
                send_status_to_gcs(gcs_conn, f"[*] FC mode: {current_mode}")

            if armed != last_armed:
                last_armed = armed
                status = "ARMED" if armed else "DISARMED"
                print(f"[*] FC: {status}")
                send_status_to_gcs(gcs_conn, f"[*] FC: {status}")

        except Exception as e:
            if not state.stop_event.is_set():
                # Tidak print error terus-menerus
                time.sleep(1)


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    print("═══════════════════════════════════════════════════")
    print("  Companion Bridge — BIMA Raspberry Pi")
    print("═══════════════════════════════════════════════════")
    print()

    # Baca konfigurasi
    args = parse_args()
    listen_port = args.listen_port
    fc_connection = args.fc_connection
    fc_baud = args.fc_baud

    # Bungkus dalam dictionary supaya sesuai dengan fungsi execute_flight_sequence
    config = {
        "takeoff_alt_m": args.takeoff_alt,
        "hold_duration_s": args.hold_duration,
    }

    print(f"[*] Konfigurasi:")
    print(f"    GCS listen port  : {listen_port}")
    print(f"    FC connection    : {fc_connection}")
    print(f"    FC baud rate     : {fc_baud}")
    print(f"    Takeoff altitude : {args.takeoff_alt}m")
    print(f"    Hold per WP      : {args.hold_duration}s")
    print()

    # State
    state = BridgeState()

    # ── Koneksi GCS (udpin — listen dari GCS) ──
    gcs_conn_str = f"udpin:0.0.0.0:{listen_port}"
    print(f"[*] Membuka koneksi GCS: {gcs_conn_str}")
    try:
        gcs_conn = mavutil.mavlink_connection(
            gcs_conn_str,
            source_system=1,
            source_component=mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER
        )
        gcs_conn.target_system = 255    # GCS system ID
        gcs_conn.target_component = 0

        # [WINDOWS FIX] Monkey patch recv() untuk menelan error 10054
        # agar gcs_conn.recv_match() tidak crash saat GCS lama terputus.
        original_recv = gcs_conn.recv
        def safe_recv(n=None):
            try:
                return original_recv(n)
            except Exception as e:
                if "10054" in str(e):
                    gcs_conn.last_address = None
                    return b""
                raise
        gcs_conn.recv = safe_recv

    except Exception as e:
        print(f"[-] Gagal membuka koneksi GCS: {e}")
        sys.exit(1)
    print(f"[+] Koneksi GCS aktif (menunggu heartbeat dari GCS...)")

    # ── Koneksi FC (serial/udp) ──
    print(f"[*] Menghubungkan ke FC: {fc_connection}")
    try:
        kwargs = {
            "source_system": 1,
            "source_component": mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER
        }
        if fc_connection.startswith("udp:") or fc_connection.startswith("tcp:"):
            fc_conn = mavutil.mavlink_connection(fc_connection, **kwargs)
        else:
            # Serial connection
            fc_conn = mavutil.mavlink_connection(fc_connection, baud=fc_baud, **kwargs)

        print("[*] Menunggu heartbeat dari FC...")
        hb = fc_conn.wait_heartbeat(timeout=10)
        if hb is None:
            print("[-] Timeout menunggu heartbeat FC! Pastikan FC terhubung.")
            print("[-] Lanjut tanpa FC — akan retry saat upload mission.")
        else:
            print(f"[+] FC heartbeat diterima! (sys={fc_conn.target_system} comp={fc_conn.target_component})")
    except Exception as e:
        print(f"[-] Gagal koneksi FC: {e}")
        print("[-] Lanjut tanpa FC — koneksi akan dicoba lagi saat upload mission.")
        # Buat dummy connection yang bisa di-retry
        fc_conn = mavutil.mavlink_connection(
            fc_connection, 
            baud=fc_baud, 
            source_system=1, 
            source_component=mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER
        )

    print()

    # ── Start threads ──
    hb_gcs = threading.Thread(
        target=heartbeat_sender_gcs,
        args=(gcs_conn, state),
        daemon=True,
        name="hb-gcs"
    )
    hb_gcs.start()
    print("[+] Heartbeat ke GCS thread aktif")

    gcs_thread = threading.Thread(
        target=gcs_listener_thread,
        args=(gcs_conn, fc_conn, state, config),
        daemon=True,
        name="gcs-listener"
    )
    gcs_thread.start()
    print("[+] GCS listener thread aktif")

    # Note: fc_status_forwarder tidak dijalankan sebagai thread terpisah
    # karena FC recv_match akan konflik dengan flight sequence thread.
    # Status FC di-forward dari dalam flight sequence thread langsung.

    print()
    print("═══════════════════════════════════════════════════")
    print("  Companion Bridge READY — menunggu perintah GCS")
    print("  Upload mission ≠ mulai terbang (safety gate)")
    print("═══════════════════════════════════════════════════")
    print()

    # Main thread: tetap hidup
    try:
        while not state.stop_event.is_set():
            state.stop_event.wait(1.0)
    except KeyboardInterrupt:
        print("\n[*] Ctrl+C — mematikan companion bridge...")
        state.stop_event.set()

    print("[+] Companion bridge selesai.")


if __name__ == "__main__":
    main()
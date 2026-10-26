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
DEFAULT_HOLD_DURATION = 3   # detik per waypoint

# MAV_CMD_USER_1 — sinyal start dari GCS
MAV_CMD_USER_1 = 31010

# Hover stabilization defaults
DEFAULT_HOVER_ALT_TOLERANCE = 0.5   # meter — altitude within target ± this
DEFAULT_HOVER_VZ_THRESHOLD = 0.2    # m/s — vertical speed must be below this
DEFAULT_HOVER_MIN_DURATION = 3.0    # seconds — must be stable for this long
DEFAULT_GCS_HEARTBEAT_TIMEOUT = 3.0 # seconds — LOITER if no GCS heartbeat


def parse_args():
    parser = argparse.ArgumentParser(description="Companion Bridge for Raspi")
    parser.add_argument("--listen-port", type=int, default=DEFAULT_LISTEN_PORT, help="Port UDP untuk mendengarkan koneksi dari GCS")
    parser.add_argument("--fc-connection", type=str, default=DEFAULT_FC_CONNECTION, help="Connection string ke FC (serial/udp)")
    parser.add_argument("--fc-system-id", type=int, default=None, help="SYSID FC yang diharapkan; default deteksi heartbeat autopilot")
    parser.add_argument("--fc-baud", type=int, default=DEFAULT_FC_BAUD, help="Baud rate untuk serial FC")
    parser.add_argument("--takeoff-alt", type=float, default=DEFAULT_TAKEOFF_ALT, help="Altitude takeoff default (meter)")
    parser.add_argument("--hold-duration", type=float, default=DEFAULT_HOLD_DURATION, help="Durasi hold per waypoint (detik)")
    parser.add_argument("--uav-id", type=int, default=1, help="UAV identity (1 or 2) for swarm routing")
    parser.add_argument("--hover-alt-tolerance", type=float, default=DEFAULT_HOVER_ALT_TOLERANCE, help="Hover altitude tolerance (m)")
    parser.add_argument("--hover-vz-threshold", type=float, default=DEFAULT_HOVER_VZ_THRESHOLD, help="Hover vertical speed threshold (m/s)")
    parser.add_argument("--hover-min-duration", type=float, default=DEFAULT_HOVER_MIN_DURATION, help="Hover stabilization min duration (s)")
    parser.add_argument("--gcs-heartbeat-timeout", type=float, default=DEFAULT_GCS_HEARTBEAT_TIMEOUT, help="GCS heartbeat timeout before failsafe (s)")
    parser.add_argument("--mission-mode", choices=("legacy", "swarm"), default="legacy")
    parser.add_argument("--swarm-safety", help="JSON site safety configuration (required in swarm mode)")
    parser.add_argument("--swarm-journal", default="swarm-companion-state.json")
    return parser.parse_args()


# ─── State Machine ───────────────────────────────────────────────────────

class BridgeState:
    """
    State utama companion_bridge, diakses dari beberapa thread.
    Lock digunakan untuk mencegah race condition.
    """
    def __init__(self, uav_id=1):
        self.lock = threading.Lock()
        self.uav_id = uav_id              # UAV identity for swarm routing
        self.mission_items = []            # Mission items dari GCS
        self.mission_uploaded_to_fc = False # True setelah FC ACK MISSION_ACCEPTED
        self.mission_running = False       # True selama flight sequence berjalan
        self.pending_mission = None        # Antrian mission baru saat terbang
        self.total_waypoints = 0           # Jumlah waypoint yang di-upload ke FC
        self.stop_event = threading.Event()

        # Flight phase tracking for swarm coordination
        self.flight_phase = "IDLE"         # IDLE|PRECHECK|ARMING|TAKEOFF|HOVER_STABILIZING|AUTO_RUNNING|COMPLETED
        self.hover_stable_since = 0.0      # timestamp when hover became stable
        self.last_gcs_heartbeat = 0.0      # timestamp of last GCS heartbeat
        self.gcs_alive = False             # True if GCS heartbeat is recent


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

def _is_fc_message(fc_conn, msg):
    return (msg.get_srcSystem() == fc_conn.target_system
            and msg.get_srcComponent() == fc_conn.target_component)


def _bind_fc(fc_conn, timeout=10.0):
    """Select an actual autopilot heartbeat, never a GCS/companion heartbeat."""
    expected = getattr(fc_conn, "expected_system", None)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        hb = fc_conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if hb is None or hb.autopilot == mavutil.mavlink.MAV_AUTOPILOT_INVALID:
            continue
        if hb.get_srcComponent() != mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1:
            continue
        if expected is not None and hb.get_srcSystem() != expected:
            continue
        fc_conn.target_system = hb.get_srcSystem()
        fc_conn.target_component = hb.get_srcComponent()
        fc_conn.expected_system = hb.get_srcSystem()
        return hb
    return None


def _mission_reply_for_us(fc_conn, msg):
    return (_is_fc_message(fc_conn, msg)
            and getattr(msg, "target_system", 0) in (0, fc_conn.mav.srcSystem)
            and getattr(msg, "target_component", 0) in (0, fc_conn.mav.srcComponent)
            and getattr(msg, "mission_type", 0) == mavutil.mavlink.MAV_MISSION_TYPE_MISSION)


def upload_mission_to_fc(fc_conn, mission_items, gcs_conn, state,
                         timeout=2.0, max_retries=3):
    """Upload until a matching final ACK; service repeated requests throughout.

    Errors abort the transaction. Timeouts retry COUNT or the last item.
    Do not clear the FC's mission as a workaround for a rejected upload.
    """
    with state.lock:
        state.mission_uploaded_to_fc = False
        state.total_waypoints = 0
    total = len(mission_items)
    sent = set()
    last_request = None
    retries = 0
    try:
        if not total:
            raise ValueError("Mission kosong")
        # Validate all coordinates before starting a partial transfer.
        for wp in mission_items:
            _mission_item_fields(wp, use_int=True)
        if not fc_conn.target_system or not fc_conn.target_component:
            if _bind_fc(fc_conn) is None:
                raise RuntimeError("Tidak ada heartbeat autopilot; cek IP/port/SYSID")

        # Discard queued replies from previous transactions before COUNT.
        drain_until = time.monotonic() + 0.25
        while time.monotonic() < drain_until:
            msg = fc_conn.recv_match(blocking=False)
            if msg is None:
                break
            if msg.get_type() == "STATUSTEXT" and _is_fc_message(fc_conn, msg):
                print(f"[FC] {msg.text}")

        print(f"[*] Forward-upload {total} mission items ke FC "
              f"{fc_conn.target_system}/{fc_conn.target_component} "
              f"dari {fc_conn.mav.srcSystem}/{fc_conn.mav.srcComponent}...")
        send_status_to_gcs(gcs_conn, f"[*] Upload {total} wp ke FC...")

        def send_count():
            fc_conn.mav.mission_count_send(
                fc_conn.target_system, fc_conn.target_component, total,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION)

        send_count()
        deadline = time.monotonic() + timeout
        overall_deadline = time.monotonic() + max(30.0, total * timeout * (max_retries + 1))
        while not state.stop_event.is_set() and time.monotonic() < overall_deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if retries >= max_retries:
                    raise TimeoutError(f"Upload timeout; sent={sorted(sent)}, last_request={last_request}")
                retries += 1
                print(f"[!] Upload timeout — retry {retries}/{max_retries}")
                if last_request is None:
                    send_count()
                else:
                    seq, request_type = last_request
                    _send_item_to_fc(fc_conn, seq, mission_items[seq], total, request_type)
                deadline = time.monotonic() + timeout
                continue
            msg = fc_conn.recv_match(
                type=["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK", "STATUSTEXT"],
                blocking=True, timeout=min(remaining, 0.5))
            if msg is None:
                continue
            kind = msg.get_type()
            if kind == "STATUSTEXT":
                if _is_fc_message(fc_conn, msg):
                    print(f"[FC] {msg.text}")
                    send_status_to_gcs(gcs_conn, f"FC: {msg.text}", msg.severity)
                continue
            if not _mission_reply_for_us(fc_conn, msg):
                continue
            if kind == "MISSION_ACK":
                if msg.type != mavutil.mavlink.MAV_MISSION_ACCEPTED:
                    entry = mavutil.mavlink.enums["MAV_MISSION_RESULT"].get(msg.type)
                    name = entry.name if entry else "UNKNOWN"
                    raise RuntimeError(f"FC tolak mission: {name} (ACK type={msg.type}), "
                                       f"sent={sorted(sent)}, last_request={last_request}")
                if len(sent) != total:
                    print("[!] Abaikan ACK ACCEPTED sebelum semua item diminta/dikirim")
                    continue
                with state.lock:
                    state.mission_uploaded_to_fc = True
                    state.total_waypoints = total
                print(f"[+] FC menerima mission! ({total} items, ACK ACCEPTED)")
                send_status_to_gcs(gcs_conn, f"[+] FC terima {total} wp - ACCEPTED")
                return True
            seq = msg.seq
            if not 0 <= seq < total:
                raise ValueError(f"FC minta seq={seq} invalid (total={total})")
            _send_item_to_fc(fc_conn, seq, mission_items[seq], total, kind)
            # Remain in this loop even after the last item: the FC may re-request it.
            if seq not in sent:
                retries = 0
            sent.add(seq)
            last_request = (seq, kind)
            deadline = time.monotonic() + timeout
            print(f"[*] Kirim wp {seq+1}/{total} ke FC ({kind})")
        raise TimeoutError("Upload dihentikan / batas waktu total tercapai")
    except Exception as exc:
        print(f"[-] {exc}")
        send_status_to_gcs(gcs_conn, f"[-] {exc}", severity=3)
        return False


def _mission_item_fields(wp, use_int):
    """GCS receiver stores global x/y in degrees; preserve altitude reference."""
    frame = wp.get("frame", mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT)
    # (float frame, integer frame), global/relative/terrain altitude.
    pairs = ((0, 5), (3, 6), (10, 11))
    pair = next((p for p in pairs if frame in p), None)
    if pair is None:
        raise ValueError(f"Frame {frame} tidak didukung oleh bridge waypoint global")
    lat, lon, alt = float(wp["x"]), float(wp["y"]), float(wp["z"])
    if not all(math.isfinite(v) for v in (lat, lon, alt)):
        raise ValueError("Koordinat/altitude waypoint harus finite")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Latitude/longitude harus derajat, bukan integer E7")
    return (pair[1] if use_int else pair[0],
            int(round(lat * 1e7)) if use_int else lat,
            int(round(lon * 1e7)) if use_int else lon, alt)


def _send_item_to_fc(fc_conn, seq, wp, total, request_type="MISSION_REQUEST_INT"):
    use_int = request_type == "MISSION_REQUEST_INT"
    frame, x, y, z = _mission_item_fields(wp, use_int)
    sender = fc_conn.mav.mission_item_int_send if use_int else fc_conn.mav.mission_item_send
    sender(fc_conn.target_system, fc_conn.target_component,
           seq, frame, wp["command"], 0, wp.get("autocontinue", 1),
           float(wp.get("param1", 0)), float(wp.get("param2", 0)),
           float(wp.get("param3", 0)), float(wp.get("param4", 0)),
           x, y, z, mavutil.mavlink.MAV_MISSION_TYPE_MISSION)


# ─── Flight Sequence (with hover stabilization for swarm) ────────────────

def execute_flight_sequence(fc_conn, gcs_conn, state, config):
    """
    Jalankan urutan terbang secara drip-feed (adaptive waypoint upload).

    Swarm enhancement: adds HOVER_STABILIZING phase between takeoff and AUTO.
    The copter must reach target altitude, have low vertical speed, and
    maintain stability for a configurable duration before entering AUTO.
    """
    takeoff_alt = config["takeoff_alt_m"]
    hold_duration = config["hold_duration_s"]
    hover_alt_tol = config.get("hover_alt_tolerance", DEFAULT_HOVER_ALT_TOLERANCE)
    hover_vz_thr = config.get("hover_vz_threshold", DEFAULT_HOVER_VZ_THRESHOLD)
    hover_min_dur = config.get("hover_min_duration", DEFAULT_HOVER_MIN_DURATION)

    with state.lock:
        mission_items = state.mission_items[:]

    total_wp = len(mission_items)
    if total_wp < 2:
        print("[-] Mission tidak valid (butuh minimal 2 wp)")
        send_status_to_gcs(gcs_conn, "[-] Error: Butuh min 2 wp")
        with state.lock:
            state.mission_running = False
            state.flight_phase = "FAILED"
        return

    print(f"[*] ═══ MEMULAI FLIGHT SEQUENCE (DRIP-FEED) ═══")
    print(f"[*] UAV-{state.uav_id} | Takeoff: {takeoff_alt}m | Hold: {hold_duration}s | WP: {total_wp}")
    send_status_to_gcs(gcs_conn, f"[*] UAV-{state.uav_id} memulai flight...")

    try:
        # Loop drip feed untuk setiap target waypoint (mulai dari seq=1)
        for wp_idx in range(1, total_wp):
            print(f"[*] --- DRIP-FEED: WP {wp_idx}/{total_wp-1} ---")
            send_status_to_gcs(gcs_conn, f"[*] Menuju WP {wp_idx}/{total_wp-1}")

            if state.stop_event.is_set():
                return
            # Confirm a live FC and leave AUTO before replacing its active mission.
            if _bind_fc(fc_conn) is None:
                print("[-] Tidak ada heartbeat dari FC yang dipilih")
                return
            if not _set_mode(fc_conn, "GUIDED"):
                print("[-] GUIDED tidak terkonfirmasi; upload dibatalkan")
                return

            # Buat mini-mission: [Home, Target]
            mini_mission = [mission_items[0], mission_items[wp_idx]]
            if not upload_mission_to_fc(fc_conn, mini_mission, gcs_conn, state):
                print(f"[-] Gagal upload mini-mission untuk WP {wp_idx}")
                send_status_to_gcs(gcs_conn, f"[-] Gagal upload WP {wp_idx}")
                return

            if wp_idx == 1:
                # ── PRECHECK ──
                with state.lock:
                    state.flight_phase = "PRECHECK"
                print("[*] Phase: PRECHECK")

                # ── Step 1: Set mode GUIDED ──
                if not _set_mode(fc_conn, "GUIDED"):
                    print("[-] Gagal set mode GUIDED!")
                    with state.lock:
                        state.flight_phase = "FAILED"
                    return

                # ── ARMING ──
                with state.lock:
                    state.flight_phase = "ARMING"
                print("[*] Phase: ARMING")

                if not _arm_vehicle(fc_conn, max_retries=3):
                    print("[-] Gagal arm copter!")
                    with state.lock:
                        state.flight_phase = "FAILED"
                    return

                # ── TAKEOFF ──
                with state.lock:
                    state.flight_phase = "TAKEOFF"
                print("[*] Phase: TAKEOFF")

                fc_conn.mav.command_long_send(
                    fc_conn.target_system, fc_conn.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                    0, 0, 0, 0, 0, 0, 0, takeoff_alt
                )
                if not _wait_for_altitude(fc_conn, takeoff_alt, timeout=30):
                    print("[-] Timeout menunggu altitude takeoff!")
                    with state.lock:
                        state.flight_phase = "FAILED"
                    return
                print(f"[+] Altitude {takeoff_alt}m tercapai!")

                # ── HOVER STABILIZATION ──
                with state.lock:
                    state.flight_phase = "HOVER_STABILIZING"
                print(f"[*] Phase: HOVER_STABILIZING (min {hover_min_dur}s)")
                send_status_to_gcs(gcs_conn, f"[*] Hover stabilizing...")

                if not _wait_for_hover_stable(
                    fc_conn, takeoff_alt, hover_alt_tol,
                    hover_vz_thr, hover_min_dur, state,
                ):
                    print("[-] Hover stabilization gagal/timeout!")
                    send_status_to_gcs(gcs_conn, "[-] Hover not stable")
                    with state.lock:
                        state.flight_phase = "FAILED"
                    return
                print("[+] Hover stable — ready for AUTO")
                send_status_to_gcs(gcs_conn, "[+] Hover stable")

            # ── Step 4: Set MISSION_CURRENT = 1 (Target) ──
            fc_conn.mav.mission_set_current_send(
                fc_conn.target_system,
                fc_conn.target_component,
                1
            )

            # ── AUTO_RUNNING ──
            with state.lock:
                state.flight_phase = "AUTO_RUNNING"

            if not _set_mode(fc_conn, "AUTO"):
                print("[-] Gagal set mode AUTO!")
                with state.lock:
                    state.flight_phase = "FAILED"
                return

            # Verify AUTO mode actually engaged via heartbeat
            if not _verify_mode(fc_conn, 3, timeout=3.0):  # 3 = AUTO
                print("[-] FC tidak dalam mode AUTO setelah set!")
                send_status_to_gcs(gcs_conn, "[-] AUTO mode not confirmed")
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
                with state.lock:
                    state.flight_phase = "COMPLETED"
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
            if state.flight_phase != "COMPLETED":
                state.flight_phase = "FAILED"
        print(f"[*] Flight sequence selesai: {state.flight_phase}")
        print("[+] ===========================================")
        print("[+] Masuk ke mode LISTEN: Menunggu misi baru...")
        print()
        print("═══════════════════════════════════════════════════")
        print("  Companion Bridge READY — menunggu perintah GCS")
        print("  Upload mission ≠ mulai terbang (safety gate)")
        print("═══════════════════════════════════════════════════")
        print()
        send_status_to_gcs(gcs_conn, f"[*] {state.flight_phase} (LISTEN MODE)")
        _check_pending_mission(fc_conn, gcs_conn, state)


def _wait_for_hover_stable(fc_conn, target_alt, alt_tolerance, vz_threshold, min_duration, state, timeout=30):
    """
    Wait until the copter is hovering stably at target_alt.

    Criteria:
      - Altitude within target_alt ± alt_tolerance
      - Vertical speed (vz) below vz_threshold
      - Both conditions must hold for min_duration seconds continuously
    """
    start = time.time()
    stable_since = None

    while time.time() - start < timeout and not state.stop_event.is_set():
        msg = fc_conn.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=1.0)
        if msg is None:
            continue

        current_alt = msg.relative_alt / 1000.0  # mm → m
        current_vz = abs(msg.vz / 100.0)         # cm/s → m/s

        alt_ok = abs(current_alt - target_alt) <= alt_tolerance
        vz_ok = current_vz <= vz_threshold

        if alt_ok and vz_ok:
            if stable_since is None:
                stable_since = time.time()
            elif time.time() - stable_since >= min_duration:
                with state.lock:
                    state.hover_stable_since = stable_since
                return True
        else:
            stable_since = None  # Reset — not stable yet

    return False


def _verify_mode(fc_conn, expected_mode_id, timeout=3.0):
    """Verify that the FC is actually in the expected mode via heartbeat."""
    start = time.time()
    while time.time() - start < timeout:
        msg = fc_conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
        if msg and _is_fc_message(fc_conn, msg) and msg.custom_mode == expected_mode_id:
            return True
    return False


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
        if msg and _is_fc_message(fc_conn, msg) and msg.custom_mode == mode_id:
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
    """Stage queued data locally; only a new explicit START may upload/run it.

    Avoid a second FC reader/upload after mission_running has been released.
    """
    with state.lock:
        if state.mission_running or state.pending_mission is None:
            return
        pending = state.pending_mission
        state.pending_mission = None
        state.mission_items = pending
        state.mission_uploaded_to_fc = False
    print(f"[*] Pending mission siap ({len(pending)} items); menunggu START baru")
    send_status_to_gcs(gcs_conn, "[*] Pending siap; menunggu START baru")


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

            # Capability probes from the assignment-only client must not keep
            # a legacy flight alive after its actual GCS has disconnected.
            if msg_type == "TUNNEL":
                continue

            # Setiap pesan valid dari GCS memperbarui heartbeat timestamp
            with state.lock:
                state.last_gcs_heartbeat = time.time()
                state.gcs_alive = True

            # ── Terima Mission dari GCS ──
            if msg_type == "MISSION_COUNT":
                count = msg.count
                print(f"\n[*] ═══ MISSION_COUNT diterima dari GCS: {count} items ═══")

                # Terima semua mission items
                mission_items = receive_mission_from_gcs(gcs_conn, count, state)
                if mission_items is None:
                    print("[-] Gagal menerima mission dari GCS")
                    continue

                # Update local queue atomically with START/flight state.
                with state.lock:
                    is_running = state.mission_running
                    if is_running:
                        state.pending_mission = mission_items
                    else:
                        state.mission_items = mission_items
                        state.mission_uploaded_to_fc = False

                if is_running:
                    # ── Adaptive Update: queue mission baru ──
                    print("[*] Mission sedang berjalan — mission baru di-queue")
                    send_status_to_gcs(gcs_conn, "[*] Mission berjalan, di-queue")
                else:
                    send_status_to_gcs(gcs_conn, "[+] Mission siap; menunggu START")

            # ── Sinyal Start Mission dari GCS ──
            elif msg_type == "COMMAND_LONG":
                if msg.command == MAV_CMD_USER_1:
                    print("\n[*] ═══ SINYAL START MISSION diterima dari GCS ═══")
                    _handle_start_command(gcs_conn, fc_conn, state, config)

            # ── Heartbeat dari GCS (koneksi hidup) ──
            elif msg_type == "HEARTBEAT":
                pass  # Timestamp sudah diperbarui di atas

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
      - mission_items harus sudah diterima dari GCS
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
        state.last_gcs_heartbeat = time.time()
        state.gcs_alive = True
        state.gcs_lost = False

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

# ─── GCS Heartbeat Watchdog ──────────────────────────────────────────────

def gcs_heartbeat_watchdog(fc_conn, gcs_conn, state, config):
    """
    Monitor GCS heartbeat. If lost for too long during flight, switch to LOITER.

    SAFETY: Never disarm while airborne. Only switch to safe hover mode.
    """
    timeout = config.get("gcs_heartbeat_timeout", DEFAULT_GCS_HEARTBEAT_TIMEOUT)
    print(f"[+] GCS heartbeat watchdog active (timeout={timeout}s)")

    while not state.stop_event.is_set():
        state.stop_event.wait(1.0)

        with state.lock:
            is_flying = state.mission_running
            last_hb = state.last_gcs_heartbeat
            phase = state.flight_phase

        if not is_flying:
            continue

        if last_hb > 0 and (time.time() - last_hb) > timeout:
            # GCS heartbeat lost during flight!
            if phase in ("AUTO_RUNNING", "HOVER_STABILIZING", "NAVIGATING", "HOLDING", "TAKEOFF"):
                print(f"[!] GCS heartbeat lost ({time.time() - last_hb:.1f}s) — switching to LOITER")
                send_status_to_gcs(gcs_conn, "[!] GCS LOST - LOITER")
                _set_mode(fc_conn, "LOITER")
                with state.lock:
                    state.gcs_alive = False


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
        "hover_alt_tolerance": args.hover_alt_tolerance,
        "hover_vz_threshold": args.hover_vz_threshold,
        "hover_min_duration": args.hover_min_duration,
        "gcs_heartbeat_timeout": args.gcs_heartbeat_timeout,
    }

    print(f"[*] Konfigurasi:")
    print(f"    UAV ID           : {args.uav_id}")
    print(f"    GCS listen port  : {listen_port}")
    print(f"    FC connection    : {fc_connection}")
    print(f"    FC baud rate     : {fc_baud}")
    print(f"    Takeoff altitude : {args.takeoff_alt}m")
    print(f"    Hold per WP      : {args.hold_duration}s")
    print(f"    Hover tolerance  : ±{args.hover_alt_tolerance}m")
    print(f"    GCS HB timeout   : {args.gcs_heartbeat_timeout}s")
    print()

    # State
    state = BridgeState(uav_id=args.uav_id)

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
    hb = None
    try:
        kwargs = {
            "source_system": 1,
            "source_component": mavutil.mavlink.MAV_COMP_ID_ONBOARD_COMPUTER
        }
        if fc_connection.startswith(("udp:", "udpin:", "udpout:", "tcp:", "tcpin:")):
            fc_conn = mavutil.mavlink_connection(fc_connection, **kwargs)
        else:
            # Serial connection
            fc_conn = mavutil.mavlink_connection(fc_connection, baud=fc_baud, **kwargs)

        print("[*] Menunggu heartbeat dari FC...")
        fc_conn.expected_system = args.fc_system_id
        hb = _bind_fc(fc_conn, timeout=10)
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

    fc_conn.expected_system = args.fc_system_id or getattr(fc_conn, "expected_system", None)

    if args.mission_mode == "swarm":
        # Swarm has a single FC reader and does not start legacy listener/watchdog
        # threads. Its own non-blocking engine preserves GCS/FC failsafe handling.
        import json
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from mission_scripts.swarm_companion import SwarmCompanion
        if not args.swarm_safety or hb is None or not fc_conn.target_system or not fc_conn.target_component:
            raise SystemExit("Swarm requires --swarm-safety and an identified FC heartbeat")
        if hb.autopilot != mavutil.mavlink.MAV_AUTOPILOT_ARDUPILOTMEGA or hb.type not in (2, 3, 4, 13, 14, 15, 29, 35):
            raise SystemExit("Swarm GUIDED engine requires an ArduPilot copter autopilot")
        safety = json.loads(Path(args.swarm_safety).read_text())
        SwarmCompanion(fc_conn, gcs_conn, args.uav_id, os.environ.get("SWARM_LINK_KEY", ""),
                       safety, args.swarm_journal, config).run()
        return

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

    watchdog_thread = threading.Thread(
        target=gcs_heartbeat_watchdog,
        args=(fc_conn, gcs_conn, state, config),
        daemon=True,
        name="gcs-watchdog"
    )
    watchdog_thread.start()
    print("[+] GCS heartbeat watchdog thread aktif")

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

from pymavlink import mavutil
from rich.live import Live
from rich.table import Table
import math
import time
import msvcrt

master = mavutil.mavlink_connection("tcp:100.121.12.16:5761")
print("Menunggu heartbeat dari drone...")
master.wait_heartbeat()
print("Heartbeat diterima!")

telemetry = {
    "Mode": "-",
    "Armed": "-",
    "GPS": "-",
    "Latitude": "-",
    "Longitude": "-",
    "Altitude": "-",
    "Roll": "-",
    "Pitch": "-",
    "Yaw": "-",
    "Ground Speed": "-",
    "Air Speed": "-",
    "Voltage": "-",
    "Battery": "-",
    "WP Status": "Siap (Tekan 1: UI, 2: Pati, 3: Zurich)"
}

def make_table():
    table = Table(title="UAV TELEMETRY (Tekan 1/2/3 untuk upload WP)")
    table.add_column("Parameter", style="cyan", width=18)
    table.add_column("Value", style="green", width=40)
    for k, v in telemetry.items():
        table.add_row(k, str(v))
    return table

def upload_waypoints(master, waypoints, live):
    telemetry["WP Status"] = "Membersihkan waypoint lama..."
    live.update(make_table())
    master.mav.mission_clear_all_send(master.target_system, master.target_component)
    master.recv_match(type=['MISSION_ACK'], blocking=True, timeout=2)
    
    telemetry["WP Status"] = f"Mengirim {len(waypoints)} waypoint..."
    live.update(make_table())
    master.mav.mission_count_send(master.target_system, master.target_component, len(waypoints))
    
    for i in range(len(waypoints)):
        msg = master.recv_match(type=['MISSION_REQUEST_INT', 'MISSION_REQUEST'], blocking=True, timeout=2)
        if not msg:
            telemetry["WP Status"] = "Gagal menerima request waypoint dari drone."
            live.update(make_table())
            return
            
        seq = msg.seq
        lat, lon, alt = waypoints[seq]
        
        master.mav.mission_item_int_send(
            master.target_system,
            master.target_component,
            seq,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            16, # MAV_CMD_NAV_WAYPOINT
            0, # current
            1, # autocontinue
            0, 0, 0, 0, # param 1-4
            int(lat * 1e7),
            int(lon * 1e7),
            alt
        )
        telemetry["WP Status"] = f"Waypoint {seq} terkirim."
        live.update(make_table())
        
    msg = master.recv_match(type=['MISSION_ACK'], blocking=True, timeout=2)
    if msg and msg.type == 0:
        telemetry["WP Status"] = "Semua waypoint berhasil diupload!"
    else:
        telemetry["WP Status"] = f"Hasil upload: {msg}"
    live.update(make_table())

# Daftar waypoint (Latitude, Longitude, Altitude dalam meter)
routes = {
    "1": [
        (-7.77126, 110.37765, 50), # UGM
        (-6.36060, 106.82740, 50)  # UI
    ],
    "2": [
        (-7.77126, 110.37765, 50), # UGM
        (-6.753887777437846, 111.02430178533939, 50)  # SMA 1 Pati
    ],
    "3": [
        (-7.77126, 110.37765, 50), # UGM
        (47.37630, 8.54770, 50)    # ETH Zurich
    ]
}

with Live(make_table(), refresh_per_second=10) as live:
    while True:
        # Cek apakah ada input keyboard
        if msvcrt.kbhit():
            key = msvcrt.getch().decode('utf-8', errors='ignore').lower()
            if key in routes:
                upload_waypoints(master, routes[key], live)
        
        # Ambil pesan dari MAVLink dengan timeout pendek agar tidak memblokir pembacaan keyboard
        msg = master.recv_match(blocking=True, timeout=0.1)
        if msg is None:
            continue

        t = msg.get_type()

        if t == "HEARTBEAT":
            telemetry["Mode"] = mavutil.mode_string_v10(msg)
            telemetry["Armed"] = (
                "True"
                if msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                else "False"
            )
        elif t == "GPS_RAW_INT":
            telemetry["GPS"] = f"{msg.fix_type}D ({msg.satellites_visible} Sat)"
        elif t == "GLOBAL_POSITION_INT":
            telemetry["Latitude"] = f"{msg.lat/1e7:.7f}"
            telemetry["Longitude"] = f"{msg.lon/1e7:.7f}"
            telemetry["Altitude"] = f"{msg.relative_alt/1000:.2f} m"
            telemetry["Ground Speed"] = f"{msg.vx/100:.2f} m/s"
        elif t == "VFR_HUD":
            telemetry["Air Speed"] = f"{msg.airspeed:.2f} m/s"
        elif t == "ATTITUDE":
            telemetry["Roll"] = f"{math.degrees(msg.roll):.2f}°"
            telemetry["Pitch"] = f"{math.degrees(msg.pitch):.2f}°"
            telemetry["Yaw"] = f"{math.degrees(msg.yaw):.2f}°"
        elif t == "SYS_STATUS":
            telemetry["Voltage"] = f"{msg.voltage_battery/1000:.2f} V"
            telemetry["Battery"] = f"{msg.battery_remaining} %"

        live.update(make_table())
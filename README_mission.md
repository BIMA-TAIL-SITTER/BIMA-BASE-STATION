# Mission Control System — GCS → Companion (Raspi) → FC

Sistem pengiriman, monitoring, dan kontrol misi UAV melalui 3 file Python yang bekerja bersama via MAVLink.

## Arsitektur

```
GCS (laptop)                     Raspi (companion)                FC (ArduPilot)
┌──────────────────┐  udpout     ┌───────────────────┐  serial   ┌──────────┐
│ gcs_mission_     │────────────→│ companion_        │──────────→│ Flight   │
│ client.py        │←────────────│ bridge.py         │←──────────│ Contrl   │
└──────────────────┘  udpin      └───────────────────┘           └──────────┘
        ↑
        │ import
┌──────────────────┐
│ control_uav.py   │  (waypoint definitions)
└──────────────────┘
```

## Prasyarat

```bash
pip install pymavlink
```

## File

| File | Lokasi | Deskripsi |
|------|--------|-----------|
| `control_uav.py` | GCS (laptop) | Definisi waypoint manual — edit di sini |
| `gcs_mission_client.py` | GCS (laptop) | Client CLI: upload, start, monitor |
| `companion_bridge.py` | Raspi | Bridge: terima dari GCS, forward ke FC, eksekusi flight |
| `mission_config.json` | Shared | Konfigurasi port/IP — diubah dari web UI atau manual |

## Konfigurasi Port

### Di Sisi GCS (Laptop)
1. Buka GCS web dashboard
2. Klik **Edit Connection** (ikon gear)
3. Di kartu **UAV 3** atau **UAV 4** (Copter), isi:
   - **MISSION UDP PORT**: Port untuk komunikasi GCS ↔ Raspi (default: `14560`)
4. Klik **SAVE & RECONNECT**
5. Port otomatis tersimpan ke `mission_config.json` di laptop.

### Di Sisi Raspi (Companion)
Konfigurasi koneksi ke Flight Controller dilakukan langsung saat menjalankan script menggunakan CLI arguments:
```bash
python companion_bridge.py --listen-port 14560 --fc-connection /dev/ttyACM0 --fc-baud 57600
```

### Untuk SITL Testing
Ganti argumen `--fc-connection` ke UDP:
```bash
python companion_bridge.py --fc-connection udp:127.0.0.1:14551
```

## Cara Pakai

### 1. Edit Waypoint
Buka `control_uav.py`, edit konfigurasi `DEFAULT_TAKEOFF_ALT`, `HOLD_DURATION` dan fungsi `build_mission()`:
```python
DEFAULT_TAKEOFF_ALT = 5  # meter
HOLD_DURATION = 10       # detik

def build_mission():
    ...
```

### 2. Jalankan Companion Bridge (di Raspi)
```bash
python companion_bridge.py --listen-port 14560 --fc-connection /dev/ttyACM0 --fc-baud 57600
```
Output:
```
═══════════════════════════════════════════════════
  Companion Bridge — BIMA Raspberry Pi
═══════════════════════════════════════════════════

[*] Konfigurasi:
    GCS listen port  : 14560
    FC connection    : /dev/ttyACM0
    ...
[+] Koneksi GCS aktif
[+] FC heartbeat diterima!
[+] Companion Bridge READY — menunggu perintah GCS
```

### 3. Jalankan GCS Client (di laptop)
```bash
python gcs_mission_client.py
```
Output:
```
═══════════════════════════════════════════════════
  GCS Mission Client — BIMA Ground Station
═══════════════════════════════════════════════════

[*] Konfigurasi koneksi:
    Raspi IP      : 192.168.1.12
    Mission UDP   : 14560
[+] Koneksi UDP dibuat
[*] Mengirim MISSION_COUNT (4 item) ke Raspi...
[+] Mission upload berhasil!

[GCS] Ketik 'start' untuk menerbangkan, 'update' untuk upload ulang, atau 'exit':
```

### 4. Start Mission
```
[GCS] Ketik 'start' untuk menerbangkan, 'update' untuk upload ulang, atau 'exit': start
[*] Mengirim sinyal START MISSION ke Raspi...
[+] Sinyal START MISSION diterima Raspi!
    [*] Memulai flight sequence...
    [+] Mode: GUIDED
    [+] ARMED!
    [*] Takeoff ke 5m
    [+] Alt 5m OK
    [+] Mode: AUTO
    [*] MISSION_START!
    [+] WP 1 reached (1/4)
    [*] Hold 10s di WP1
    ...
    [+] DISARMED! Mission SELESAI!
```

### 5. Update Waypoint Tanpa Restart
1. Edit `control_uav.py`
2. Di CLI GCS, ketik `update`
3. Mission baru akan di-upload ke Raspi → FC

## Safety Gate

**Upload mission ≠ mulai terbang!**

- Setelah upload, FC menerima mission tapi motor TIDAK armed.
- Copter baru terbang setelah user ketik `start` di GCS.
- Sinyal start dikirim via `MAV_CMD_USER_1` (COMMAND_LONG).
- Raspi validasi: mission sudah di-upload ke FC DAN tidak ada mission berjalan.

## Adaptive Update

Jika mission baru dikirim saat copter sedang terbang:
- Mission baru di-**queue** (tidak langsung upload ke FC).
- Setelah mission selesai (disarm), mission dari queue otomatis di-upload.
- Tetap butuh sinyal `start` lagi untuk menerbangkan mission baru.

## Perintah CLI

| Perintah | Deskripsi |
|----------|-----------|
| `start` | Kirim sinyal start mission ke Raspi |
| `update` | Reload `control_uav.py` dan upload ulang mission |
| `status` | Tampilkan info koneksi |
| `exit` | Keluar dari program |

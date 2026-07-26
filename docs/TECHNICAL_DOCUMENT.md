# 📡 BIMA UAV Ground Control Station (GCS) — Technical Document

> **Version:** 1.0.0 | **Tanggal:** 25 Juli 2026 | **Stack:** FastAPI + Next.js 15 (Split-Stack)

---

## Daftar Isi

1. [Gambaran Umum Sistem](#1-gambaran-umum-sistem)
2. [Arsitektur Sistem](#2-arsitektur-sistem)
3. [Struktur Repository](#3-struktur-repository)
4. [Backend — FastAPI Engine](#4-backend--fastapi-engine)
5. [Frontend — Next.js Command Centre](#5-frontend--nextjs-command-centre)
6. [Protokol Komunikasi](#6-protokol-komunikasi)
7. [REST API Reference](#7-rest-api-reference)
8. [Konfigurasi Environment](#8-konfigurasi-environment)
9. [Deployment](#9-deployment)
10. [Dependensi](#10-dependensi)
11. [Roadmap: AI Decision Layer](#11-roadmap-ai-decision-layer)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Gambaran Umum Sistem

**BIMA GCS** adalah Ground Control Station (GCS) berbasis web untuk memantau dan mengoperasikan beberapa UAV (*Unmanned Aerial Vehicle*) secara bersamaan. Sistem ini dibangun menggunakan **Split-Stack Architecture** yang memisahkan backend real-time dari frontend dashboard modern.

### Kapabilitas Utama

| Fitur | Deskripsi |
|---|---|
| **Multi-UAV Video** | Menerima, mendekode, dan meneruskan stream video JPEG via UDP dari hingga 2 UAV secara bersamaan |
| **YOLOv11 Detection** | Deteksi objek real-time menggunakan Ultralytics YOLOv11 di thread terpisah tanpa memblokir video |
| **Dual-Slot MAVLink** | Koneksi simultan ke 2 autopilot (ArduPilot/PX4) via TCP, parsing lengkap data penerbangan |
| **Primary Flight Display** | Artificial horizon, altitude tape, dan speed indicator berbasis SVG dengan animasi `requestAnimationFrame` |
| **Offline GIS Map** | Tile server satelit offline dari MBTiles SQLite dengan fallback auto-download dari Esri |
| **Tailscale Integration** | Dukungan jaringan overlay terenkripsi untuk deployment lapangan via 4G/LTE |

---

## 2. Arsitektur Sistem

```
                       BIMA SPLIT-STACK GCS

  UAV & EDGE SENSORS          FASTAPI BACKEND (Port 8000)            NEXT.JS 15 CLIENT (Port 3000)
+------------------+     +----------------------------------+       +----------------------------+
| UDP JPEG Stream  |─UDP►| MultiStreamManager + VideoReceiver|       | VideoPanel + HudCanvas.tsx |
| Port 5000, 5006  |     |  └─ YOLODetector (background)    |──WS──►|  └─ Canvas JPEG rendering  |
+------------------+     +----------------------------------+       +----------------------------+
| MAVLink Autopilot|─TCP►| MavlinkTelemetryBridge (2 slots) |──WS──►| AttitudeIndicator + Stats  |
| Port 5761        |     |  └─ HEARTBEAT, ATTITUDE, GPS     |       |  └─ PFD SVG + Telemetry    |
+------------------+     +----------------------------------+       +----------------------------+
| UDP JSON Overlay |─UDP►| UdpTelemetryReceiver (Port 5005) |──WS──►| Bounding Box + Crosshair   |
| bbox_px, lat/lon |     |  └─ Target coordinates overlay   |       |  └─ Canvas overlay HUD     |
+------------------+     +----------------------------------+       +----------------------------+
| MBTiles / Esri   |─HTTP| PetaRouter (/api/peta/ubin/z/x/y)|─HTTP─►| PetaOfflineUav (Leaflet)   |
| Satellite tiles  |     |  └─ SQLite auto-cache + fallback  |       |  └─ Interactive GIS Map    |
+------------------+     +----------------------------------+       +----------------------------+
```

### Prinsip Arsitektur

- **Decoupled / Split-Stack**: Backend FastAPI dan frontend Next.js berjalan sebagai proses independen. Frontend mengambil konfigurasi dinamis dari `/api/config` saat startup.
- **Dependency Injection**: Service global (`video_manager`, `telemetry_generator`, `yolo_detector`, `ws_manager`) dibuat di `main.py` dan diinjeksikan ke setiap router melalui modul-level variables pada event `lifespan`.
- **Thread-per-Stream**: Setiap `VideoReceiver` berjalan dalam daemon thread terpisah. YOLO detector berjalan dalam worker thread sendiri, terpisah dari event loop asyncio.
- **Zero-DOM Canvas**: Semua rendering frame video dan overlay YOLO dilakukan langsung ke `<canvas>` HTML5 untuk menghindari React re-render bottleneck.

---

## 3. Struktur Repository

```
BIMA-BASE-STATION/
├── app/                              # FastAPI Backend Engine
│   ├── main.py                       # Entrypoint, lifespan, CORS, routing
│   ├── config/
│   │   └── settings.py               # Pydantic Settings (env-var driven)
│   ├── routers/
│   │   ├── video.py                  # /ws/video/{port} + /api/video/*
│   │   ├── telemetry.py              # /ws/telemetry + /api/telemetry/*
│   │   ├── system.py                 # /ws/system + /api/system/*
│   │   └── peta.py                   # /api/peta/ubin/{z}/{x}/{y}.png
│   └── services/
│       ├── video/
│       │   ├── receiver.py           # VideoReceiver: UDP socket + camera (daemon thread)
│       │   └── manager.py            # MultiStreamManager: broadcast loop + YOLO overlay
│       ├── mavlink/
│       │   ├── interfaces.py         # Abstract base classes MAVLink
│       │   ├── connection.py         # MavlinkTCPConnection (pymavlink)
│       │   └── telemetry_bridge.py   # MavlinkTelemetryBridge: dual-slot parsing
│       ├── telemetry/
│       │   ├── generator.py          # TelemetryPacket dataclass + fallback generator
│       │   └── udp_telemetry.py      # UdpTelemetryReceiver: JSON target overlay
│       ├── yolo/
│       │   └── detector.py           # YOLODetector: background inference worker
│       └── websocket/
│           └── manager.py            # WebSocketManager: multi-channel hub
│
├── gcs-client/                       # Next.js 15 Frontend (Port 3000)
│   └── src/
│       ├── app/
│       │   ├── layout.tsx            # Root layout + GCSProvider wrapper
│       │   ├── page.tsx              # GCSDashboard: grid layout utama
│       │   └── globals.css           # Tailwind CSS tokens + custom styling
│       ├── components/
│       │   ├── header/TopBar.tsx     # Header: Tailscale IP, YOLO toggle, theme switch
│       │   ├── map/PetaOfflineUav.tsx # Leaflet map + offline tile + UAV markers
│       │   ├── modal/                # ConnectionSetupModal + EditConnectionModal
│       │   ├── telemetry/            # AttitudeIndicator, AltitudeTape, TelemetryStats
│       │   └── video/                # VideoPanel + HudCanvas (canvas rendering)
│       ├── hooks/
│       │   ├── useGCSStore.tsx       # Global state via React Context
│       │   └── useWebSocket.ts       # Reusable WebSocket hook
│       └── types/telemetry.ts        # TypeScript interfaces
│
├── data/peta_offline.mbtiles          # SQLite MBTiles database (~36 MB)
├── logs/                             # Rotating log files
├── best.pt / yolo11n.pt / yolov8n.pt # YOLO model weights
├── requirements.txt                  # Python dependencies
├── Dockerfile + docker-compose.yml   # Container configs
├── .env.example                      # Template konfigurasi environment
├── AI_DECISION_LAYER_AUDIT.md        # Audit arsitektur AI Decision Layer
└── swarm_integration_audit_plan.md   # Rencana integrasi UAV swarm
```

---

## 4. Backend — FastAPI Engine

### 4.1 Entry Point & Lifespan

**File:** `app/main.py`

Inisialisasi seluruh sistem menggunakan pattern **asynccontextmanager lifespan** FastAPI:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    yolo_detector.start()                          # Background YOLO thread
    telemetry_task = asyncio.create_task(          # Async telemetry broadcast
        telemetry_generator.broadcast_loop()
    )
    yield  # App running
    
    # Shutdown
    telemetry_task.cancel()
    video_manager.stop_all()
    await telemetry_generator.stop()
    yolo_detector.stop()
```

**Service instances yang dibuat secara global:**

| Instance | Kelas | Fungsi |
|---|---|---|
| `ws_manager` | `WebSocketManager` | Hub multi-channel WebSocket |
| `yolo_detector` | `YOLODetector` | Background inference worker |
| `video_manager` | `MultiStreamManager` | Manajer multi-stream video |
| `telemetry_generator` | `MavlinkTelemetryBridge` | Dual-slot MAVLink bridge |

**Logging:** `RotatingFileHandler` → `logs/ground_station.log` (10 MB max, 5 backup files)

**IP Detection:** Fungsi `get_tailscale_ip()` mendeteksi IP Tailscale (prefix `100.x`) dengan fallback ke LAN IP via routing `8.8.8.8`.

---

### 4.2 Konfigurasi (Settings)

**File:** `app/config/settings.py` — Menggunakan **Pydantic Settings** dengan env file binding:

```python
class Settings(BaseSettings):
    HOST: str = "0.0.0.0"
    WEB_PORT: int = 8000
    VIDEO_FPS_LIMIT: int = 30
    VIDEO_JPEG_QUALITY: int = 80
    YOLO_ENABLED: bool = True
    YOLO_MODEL_PATH: str = "yolo11n.pt"
    YOLO_CONF_THRESHOLD: float = 0.4
    YOLO_IOU_THRESHOLD: float = 0.45
    YOLO_MAX_FPS: float = 10.0
    TELEMETRY_HZ: float = 5.0
    MAVLINK_HOSTS: str = "100.121.12.16,..."
    MAVLINK_DEFAULT_PORT: int = 5761
    
    model_config = {"env_file": ".env"}
```

---

### 4.3 Routers

#### Video Router (`app/routers/video.py`)

| Endpoint | Metode | Fungsi |
|---|---|---|
| `/ws/video/{port}` | WebSocket | Stream JPEG binary per frame + JSON detections |
| `/api/video/status` | GET | Statistik semua stream aktif |
| `/api/video/detect` | POST | JPEG body → YOLO inference → JSON bounding boxes |
| `/api/video/yolo/toggle` | POST | Toggle YOLO on/off secara dinamis |

**Lifecycle WebSocket Video:**
```
Client connect → ensure_stream(port, json_port)
                → VideoReceiver start (jika belum ada)
                → broadcast_loop task (asyncio.create_task)
Client disconnect → stop_stream(port) jika tidak ada client lain
```

#### Telemetry Router (`app/routers/telemetry.py`)

| Endpoint | Metode | Fungsi |
|---|---|---|
| `/ws/telemetry` | WebSocket | JSON snapshot MAVLink @ 5 Hz |
| `/api/telemetry/latest` | GET | Snapshot terakhir slot 1 & 2 |
| `/api/telemetry/sources` | GET | Daftar IP MAVLink dari settings |
| `/api/telemetry/connect` | POST | Connect MAVLink slot `{slot, ip, port}` |
| `/api/telemetry/disconnect` | POST | Disconnect MAVLink slot |
| `/api/telemetry/status` | GET | Status koneksi per slot |

#### Peta (Map) Router (`app/routers/peta.py`)

| Endpoint | Metode | Fungsi |
|---|---|---|
| `/api/peta/ubin/{z}/{x}/{y}.png` | GET | Tile satelit offline (MBTiles + Esri fallback) |

**Alur Tile Request:**
```
Request tile (z, x, y)
  → y_terbalik = 2^z - 1 - y  (MBTiles Y-inversion)
  → Query SQLite: SELECT tile_data WHERE zoom=z, col=x, row=y_terbalik
  ├─ Ditemukan       → Response PNG langsung
  ├─ Tidak ada       → Download dari Esri World Imagery → Simpan ke MBTiles → Response PNG
  └─ Offline/Error   → Generate placeholder dark grid tile (PIL)
```

#### System Router (`app/routers/system.py`)

| Endpoint | Metode | Fungsi |
|---|---|---|
| `/ws/system` | WebSocket | Live system events + replay 50 log terakhir |
| `/api/system/events` | GET | Hingga 200 log events terakhir |
| `/api/system/info` | GET | Platform info, PID, Python version |

---

### 4.4 Services

#### VideoReceiver (`app/services/video/receiver.py`)

Berjalan sebagai **daemon thread**. Mendukung dua mode:

| Mode | Deskripsi |
|---|---|
| `"udp"` | Listens UDP socket, decode raw JPEG dari packet |
| `"camera"` | `cv2.VideoCapture` untuk webcam lokal |

- **Thread Safety:** Frame terbaru di `self._latest_frame` dengan `threading.Lock`
- **Socket Tuning:** `SO_RCVBUF = 4 MB` untuk mengurangi kernel-level packet drops
- **Stats:** `ReceiverStats` melacak `fps`, `frame_count`, `drop_count` secara atomik

> **Catatan Implementasi:** Receiver saat ini memperlakukan seluruh UDP datagram sebagai raw JPEG (tanpa 4-byte length header). Format header yang ada di README adalah contoh sender, bukan protokol yang di-enforce oleh receiver.

#### MultiStreamManager (`app/services/video/manager.py`)

Mengelola satu `VideoReceiver` + `asyncio.Task` broadcast loop per port:

```
MultiStreamManager
  ├─ _receivers: {port: VideoReceiver}
  ├─ _tasks: {port: asyncio.Task}              ← _broadcast_loop coroutine
  ├─ _telemetry_receivers: {json_port: UdpTelemetryReceiver}
  └─ _video_to_telemetry: {video_port: json_port}
```

**Broadcast Loop (`_broadcast_loop`):**
1. Tidur hingga `next_send` (frame interval)
2. Cek apakah ada WebSocket client untuk port ini
3. Ambil `receiver.latest_frame`
4. Overlay UDP telemetry (bounding box + crosshair via `cv2.rectangle`)
5. Encode frame ke JPEG (`cv2.imencode`)
6. Enqueue frame ke YOLO detector (jika enabled)
7. Broadcast binary JPEG ke semua client
8. Broadcast JSON detections terakhir (UDP telemetry)

**No-Signal Placeholder:** Gambar `320x180` gelap dengan teks "NO SIGNAL" dikirim saat tidak ada frame masuk.

#### MavlinkTelemetryBridge (`app/services/mavlink/telemetry_bridge.py`)

Mengelola dua slot koneksi MAVLink independen:

**MAVLink Messages yang Di-parse:**

| Message Type | Field yang Dipetakan |
|---|---|
| `HEARTBEAT` | `flight_mode`, `armed` |
| `GLOBAL_POSITION_INT` | `lat`, `lon`, `altitude_m`, `relative_alt_m`, `vx/vy/vz`, `ground_speed_ms` |
| `ATTITUDE` | `roll_deg`, `pitch_deg`, `yaw_deg` (rad → deg: × 57.2958) |
| `VFR_HUD` | `air_speed_ms`, `heading_deg`, `climb_rate_ms` |
| `SYS_STATUS` | `battery_voltage`, `battery_current`, `battery_remaining_pct` |
| `GPS_RAW_INT` | `gps_fix`, `satellites_visible`, `hdop` |

**Flight Mode Mapping (ArduCopter):**
```python
{0: "STABILIZE", 1: "ACRO", 2: "ALT_HOLD", 3: "AUTO",
 4: "GUIDED", 5: "LOITER", 6: "RTL", 7: "CIRCLE", 9: "LAND", 16: "POSHOLD"}
```

**Race Condition Guard:** Token system `_connect_tokens` memastikan permintaan koneksi lama yang selesai belakangan akan dibuang (*stale connection guard*).

#### MavlinkTCPConnection (`app/services/mavlink/connection.py`)

Wrapper asyncio di atas `pymavlink.mavutil`:
- Koneksi blocking dijalankan via `asyncio.to_thread`
- Menggunakan `asyncio.wait` (bukan `wait_for`) untuk timeout — menghindari pemblokiran event loop
- Heartbeat wait timeout: **2 detik**, overall connection timeout: **3 detik**

#### YOLODetector (`app/services/yolo/detector.py`)

Menjalankan Ultralytics YOLO inference di **background daemon thread** dengan rate limiter independen (`YOLO_MAX_FPS`):
- Model dimuat saat `start()` dipanggil
- Frame dienqueue oleh `MultiStreamManager`
- Worker thread menjalankan `model.predict()`, broadcast hasil ke WebSocket sebagai JSON text
- Thread-safe via `threading.Lock` pada `_inference_lock`

#### WebSocketManager (`app/services/websocket/manager.py`)

Multi-channel hub:
```
WebSocketManager
  ├─ _video_clients: {port: set[WebSocket]}
  ├─ _telemetry_clients: set[WebSocket]
  └─ _system_clients: set[WebSocket]
```

#### MAVLink Interfaces — Abstract (`app/services/mavlink/interfaces.py`)

| Interface | Fungsi |
|---|---|
| `MAVLinkConnection` | Abstraksi physical link (TCP/UDP/Serial) |
| `MAVLinkTelemetryBridge` | Abstraksi parsing & broadcasting telemetry |
| `MAVLinkMissionManager` | Upload/download/clear mission waypoints |
| `MAVLinkCommandSender` | Arm, disarm, set mode, takeoff, RTL |

---

## 5. Frontend — Next.js Command Centre

### 5.1 Halaman Utama & Layout (`gcs-client/src/app/page.tsx`)

Komponen `GCSDashboard` mengimplementasikan **grid 2-kolom resizable**:

```
+─────────────────────────────────+───+─────────────────────────+
|  KOLOM MONITORING KIRI (53%)    | ║ |  KOLOM PETA KANAN (47%) |
|  +──────────────────────────+   |   |                         |
|  |  UAV 1: VideoPanel       |   |   |  PetaOfflineUav         |
|  |  + AttitudeIndicator     |   |   |  (Leaflet Interactive)  |
|  |  + TelemetryStats        |   |   |                         |
|  +──────────────────────────+   |   |                         |
|  |  UAV 2: VideoPanel       |   |   |                         |
|  |  + AttitudeIndicator     |   |   |                         |
|  |  + TelemetryStats        |   |   |                         |
|  +──────────────────────────+   |   |                         |
+─────────────────────────────────+───+─────────────────────────+
```

**Key behaviors:**
- **Draggable Splitter:** Pembatas tengah dapat digeser antara 25%–78%
- **Telemetry WebSocket:** `ws://{ws_host}/ws/telemetry` — attitude disimpan di `useRef`, diperbarui via `requestAnimationFrame` @ 30 FPS
- **Auto-Connect MAVLink:** POST ke `/api/telemetry/connect` otomatis setelah konfigurasi (delay 800ms)
- **Timeout Detection:** Status `DISCONNECTED` jika tidak ada update telemetry > 3 detik
- **Config Fetch:** `GET /api/config` saat mount untuk mendapat `ws_host`, `tailscale_ip`, `yolo_enabled`

---

### 5.2 Komponen UI

#### VideoPanel (`components/video/VideoPanel.tsx`)
- WebSocket ke `/ws/video/{port}?json_port={jsonPort}`
- Mode: **UAV (UDP stream)** atau **KAMERA (webcam lokal)**
- Render JPEG biner ke `<canvas>` via `createImageBitmap` + `ctx.drawImage`
- Mode kamera: kirim frame ke `POST /api/video/detect` untuk YOLO REST inference

#### HudCanvas (`components/video/HudCanvas.tsx`)
- Canvas overlay transparan di atas video
- Menggambar bounding boxes (label + confidence) dan crosshair targeting
- Tidak menyebabkan React re-render saat diperbarui

#### AttitudeIndicator / PFD (`components/telemetry/AttitudeIndicator.tsx`)
- Artificial horizon SVG — rotasi berdasarkan `roll_deg`, translasi berdasarkan `pitch_deg`
- Heading tape bergeser berdasarkan `heading_deg`
- Altitude readout MSL vs relative

#### TelemetryStats (`components/telemetry/TelemetryStats.tsx`)
- GPS coordinates, altitude MSL & relative, ground/air speed, climb rate
- Battery voltage, current, persentase
- Satellite count, HDOP, GPS fix type, flight mode, armed status
- UDP target data (lat, lon, distance, GSD)

#### PetaOfflineUav (`components/map/PetaOfflineUav.tsx`)
- Leaflet + react-leaflet dengan tile source: `/api/peta/ubin/{z}/{x}/{y}.png`
- Marker UAV 1 & 2 dengan ikon custom + rotasi berdasarkan heading
- Loaded via `next/dynamic` dengan `ssr: false` (Leaflet membutuhkan `window`)

---

### 5.3 State Management (`hooks/useGCSStore.tsx`)

Menggunakan **React Context + useState** (bukan Zustand meski disebutkan di README):

```typescript
interface GCSStoreState {
  config: GCSConfig | null;          // Server config dari /api/config
  uav1: UAVConnectionConfig | null;  // Konfigurasi koneksi UAV 1
  uav2: UAVConnectionConfig | null;  // Konfigurasi koneksi UAV 2
  isConfigured: boolean;             // Setup modal sudah selesai?
  theme: ThemeMode;                  // "dark" | "light"
  yoloEnabled: boolean;
}
```

**Persistensi localStorage:**
- `bima_gcs_uav_1`, `bima_gcs_uav_2` — konfigurasi UAV
- `bima_gcs_configured` — flag setup selesai

#### useWebSocket (`hooks/useWebSocket.ts`)
- Auto-reconnect saat URL tersedia dan koneksi terputus
- Callback `onMessage(data: string)` untuk text messages
- Membedakan `Blob` (binary JPEG frame) vs `string` (JSON detections/telemetry)

---

### 5.4 Tipe Data TypeScript (`types/telemetry.ts`)

```typescript
interface TelemetryData {
  slot: 1 | 2;
  vehicle_id: number; vehicle_name: string;
  lat: number; lon: number;
  altitude_m: number; relative_alt_m: number;
  roll_deg: number; pitch_deg: number; yaw_deg: number;
  air_speed_ms: number; ground_speed_ms: number; climb_rate_ms: number;
  heading_deg: number;
  battery_voltage: number; battery_current: number; battery_remaining_pct: number;
  gps_fix: number; satellites_visible: number; hdop: number;
  flight_mode: string; armed: boolean;
  timestamp: number;
}

interface GCSConfig {
  ws_host: string;
  tailscale_ip: string;
  yolo_enabled: boolean;
  web_port: number;
}

type MavlinkStatus = "DISCONNECTED" | "CONNECTED" | "ARMED" | "DISARMED";
```

---

## 6. Protokol Komunikasi

### 6.1 UDP Video Streaming

```
Sender (UAV companion computer):
  sock.sendto(jpeg_bytes, (GCS_IP, PORT))

Receiver (VideoReceiver):
  packet, addr = sock.recvfrom(65535)
  frame = cv2.imdecode(np.frombuffer(packet, dtype=np.uint8), IMREAD_COLOR)
```

**Port defaults:**
- UAV-1 video: `5000` | UAV-2 video: `5006` | UDP JSON overlay: `5005`

### 6.2 WebSocket Channels

| Channel | Path | Data Type | Rate |
|---|---|---|---|
| Video Stream | `/ws/video/{port}` | `Blob` (binary JPEG) | hingga 30 FPS |
| Video Detections | `/ws/video/{port}` | `string` (JSON) | setiap deteksi baru |
| Telemetry | `/ws/telemetry` | `string` (JSON) | 5 Hz |
| System Events | `/ws/system` | `string` (JSON) | event-driven |

**Video channel message disambiguation (satu WebSocket connection):**
```javascript
ws.onmessage = (event) => {
  if (event.data instanceof Blob) {
    // Binary JPEG frame → render ke canvas
  } else {
    const data = JSON.parse(event.data);
    if (data.type === 'telemetry') { /* UDP target overlay */ }
    else if (data.type === 'detections') { /* YOLO bounding boxes */ }
  }
};
```

### 6.3 MAVLink TCP

```
MAVLink Autopilot
  └─ TCP Server (:5761)
       └─ MavlinkTCPConnection (pymavlink via asyncio.to_thread)
            └─ wait_heartbeat(timeout=2.0)
                 └─ recv_msg() non-blocking loop → parse → TelemetryPacket
                      └─ broadcast_telemetry(json) @ 5 Hz
```

### 6.4 UDP Telemetry Overlay

Format JSON dari UAV edge computer ke port `5005`:

```json
{
  "detection": true,
  "bbox_px": [120, 80, 340, 400],
  "conf": 0.85,
  "lokasi_target": {
    "lat": -6.8912,
    "lon": 107.6105,
    "alt_m": 725.4
  }
}
```

`UdpTelemetryReceiver` menyimpan data terakhir → `MultiStreamManager` membaca per frame → gambar overlay di frame sebelum encoding JPEG.

---

## 7. REST API Reference

### System

| Method | Path | Response |
|---|---|---|
| `GET` | `/health` | `{status, video, yolo, clients}` |
| `GET` | `/api/config` | `{ws_host, tailscale_ip, yolo_enabled, web_port}` |
| `GET` | `/api/system/info` | Platform, PID, Python version |
| `GET` | `/api/system/events` | Last 200 log events |

### Video

| Method | Path | Request | Response |
|---|---|---|---|
| `GET` | `/api/video/status` | — | `{streams: {port: {receiving, fps, drops, ...}}}` |
| `POST` | `/api/video/detect` | JPEG binary body | `{type, count, detections[], inference_ms}` |
| `POST` | `/api/video/yolo/toggle` | — | `{enabled: bool}` |

**Detection Object Format:**
```json
{
  "x1": 100.0, "y1": 80.0, "x2": 340.0, "y2": 400.0,
  "cx": 220.0, "cy": 240.0,
  "label": "person", "conf": 0.856, "class_id": 0, "color": "#D5FF40"
}
```

### Telemetry

| Method | Path | Request | Response |
|---|---|---|---|
| `GET` | `/api/telemetry/latest` | — | `{slot_1: TelemetryPacket, slot_2: TelemetryPacket}` |
| `GET` | `/api/telemetry/sources` | — | `{hosts: [...], default_port: 5761}` |
| `GET` | `/api/telemetry/status` | — | `{1: bool, 2: bool}` |
| `POST` | `/api/telemetry/connect` | `{slot, ip, port}` | `{success: bool}` |
| `POST` | `/api/telemetry/disconnect` | `{slot}` | `{success: bool}` |

### Map

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/peta/ubin/{z}/{x}/{y}.png` | PNG 256×256 |

---

## 8. Konfigurasi Environment

File `.env` (salin dari `.env.example`):

| Variable | Default | Deskripsi |
|---|---|---|
| `HOST` | `0.0.0.0` | Bind address FastAPI |
| `WEB_PORT` | `8000` | HTTP + WebSocket port |
| `UDP_PORT` | `5000` | UDP port video stream default |
| `VIDEO_FPS_LIMIT` | `30` | Maks FPS via WebSocket |
| `VIDEO_JPEG_QUALITY` | `80` | Kualitas re-encode JPEG (1–100) |
| `VIDEO_MAX_CLIENTS` | `10` | Maks koneksi WebSocket video |
| `TAILSCALE_ENABLED` | `false` | Enable Tailscale network logging |
| `LOG_LEVEL` | `INFO` | Level logging Python |
| `TELEMETRY_HZ` | `5.0` | Rate broadcast telemetry (Hz) |
| `MAVLINK_HOSTS` | `100.121.12.16,...` | List IP MAVLink (comma-separated) |
| `MAVLINK_DEFAULT_PORT` | `5761` | Port MAVLink TCP default |
| `YOLO_ENABLED` | `true` | Master switch YOLO detection |
| `YOLO_MODEL_PATH` | `yolo11n.pt` | Path ke model weights |
| `YOLO_CONF_THRESHOLD` | `0.4` | Min confidence score |
| `YOLO_IOU_THRESHOLD` | `0.45` | IoU threshold NMS |
| `YOLO_MAX_FPS` | `10.0` | Maks rate YOLO inference (Hz) |
| `YOLO_DEVICE` | `""` | Device: `""` (auto), `"cpu"`, `"cuda:0"` |
| `YOLO_TARGET_CLASSES` | `"person"` | Kelas target COCO (comma-separated) |
| `SNAPSHOT_DIR` | `snapshots` | Direktori penyimpanan snapshot |

**Frontend env var:**
```bash
# gcs-client/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 9. Deployment

### 9.1 Standalone (Split-Stack)

**Backend (Terminal 1):**
```bash
cd BIMA-BASE-STATION
python -m venv venv
source venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
cp .env.example .env       # Edit sesuai kebutuhan
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend (Terminal 2):**
```bash
cd BIMA-BASE-STATION/gcs-client
npm install
npm run dev    # http://localhost:3000
```

### 9.2 Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f      # Monitor logs
docker compose down         # Stop
```

**Docker config highlights:**
```yaml
ports:
  - "${WEB_PORT:-8000}:8000"      # HTTP + WebSocket
  - "${UDP_PORT:-5000}:5000/udp"  # UDP video stream
sysctls:
  net.core.rmem_max: 4194304      # Buffer UDP 4 MB
healthcheck:
  test: curl -f http://localhost:8000/health
  interval: 10s
```

> **Catatan:** Docker Compose saat ini hanya backend FastAPI. Frontend Next.js perlu dijalankan terpisah.

### 9.3 Tailscale Field Deployment

```bash
# GCS laptop
tailscale up
tailscale ip -4     # Contoh: 100.121.12.16

# .env
TAILSCALE_ENABLED=true
MAVLINK_HOSTS=100.121.12.16,100.x.x.x

# gcs-client/.env.local
NEXT_PUBLIC_API_URL=http://100.121.12.16:8000
```

**Windows Firewall (PowerShell Admin):**
```powershell
netsh advfirewall firewall add rule name="GCS_UDP_Video" dir=in action=allow protocol=UDP localport=5000-5010
netsh advfirewall firewall add rule name="GCS_Backend_API" dir=in action=allow protocol=TCP localport=8000
netsh advfirewall firewall add rule name="GCS_NextJS_UI" dir=in action=allow protocol=TCP localport=3000
```

---

## 10. Dependensi

### Python Backend (`requirements.txt`)

| Package | Versi | Fungsi |
|---|---|---|
| `fastapi` | 0.115.5 | Web framework + WebSocket |
| `uvicorn[standard]` | 0.32.1 | ASGI server |
| `pydantic` | 2.10.3 | Data validation |
| `pydantic-settings` | 2.7.0 | Environment variable binding |
| `jinja2` | 3.1.4 | Template engine (legacy HTML) |
| `aiofiles` | 24.1.0 | Async static file serving |
| `websockets` | 14.1 | WebSocket support |
| `opencv-python-headless` | 4.11.0.86 | JPEG decode/encode, CV operations |
| `numpy` | 2.2.6 | Array processing |
| `ultralytics` | 8.3.55 | YOLOv11 inference engine |
| `pymavlink` | 2.4.41 | MAVLink protocol library |

### JavaScript Frontend (`package.json`)

| Package | Versi | Fungsi |
|---|---|---|
| `next` | 16.2.10 | React SSR framework |
| `react` | 19.2.4 | UI library |
| `react-dom` | 19.2.4 | DOM rendering |
| `leaflet` | 1.9.4 | GIS mapping library |
| `react-leaflet` | 5.0.0 | Leaflet React bindings |
| `tailwindcss` | 4.x | Utility CSS framework |
| `typescript` | 5.x | Type safety |

### Model Files

| File | Ukuran | Deskripsi |
|---|---|---|
| `yolo11n.pt` | ~5.4 MB | YOLOv11 Nano — model default |
| `yolov8n.pt` | ~6.3 MB | YOLOv8 Nano — alternatif |
| `best.pt` | ~6.0 MB | Custom trained model |

---

## 11. Roadmap: AI Decision Layer

Berdasarkan `AI_DECISION_LAYER_AUDIT.md`, sistem ini telah diaudit untuk kesiapan integrasi AI Decision Layer.

### Infrastruktur yang Sudah Tersedia

| Komponen | Status | Implementasi |
|---|---|---|
| Multi-UAV telemetry slots | ✅ | Dual-slot MAVLink bridge |
| YOLO real-time detection | ✅ | YOLODetector background thread |
| UDP target coordinates | ✅ | UdpTelemetryReceiver |
| Abstract MAVLink interfaces | ✅ | `interfaces.py` dengan ABC |
| WebSocket broadcast hub | ✅ | WebSocketManager multi-channel |

### Komponen yang Perlu Ditambahkan

```
AI Decision Layer (Rencana):
├── WorldModel                    ← Centralized state store semua UAV
├── TargetManager                 ← Spatial clustering (Haversine)
│   └── target_tracks: dict       ← ID tracking per deteksi
├── MAVLinkCommandSender (konkrit)
│   ├── arm() / disarm()
│   ├── set_mode("AUTO")
│   ├── takeoff(altitude_m)
│   └── return_to_launch()
├── MissionUploadPipeline         ← Upload waypoint otomatis
└── SwarmCoordinator              ← Koordinasi scout/observer UAV
    ├── Scout UAV (2 slot)        ← Deteksi target
    └── Observer UAV (2 slot)     ← Konfirmasi & dokumentasi
```

### Integrasi Swarm (4 UAV Slots)

Dari `swarm_integration_audit_plan.md`:
- Ekspansi `MavlinkTelemetryBridge` dari 2 slot ke 4 slot
- `TargetManager` dengan Haversine clustering untuk dedup target
- Closed-loop command: deteksi → kalkulasi → kirim MAVLink waypoint → konfirmasi ACK

---

## 12. Troubleshooting

| Gejala | Resolusi |
|---|---|
| **"NO SIGNAL" / Video blank** | Pastikan sender mengirim ke IP yang benar dan port UDP tepat. Cek firewall rules. |
| **Frontend tidak connect ke backend** | Pastikan FastAPI di port `8000`. Verifikasi CORS `allow_origins=["*"]` dan `/api/config` return 200. |
| **MAVLink "DISCONNECTED"** | Cek TCP endpoint reachable: `nc -zv UAV_IP 5761`. Pastikan autopilot mengirim heartbeat. |
| **Peta dark grid** | Tidak ada tile offline + tidak ada internet. Connect internet agar Esri tiles auto-cache ke MBTiles. |
| **YOLO tidak mendeteksi** | Cek `ultralytics` terinstall, `YOLO_ENABLED=true`, nama kelas di `YOLO_TARGET_CLASSES` sesuai COCO. |
| **CPU tinggi / latency tinggi** | Turunkan `VIDEO_FPS_LIMIT` (→20), `VIDEO_JPEG_QUALITY` (→70), atau `YOLO_MAX_FPS` (→5.0) di `.env`. |
| **Port sudah dipakai (Errno 98)** | Ganti `WEB_PORT` di `.env` atau `npm run dev -- -p 3001` untuk frontend. |
| **Tailscale IP tidak terdeteksi** | Jalankan `tailscale up`. Fungsi `get_tailscale_ip()` deteksi IP `100.x` otomatis. |

---

## Appendix: Data Flow Diagram

```
[UAV Camera] ─UDP─► [VideoReceiver] ─daemon thread─ stores latest_frame
                           │
                [MultiStreamManager] ─asyncio broadcast loop
                     ├─ cv2.imencode JPEG
                     ├─ YOLODetector.enqueue(frame)    [background thread]
                     ├─ WebSocket broadcast (binary)   → [Browser Canvas]
                     └─ JSON detections broadcast      → [Browser HudCanvas]
                           │
              [YOLODetector] ─daemon worker thread
                     model.predict(frame)
                     └─ broadcast_video_detections(json) → [Browser HudCanvas]

[MAVLink Autopilot] ─TCP─► [MavlinkTCPConnection] ─pymavlink recv_msg()
                                   │
                     [MavlinkTelemetryBridge] ─asyncio loop @ 5 Hz
                          parse HEARTBEAT, ATTITUDE, GPS, VFR_HUD, SYS_STATUS
                          └─ broadcast_telemetry(json) → [Browser AttitudeIndicator + Stats]

[Browser Leaflet Map] ─HTTP─► [PetaRouter] ─SQLite query
                                └─ Response PNG 256×256 ← [Esri fallback jika offline]
```

---

*Dokumen ini dibuat berdasarkan analisis seluruh source code project BIMA-BASE-STATION pada 25 Juli 2026.*

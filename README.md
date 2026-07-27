# BIMA UAV Ground Control Station (GCS)

A modern, high-performance, and decoupled **Multi-UAV Ground Control Station** powered by a **Split-Stack Architecture**. It combines a real-time **FastAPI backend engine** for UDP video ingestion, asynchronous YOLOv11 object detection, Dual-Slot MAVLink telemetry bridging, and MBTiles offline GIS mapping with a state-of-the-art **Next.js 15 & React 19 Command Centre dashboard**.

```
                           ┌──────────────────────────────────────────────────────────────┐
                           │                    BIMA SPLIT-STACK GCS                      │
                           └──────────────────────────────────────────────────────────────┘

  UAV & EDGE SENSORS                          FASTAPI BACKEND ENGINE (Port 8000)                   NEXT.JS 15 CLIENT (Port 3000)
┌────────────────────┐               ┌──────────────────────────────────────────────────┐        ┌───────────────────────────────┐
│ UDP JPEG Streams   │──UDP 5000+───►│ MultiStreamManager + VideoReceiver               │        │ VideoPanel & Canvas HUD       │
│ (Camera Feed)      │               │  ├─ Asynchronous YOLODetector (Ultralytics v11)  │──WS───►│  ├─ Real-Time Frame Render  │
└────────────────────┘               │  └─ UdpTelemetryReceiver (Target Geodata Overlay)│        │  └─ Zero-DOM Bounding Boxes   │
┌────────────────────┐               ├──────────────────────────────────────────────────┤        ├───────────────────────────────┤
│ MAVLink Autopilot  │──TCP 5761+───►│ MavlinkTelemetryBridge (Dual-Slot Architecture)  │──WS───►│ Telemetry & Navigation Panel  │
│ (ArduPilot/PX4)    │               │  ├─ Heartbeat, Attitude, Global Position & HUD   │        │  ├─ AttitudeIndicator (PFD)   │
└────────────────────┘               │  └─ High-Rate Telemetry Snapshots (5 Hz)         │        │  └─ Altitude & Speed Tapes    │
┌────────────────────┐               ├──────────────────────────────────────────────────┤        ├───────────────────────────────┤
│ Esri / Offline GIS │──HTTP / Local►│ Peta Offline Router (/api/peta/ubin/z/x/y.png)   │──HTTP─►│ Tactical GIS Map Engine     │
│ Satellite Imagery  │               │  └─ MBTiles SQLite Storage (peta_offline.mbtiles)│        │  └─ MapLibre / Leaflet View   │
└────────────────────┘               └──────────────────────────────────────────────────┘        └───────────────────────────────┘
```

---

## 🌟 Key Features & Architectural Highlights

### 1. Decoupled Split-Stack Architecture
- **FastAPI Real-Time Backend (`app/`)**: Pure API & WebSocket engine running on Port `8000`. Handles high-throughput network I/O, background threading models, CORS middleware, and automated configuration exposure (`/api/config`).
- **Next.js 15 Modern Command Centre (`gcs-client/`)**: Responsive, highly reactive tactical dashboard running on Port `3000`. Built with **TypeScript**, **Tailwind CSS**, and **Zustand (`useGCSStore`)**, featuring a 4-column dynamic grid layout optimized for multi-monitor desktop command centers and field tablets.

### 2. High-Performance Video & HUD Canvas Rendering
- **Dynamic Multi-Stream Video**: Ingests raw UDP JPEG streams across configurable ports (`/ws/video/{port}`). Includes optional high-frequency UDP target telemetry overlays (`?json_port={port}`) for rendering target bounding boxes (`bbox_px`) and crosshairs directly onto incoming frames.
- **Zero-DOM Canvas Optimization**: To prevent React re-render bottlenecks at high frame rates (10–30 FPS), all incoming frames and YOLO detections are drawn directly onto HTML5 `<canvas>` layers (`HudCanvas.tsx`), achieving butter-smooth tactical overlays.
- **Real-Time Asynchronous YOLOv11 Detection**: Powered by `YOLODetector` using Ultralytics (`yolo11n.pt`). Runs inference in a dedicated daemon worker thread without blocking video transmission loops. Supports REST frame submission (`POST /api/video/detect`) for client-side webcam or phone camera feeds.

### 3. Dual-Slot MAVLink Telemetry & Flight Instrumentation
- **MavlinkTelemetryBridge**: Connect to two independent MAVLink TCP streams simultaneously (**Slot 1** and **Slot 2**). Automatically decodes heartbeat, attitude (roll, pitch, yaw), global GPS coordinates, battery percentage, VFR HUD airspeed/altitude, and mission waypoints, broadcasting unified snapshots over `/ws/telemetry` at 5 Hz.
- **Primary Flight Display (PFD)**: Client-side artificial horizon and altitude tapes (`AttitudeIndicator.tsx`, `AltitudeTape.tsx`) utilizing `requestAnimationFrame` and SVG transforms (`translateY`, `rotate`) for fluid attitude visualization.

### 4. Offline GIS Satellite Mapping (`/api/peta`)
- **MBTiles SQLite Engine**: Integrated local tile server serving satellite imagery offline from `data/peta_offline.mbtiles` (`/api/peta/ubin/{zoom}/{x}/{y}.png`).
- **Auto-Cache & Fallback**: If a requested tile is not present in the local database, the server automatically fetches high-resolution imagery from Esri World Imagery, commits it to the SQLite `tiles` table with Y-axis inversion (`2^zoom - 1 - y`), and serves it seamlessly. If completely disconnected, renders dark tactical grid placeholder tiles (`buat_gambar_ubin_pengganti`).

### 5. AI Decision Layer Readiness (`AI_DECISION_LAYER_AUDIT.md`)
- Verified and architecturally audited for transition into an autonomous **AI Decision Layer** capable of coordinating up to **4 UAV slots** (Scouts and Observers).
- Prepared for centralized `WorldModel` state stores, spatial target tracking engines (`TargetManager` with Haversine clustering), and closed-loop MAVLink command actuation (`MAVLinkCommandSender` & mission upload pipelines).

---

## 📂 Repository Directory Structure

```
ground_station/
├── app/                             # FastAPI Backend Engine (Port 8000)
│   ├── main.py                      # Application entrypoint + lifespan service wiring + CORS
│   ├── config/
│   │   └── settings.py              # Pydantic Settings (env vars, Tailscale, YOLO configuration)
│   ├── routers/
│   │   ├── video.py                 # /ws/video/{port} + REST (/api/video/status, /api/video/detect)
│   │   ├── telemetry.py             # /ws/telemetry + REST (/api/telemetry/connect, /sources, /latest)
│   │   ├── system.py                # /ws/system + REST (/api/system/events, /api/system/info)
│   │   └── peta.py                  # /api/peta/ubin/{z}/{x}/{y}.png (MBTiles offline map server)
│   ├── services/
│   │   ├── video/
│   │   │   ├── receiver.py          # UDP socket & camera reader → decoded JPEG frames (daemon thread)
│   │   │   └── manager.py           # MultiStreamManager: dynamic multi-stream video & UDP target overlay
│   │   ├── telemetry/
│   │   │   ├── generator.py         # Telemetry packet schemas & fallback simulated generator
│   │   │   └── udp_telemetry.py     # UdpTelemetryReceiver: high-rate JSON target coordinates (Port 5005)
│   │   ├── mavlink/
│   │   │   ├── connection.py        # Async TCP MAVLink connection handler (pymavlink)
│   │   │   ├── interfaces.py        # Abstract interfaces for MAVLink bridges & command senders
│   │   │   └── telemetry_bridge.py  # MavlinkTelemetryBridge: multi-slot MAVLink parsing & broadcasting
│   │   ├── yolo/
│   │   │   └── detector.py          # YOLODetector: background worker thread for Ultralytics inference
│   │   └── websocket/
│   │       └── manager.py           # Multi-channel WebSocket hub (/ws/video, /ws/telemetry, /ws/system)
│   ├── static/                      # Legacy Vanilla JS/CSS assets (for standalone fallback)
│   └── templates/                   # Legacy index.html (fallback monolithic UI)
│
├── gcs-client/                      # Next.js 15 Modern Command Centre Frontend (Port 3000)
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx           # Root layout + Global theme & state providers
│   │   │   ├── page.tsx             # 4-Column tactical GCS Dashboard
│   │   │   └── globals.css          # Tailwind CSS custom styling & design tokens
│   │   ├── components/
│   │   │   ├── header/TopBar.tsx    # Header with Tailscale IP status, YOLO toggle, and Theme switch
│   │   │   ├── map/PetaOfflineUav.tsx # Offline satellite GIS map component (connecting to /api/peta)
│   │   │   ├── modal/               # ConnectionSetupModal.tsx & EditConnectionModal.tsx
│   │   │   ├── telemetry/           # AttitudeIndicator.tsx (PFD), TelemetryStats.tsx, AltitudeTape
│   │   │   └── video/               # VideoPanel.tsx & HudCanvas.tsx (High-FPS canvas rendering)
│   │   ├── hooks/                   # useWebSocket.ts & useGCSStore.ts (Zustand store)
│   │   └── types/                   # TypeScript interfaces (telemetry.ts, video.ts)
│   ├── package.json                 # Next.js & React dependencies
│   └── tailwind.config.ts / next.config.ts
│
├── data/
│   └── peta_offline.mbtiles         # MBTiles SQLite database storing high-res offline satellite tiles
├── logs/                            # Rotating server log files (ground_station.log)
├── snapshots/                       # Captured JPEG/PNG high-res snapshots from video feeds
├── AI_DECISION_LAYER_AUDIT.md       # Comprehensive architectural audit & AI roadmap
├── NEXTJS_MIGRATION_LLM_BRIEF.md    # Technical brief on the split-stack Next.js migration
├── requirements.txt                 # Python dependencies (FastAPI, pymavlink, ultralytics, Pillow)
├── Dockerfile & docker-compose.yml  # Containerization configurations
└── .env.example                     # Environment configuration variables
```

---

## 📡 Video & Telemetry Protocols

### 1. UDP Video Streaming Protocol
The backend expects standard UDP JPEG packets sent directly to target ports (default: Port `5000` for UAV-1, Port `5006` for UAV-2).

```
Packet Structure:
  [0:4]  uint32 little-endian   — declared JPEG payload length in bytes
  [4:]   bytes                  — raw JPEG image data
```

#### Python Sender Example (`cv2` + `socket`):
```python
import cv2, socket, struct, time

HOST = "127.0.0.1"   # Ground Station IP (or Tailscale IP e.g. 100.x.x.x)
PORT = 5000          # Target UDP Port
QUALITY = 80

cap = cv2.VideoCapture(0)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while True:
    ret, frame = cap.read()
    if not ret:
        break
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
    if not ok:
        continue
    data = buf.tobytes()
    packet = struct.pack("<I", len(data)) + data
    try:
        sock.sendto(packet, (HOST, PORT))
    except Exception as e:
        print(f"Send error: {e}")
    time.sleep(1 / 30)

cap.release()
sock.close()
```

### 2. UDP Target Telemetry Overlay (`?json_port={port}`)
When opening a video stream with an associated JSON port (e.g. `/ws/video/5000?json_port=5005`), `UdpTelemetryReceiver` listens on Port `5005`. If incoming JSON packets contain detection bounding boxes (`bbox_px`) or target coordinates (`lokasi_target`), the frontend canvas automatically renders green tactical boxes, crosshairs, and target geodata.

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

---

## 🚀 Quickstart & Installation

### Prerequisites
- **Python:** `3.10+` (Backend API Server)
- **Node.js:** `18+` & `npm` / `pnpm` (Next.js Frontend Dashboard)

---

### Option 1: Running the Split-Stack Environment (Recommended)

#### Step 1: Start the FastAPI Backend Engine (Terminal 1)
```bash
# 1. Navigate to the ground_station root
cd ground_station

# 2. Create virtual environment & install dependencies
python -m venv venv
# On Windows PowerShell:
.\venv\Scripts\Activate.ps1
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt

# 3. Copy environment configuration
cp .env.example .env

# 4. Launch FastAPI server on Port 8000
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*Backend is ready when you see:* `Ground Station ready — open http://0.0.0.0:8000`

#### Step 2: Start the Next.js Command Centre Frontend (Terminal 2)
```bash
# 1. Navigate to the gcs-client directory
cd ground_station/gcs-client
 
# 2. Install Node.js dependencies
npm install

# 3. Launch Next.js development server on Port 3000
npm run dev
```
*Open **[http://localhost:3000](http://localhost:3000)** in your browser to access the modern tactical dashboard.*

---

### Option 2: Running via Docker Compose

```bash
# 1. Copy environment configuration
cp .env.example .env

# 2. Build and launch container in background
docker compose up -d --build

# 3. View live server logs
docker compose logs -f

# 4. Stop environment
docker compose down
```

---

## 🔌 WebSocket & REST API Reference

### WebSocket Channels (FastAPI Port `8000`)

| Channel | Type | Description |
| :--- | :--- | :--- |
| `/ws/video/{port}` | `binary` / `text` | Streams re-encoded JPEG image bytes (up to `VIDEO_FPS_LIMIT`). Simultaneously broadcasts text JSON containing YOLO detections and UDP target telemetry. Supports query parameter `?json_port={port}`. |
| `/ws/telemetry` | `text` | JSON snapshots of MAVLink attitude, position, battery, and HUD data published at `TELEMETRY_HZ` (5 Hz). Tagged with `slot` (`1` or `2`). |
| `/ws/system` | `text` | Live JSON system logs, warnings, and events. Replays the last 50 buffered log events upon connection. |

### REST API Endpoints

| Endpoint | Method | Description |
| :--- | :---: | :--- |
| `/api/config` | `GET` | Returns server configuration (`ws_host`, `tailscale_ip`, `yolo_enabled`, `web_port`) for decoupled frontend clients. |
| `/health` | `GET` | Overall health check, active video streams, YOLO inference status, and connected client count. |
| `/api/video/status` | `GET` | Receiving statistics for all active UDP video ports. |
| `/api/video/detect` | `POST` | Accepts raw JPEG binary body, executes asynchronous YOLO inference, and returns bounding boxes. |
| `/api/video/yolo/toggle` | `POST` | Dynamically enables or disables backend YOLOv11 object detection. |
| `/api/telemetry/connect` | `POST` | Connects a MAVLink slot (`{"slot": 1, "ip": "100.x.x.x", "port": 5761}`). |
| `/api/telemetry/disconnect` | `POST` | Disconnects an active MAVLink slot (`{"slot": 1}`). |
| `/api/telemetry/latest` | `GET` | Retrieves the latest telemetry snapshot for Slot 1 and Slot 2. |
| `/api/telemetry/sources` | `GET` | Lists configured MAVLink TCP host IPs and default port (`5761`). |
| `/api/peta/ubin/{z}/{x}/{y}.png` | `GET` | Serves offline satellite imagery from local `peta_offline.mbtiles` with auto-download fallback. |
| `/api/system/events` | `GET` | Retrieves up to the last 200 buffered system log events. |
| `/api/system/info` | `GET` | Platform architecture, Python version, process PID, and environment metadata. |

---

## ⚙️ Configuration Variables (`.env`)

| Variable | Default | Description |
| :--- | :--- | :--- |
| `HOST` | `0.0.0.0` | Bind host address for the FastAPI backend |
| `WEB_PORT` | `8000` | FastAPI HTTP & WebSocket server port |
| `UDP_PORT` | `5000` | Default UDP port for incoming video stream 1 |
| `VIDEO_FPS_LIMIT` | `30` | Maximum FPS pushed over WebSocket channels |
| `VIDEO_JPEG_QUALITY` | `80` | Re-encoded JPEG quality (1–100) for WebSocket delivery |
| `TAILSCALE_ENABLED` | `false` | Enables Tailscale MagicDNS network logging & CORS handling |
| `LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TELEMETRY_HZ` | `5.0` | MAVLink telemetry broadcast rate over `/ws/telemetry` in Hz |
| `MAVLINK_HOSTS` | `100.121.12.16,...` | Comma-separated list of available MAVLink TCP host IPs |
| `MAVLINK_DEFAULT_PORT` | `5761` | Default MAVLink TCP port |
| `YOLO_ENABLED` | `true` | Master switch for backend YOLOv11 object detection |
| `YOLO_MODEL_PATH` | `yolo11n.pt` | Weights path for Ultralytics inference model |
| `YOLO_CONF_THRESHOLD` | `0.4` | Minimum confidence threshold to retain detection boxes |
| `YOLO_IOU_THRESHOLD` | `0.45` | IoU threshold for Non-Maximum Suppression (NMS) |
| `YOLO_MAX_FPS` | `10.0` | Maximum inference rate in Hz (runs independently of video FPS) |
| `YOLO_DEVICE` | `""` | Computation device: `""` (auto), `"cpu"`, or `"cuda:0"` |
| `YOLO_TARGET_CLASSES` | `"person"` | Comma-separated COCO target classes to detect (`"person,car,bus"`) |

---

## 🔐 Tailscale Setup & Field Deployment

Tailscale creates a secure zero-configuration overlay network (SD-WAN) so UAV companion computers and the Ground Control Station can communicate seamlessly across 4G/LTE/5G or local mesh networks without port forwarding or static public IPs.

```bash
# 1. Install Tailscale on UAV companion computer and GCS laptop
tailscale up

# 2. Retrieve the Tailscale IP of the Ground Station
tailscale ip -4
# Example output: 100.121.12.16

# 3. Enable Tailscale support in .env
TAILSCALE_ENABLED=true
```

### Windows Firewall Rules (Administrator PowerShell)
Ensure UDP video ports (`5000-5010`), TCP backend (`8000`), and TCP Next.js frontend (`3000`) ports are open:
```powershell
netsh advfirewall firewall add rule name="GCS_UDP_Video" dir=in action=allow protocol=UDP localport=5000-5010
netsh advfirewall firewall add rule name="GCS_Backend_API" dir=in action=allow protocol=TCP localport=8000
netsh advfirewall firewall add rule name="GCS_NextJS_UI" dir=in action=allow protocol=TCP localport=3000
```

---

## 🛠️ Troubleshooting

| Symptom | Resolution |
| :--- | :--- |
| **"NO SIGNAL" / Blank Video on Dashboard** | Verify the UDP sender script is actively sending to the exact IP (`127.0.0.1` or Tailscale `100.x.x.x`) and target UDP port. Check Windows/Linux firewall rules for UDP traffic. |
| **Next.js Client Cannot Connect to Backend** | Ensure FastAPI is running on Port `8000`. Verify `CORSMiddleware` in `app/main.py` is enabled (`allow_origins=["*"]`) and `/api/config` returns status `200`. |
| **MAVLink Status "Disconnected"** | Check that the target MAVLink TCP endpoint (`5761`) is reachable from the GCS host using `ping` or `nc -zv <UAV_IP> 5761`. Ensure `MavlinkTelemetryBridge` slot is configured with the correct IP. |
| **Offline Map Tiles Showing Dark Grids** | If completely offline and `data/peta_offline.mbtiles` is empty for those coordinates, the server renders fallback dark grid tiles (`buat_gambar_ubin_pengganti`). Connect to the internet once to allow `unduh_ubin_satelit_eksternal` to auto-cache Esri satellite imagery. |
| **YOLO Not Detecting Targets** | Verify `ultralytics` package is installed (`pip install ultralytics`), `YOLO_ENABLED=true` in `.env`, and target class names match standard COCO classes in `YOLO_TARGET_CLASSES`. |
| **High CPU / High Latency** | Lower `VIDEO_FPS_LIMIT` (e.g. `20`), decrease `VIDEO_JPEG_QUALITY` (`70`), or cap `YOLO_MAX_FPS` (`5.0`) inside `.env`. |
| **Port Already in Use (`Errno 98` / `EADDRINUSE`)** | Modify `WEB_PORT=8000` or `UDP_PORT=5000` in `.env`, or change Next.js port using `npm run dev -- -p 3001`. |


# UAV Ground Station

A web-based, multi-UAV Ground Station that receives live video over UDP, streams it to the browser in real-time via multi-channel WebSockets, runs asynchronous YOLO object detection, bridges real MAVLink telemetry, and displays everything in a modern, dark military-style command-centre interface.

```
UAVs / Camera Sources
  ├─ UDP JPEG Streams (Port 5000+)  ──► Ground Station (FastAPI + MultiStreamManager)
  │                                        ├─ /ws/video/{port}      ──► Browser Canvas (Frames + YOLO HUD)
  │                                        ├─ /ws/telemetry         ──► Live MAVLink & Target Telemetry (5 Hz)
  │                                        └─ /ws/system            ──► Log Feed & System Events
  └─ MAVLink TCP (Port 5761+)       ──► MavlinkTelemetryBridge (Slot 1 & Slot 2)
```

---

## Key Features

- **Dynamic Multi-Stream Video**: Supports simultaneous video feeds on configurable UDP ports via `/ws/video/{port}`. Includes optional UDP telemetry overlay (`?json_port={port}`) for rendering target bounding boxes and crosshairs directly onto incoming frames.
- **Real-Time YOLO Object Detection**: Integrated `YOLODetector` powered by Ultralytics (`yolo11n.pt` by default). Runs inference asynchronously in a dedicated background worker thread without blocking streaming loops. Broadcasts detections over WebSockets and provides a REST endpoint (`POST /api/video/detect`) for client-side camera/webcam detection.
- **Dual-Slot MAVLink Telemetry Bridge**: Connect to two independent MAVLink TCP streams simultaneously (Slot 1 and Slot 2). Automatically decodes heartbeat, attitude, global position, battery status, VFR HUD, and waypoints, broadcasting unified JSON telemetry snapshots at 5 Hz.
- **High-Rate UDP Target Telemetry**: Lightweight receiver (`UdpTelemetryReceiver`) for receiving high-frequency target tracking coordinates and confidence scores over UDP.
- **Responsive Command Centre UI**: Designed with CSS Grid and Flexbox for seamless adaptation between 4-column desktop monitors and mobile devices. Features sticky HUD top bars, dark/light theme toggles, live log console, and client-side camera streaming.

---

## Architecture & Directory Structure

```
ground_station/
├── app/
│   ├── main.py                      # FastAPI app entry point + lifespan service wiring
│   ├── config/
│   │   └── settings.py              # Pydantic Settings (env vars & configuration defaults)
│   ├── services/
│   │   ├── video/
│   │   │   ├── receiver.py          # UDP socket / camera reader → decoded frames (daemon thread)
│   │   │   └── manager.py           # MultiStreamManager: dynamic multi-stream video & UDP telemetry overlay
│   │   ├── telemetry/
│   │   │   ├── generator.py         # Telemetry packet schemas & data structures
│   │   │   └── udp_telemetry.py     # UdpTelemetryReceiver: lightweight high-rate JSON telemetry
│   │   ├── mavlink/
│   │   │   ├── connection.py        # Async TCP MAVLink connection handler
│   │   │   ├── interfaces.py        # Abstract interfaces for MAVLink telemetry bridges
│   │   │   └── telemetry_bridge.py  # MavlinkTelemetryBridge: multi-slot MAVLink parsing & broadcasting
│   │   ├── yolo/
│   │   │   └── detector.py          # YOLODetector: real-time asynchronous YOLO inference thread
│   │   └── websocket/
│   │       └── manager.py           # Multi-channel WebSocket hub (/ws/video, /ws/telemetry, /ws/system)
│   ├── routers/
│   │   ├── video.py                 # /ws/video/{port} + REST (/api/video/status, /api/video/detect, /yolo/toggle)
│   │   ├── telemetry.py             # /ws/telemetry + REST (/api/telemetry/connect, /disconnect, /sources, /status, /latest)
│   │   └── system.py                # /ws/system + REST (/api/system/events, /api/system/info)
│   ├── static/
│   │   ├── css/styles.css           # Responsive dark/light command-centre styling
│   │   └── js/
│   │       ├── camera.js            # Client-side webcam/phone camera capture & JPEG streaming to backend
│   │       ├── system.js            # WS client, log feed console, clock, theme toggle
│   │       ├── telemetry.js         # WS client, MAVLink slot management, DOM updates
│   │       └── video.js             # WS client, canvas renderer, YOLO bounding box overlays
│   └── templates/
│       └── index.html               # Main UI template (4-column responsive grid layout)
├── logs/                            # Rotating log files (auto-created)
├── snapshots/                       # Saved JPEG snapshots (auto-created)
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

---

## Video & Telemetry Protocols

### 1. UDP Video Stream Protocol

The backend is fully compatible with standard UDP JPEG streaming scripts.

```
Packet Structure:
  [0:4]  uint32 little-endian   — declared JPEG payload length in bytes
  [4:]   bytes                  — raw JPEG image data
```

#### Python Sender Example:
```python
import cv2, socket, struct, time

HOST = "127.0.0.1"   # Ground Station IP
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

### 2. UDP Target Telemetry Overlay (`json_port`)

When opening a video stream with an associated JSON port (e.g. `/ws/video/5000?json_port=5005`), the backend starts a `UdpTelemetryReceiver` on that port. If incoming JSON packets contain detection bounding boxes, the backend automatically renders green target boxes and crosshairs onto the video frames.

```json
{
  "detection": true,
  "bbox_px": [120, 80, 340, 400],
  "conf": 0.85
}
```

---

## Installation

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python      | 3.10+   |
| pip         | 23+     |

### Linux / macOS

```bash
# 1. Clone / extract the project
cd ground_station

# 2. Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment config
cp .env.example .env
# Edit .env as needed (UDP_PORT, WEB_PORT, YOLO_ENABLED, etc.)

# 5. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Windows

```powershell
# 1. Open PowerShell in the project directory
cd ground_station

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# If script execution is blocked:
# Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment config
copy .env.example .env

# 5. Start the server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Running the Server

```bash
# Development (auto-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Production (single worker recommended for streaming synchronization)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

# Custom ports via environment variables
WEB_PORT=9000 UDP_PORT=6000 uvicorn app.main:app --host 0.0.0.0 --port 9000
```

---

## WebSocket & REST API Reference

### WebSocket Endpoints

| Endpoint                | Type   | Description                                                                 |
|-------------------------|--------|-----------------------------------------------------------------------------|
| `/ws/video/{port}`      | binary | Raw JPEG frames for the given UDP port (up to `VIDEO_FPS_LIMIT` FPS). Also transmits YOLO text JSON detection blobs. Supports optional query param `?json_port={port}`. |
| `/ws/telemetry`         | text   | JSON MAVLink & target telemetry snapshots published at `TELEMETRY_HZ` (5 Hz). Includes `slot` identifier (`1` or `2`). |
| `/ws/system`            | text   | JSON log messages, system warnings, and application events. Replays last 50 buffered events on connect. |

### REST Endpoints

| Endpoint                   | Method | Description                                                                 |
|----------------------------|--------|-----------------------------------------------------------------------------|
| `/`                        | GET    | Ground Station main web UI                                                  |
| `/health`                  | GET    | Overall server health, active video stream stats, YOLO status, and client count |
| `/api/video/status`        | GET    | Detailed receiving statistics for all active video UDP ports                  |
| `/api/video/detect`        | POST   | Accept raw JPEG image body, run asynchronous YOLO inference, and return bounding boxes |
| `/api/video/yolo/toggle`   | POST   | Dynamically enable or disable backend YOLO object detection                 |
| `/api/telemetry/latest`    | GET    | Latest telemetry snapshot for MAVLink Slot 1 and Slot 2                     |
| `/api/telemetry/sources`   | GET    | List configured MAVLink TCP host IPs and default port                       |
| `/api/telemetry/connect`   | POST   | Connect a MAVLink slot to an IP and TCP port (`{"slot": 1, "ip": "...", "port": 5761}`) |
| `/api/telemetry/disconnect`| POST   | Disconnect an active MAVLink slot (`{"slot": 1}`)                           |
| `/api/telemetry/status`    | GET    | Current connection status for MAVLink Slot 1 and Slot 2                     |
| `/api/system/events`       | GET    | Retrieve up to the last 200 system log events                               |
| `/api/system/info`         | GET    | Server platform, Python version, PID, and environment info                  |

---

## Configuration Reference

All options are configured via environment variables or inside the `.env` file:

| Variable                | Default                             | Description                                                                 |
|-------------------------|-------------------------------------|-----------------------------------------------------------------------------|
| `HOST`                  | `0.0.0.0`                           | Bind host for the web server                                                |
| `WEB_PORT`              | `8000`                              | HTTP & WebSocket server port                                                |
| `UDP_PORT`              | `5000`                              | Default UDP port for incoming video streams                                 |
| `VIDEO_FPS_LIMIT`       | `30`                                | Maximum frames per second pushed to browser WebSocket clients               |
| `VIDEO_JPEG_QUALITY`    | `80`                                | Re-encoded JPEG quality (1–100) for WebSocket transport                     |
| `VIDEO_MAX_CLIENTS`     | `10`                                | Maximum simultaneous WebSocket clients per video stream                     |
| `TAILSCALE_ENABLED`     | `false`                             | Enable Tailscale-specific network logging & CORS handling                   |
| `LOG_LEVEL`             | `INFO`                              | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`)                  |
| `TELEMETRY_HZ`          | `5.0`                               | MAVLink telemetry broadcast rate over WebSocket in Hz                       |
| `MAVLINK_HOSTS`         | `100.121.12.16,100.109.178.125`     | Comma-separated list of available MAVLink TCP host IPs in source dropdowns  |
| `MAVLINK_DEFAULT_PORT`  | `5761`                              | Default MAVLink TCP port                                                    |
| `SNAPSHOT_DIR`          | `snapshots`                         | Directory for saving server-side image snapshots                            |
| `YOLO_ENABLED`          | `true`                              | Master toggle for backend YOLO object detection                             |
| `YOLO_MODEL_PATH`       | `yolo11n.pt`                        | Path or filename of the YOLO model weights (auto-downloads `yolo11n.pt`)    |
| `YOLO_CONF_THRESHOLD`   | `0.4`                               | Minimum confidence score to keep a detection box                            |
| `YOLO_IOU_THRESHOLD`    | `0.45`                              | IoU threshold for Non-Maximum Suppression (NMS)                             |
| `YOLO_MAX_FPS`          | `10.0`                              | Maximum YOLO inference rate in Hz (runs independently of video stream FPS)  |
| `YOLO_DEVICE`           | `""`                                | Inference computation device: `""` (auto), `"cpu"`, or `"cuda:0"`          |
| `YOLO_TARGET_CLASSES`   | `"person"`                          | Comma-separated target class names to detect (e.g. `"person,car,bus"`)       |

---

## Tailscale Setup

Tailscale creates a secure overlay network so UAVs and the ground station can communicate seamlessly over the internet without port forwarding.

```bash
# 1. Install Tailscale on both UAV companion computer and Ground Station
# 2. Authenticate both devices to the same Tailscale network
tailscale up

# 3. Find the Tailscale IP of the Ground Station
tailscale ip -4

# 4. In .env on the Ground Station, set:
TAILSCALE_ENABLED=true

# 5. UAV video sender targets the Tailscale IP of the Ground Station
HOST = "100.x.x.x"
```

### Firewall Rules
Ensure UDP video ports (e.g., 5000, 5005) and TCP web/MAVLink ports (8000, 5761) are open:

```powershell
# Windows PowerShell (Run as Administrator)
netsh advfirewall firewall add rule name="GS_UDP" dir=in action=allow protocol=UDP localport=5000-5010
netsh advfirewall firewall add rule name="GS_WEB" dir=in action=allow protocol=TCP localport=8000
```

---

## Docker Deployment

```bash
# 1. Copy environment config
cp .env.example .env

# 2. Build and run container in background
docker compose up -d --build

# 3. View live container logs
docker compose logs -f

# 4. Stop container
docker compose down
```

---

## Troubleshooting

| Symptom | Resolution |
|---------|------------|
| **"NO SIGNAL" / Blank Video** | Verify the UDP sender script is running and targeting the exact IP and port. Check OS firewall rules for UDP traffic. |
| **MAVLink Disconnected** | Ensure the MAVLink TCP endpoint is reachable from the ground station. Check IP address and verify TCP port `5761` is open. |
| **YOLO Not Detecting** | Check terminal logs to ensure `ultralytics` is installed and `YOLO_ENABLED=true`. Verify target class names match COCO class labels in `YOLO_TARGET_CLASSES`. |
| **High CPU / Latency** | Reduce `VIDEO_FPS_LIMIT`, lower `VIDEO_JPEG_QUALITY`, or decrease `YOLO_MAX_FPS` in `.env`. |
| **Port Already in Use** | Modify `WEB_PORT` or `UDP_PORT` inside `.env` or pass as environment variables. |

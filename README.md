# UAV Ground Station

A web-based UAV Ground Station that receives live video over UDP, streams it
to the browser in real-time via WebSocket, and displays telemetry in a
dark military-style command-centre interface.

```
UAV (sender)
  └─ UDP JPEG stream
        └─ Ground Station (FastAPI)
              ├─ /ws/video      → browser canvas
              ├─ /ws/telemetry  → live telemetry panel
              └─ /ws/system     → log feed
```

---

## Architecture

```
ground_station/
├── app/
│   ├── main.py                      # FastAPI app + lifespan (service wiring)
│   ├── config/
│   │   └── settings.py              # Pydantic Settings (env vars)
│   ├── services/
│   │   ├── video/
│   │   │   ├── receiver.py          # UDP socket → decoded frame (thread)
│   │   │   └── manager.py           # frame → JPEG → WebSocket broadcast
│   │   ├── telemetry/
│   │   │   └── generator.py         # simulated telemetry (replace w/ MAVLink)
│   │   ├── mavlink/
│   │   │   └── interfaces.py        # abstract interfaces for future MAVLink
│   │   ├── yolo/
│   │   │   └── detector.py          # abstract interfaces for future YOLO
│   │   └── websocket/
│   │       └── manager.py           # multi-channel WebSocket hub
│   ├── routers/
│   │   ├── video.py                 # /ws/video + /api/video/*
│   │   ├── telemetry.py             # /ws/telemetry + /api/telemetry/*
│   │   └── system.py                # /ws/system + /api/system/*
│   ├── static/
│   │   ├── css/styles.css           # dark military theme
│   │   └── js/
│   │       ├── system.js            # WS client, log feed, clock
│   │       ├── telemetry.js         # WS client, DOM updates
│   │       └── video.js             # WS client, canvas renderer, HUD
│   └── templates/
│       └── index.html               # Jinja2 template (Tailwind + vanilla JS)
├── logs/                            # rotating log files (auto-created)
├── snapshots/                       # saved JPEG snapshots (auto-created)
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

---

## Video Packet Protocol

The backend is **fully compatible** with the existing UDP sender.

```
Packet structure:
  [0:4]  uint32 little-endian   — declared JPEG payload length
  [4:]   bytes                  — raw JPEG data

Python sender example:
  jpeg_bytes = cv2.imencode('.jpg', frame)[1].tobytes()
  packet     = struct.pack('<I', len(jpeg_bytes)) + jpeg_bytes
  sock.sendto(packet, (ground_station_ip, 5000))
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
# Edit .env as needed (UDP_PORT, WEB_PORT, etc.)

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

# Production (single worker — video is single-stream)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1

# Custom ports from .env
WEB_PORT=9000 UDP_PORT=6000 uvicorn app.main:app --host 0.0.0.0 --port 9000
```

---

## Opening the UI

Once the server is running, open in any modern browser:

```
http://localhost:8000
```

Or from another machine on the same LAN:

```
http://<server-ip>:8000
```

---

## Testing the Video Stream

You need a sender script on the UAV side (or locally for testing).

### Test sender (run on any machine with Python + OpenCV):

```python
import cv2, socket, struct, time

HOST = "127.0.0.1"   # ground station IP
PORT = 5000
QUALITY = 80

cap  = cv2.VideoCapture(0)          # 0 = webcam; or use a video file
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

while True:
    ret, frame = cap.read()
    if not ret:
        break
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
    if not ok:
        continue
    data   = buf.tobytes()
    packet = struct.pack("<I", len(data)) + data
    try:
        sock.sendto(packet, (HOST, PORT))
    except Exception as e:
        print(f"Send error: {e}")
    time.sleep(1 / 30)

cap.release()
sock.close()
```

### Test with an existing video file:

```python
cap = cv2.VideoCapture("path/to/video.mp4")
```

### Test with a static image (single frame loop):

```python
frame = cv2.imread("test.jpg")
```

---

## Tailscale Usage

Tailscale creates a private overlay network so the UAV and ground station
can communicate securely over the internet without port forwarding.

### Setup

```bash
# 1. Install Tailscale on both the UAV companion computer and the ground station
#    https://tailscale.com/download

# 2. Authenticate both devices to the same Tailscale account
tailscale up

# 3. Find the Tailscale IP of the ground station
tailscale ip -4

# 4. Set the environment variable on the ground station
TAILSCALE_ENABLED=true

# 5. The UAV sender targets the Tailscale IP of the ground station
HOST = "100.x.x.x"  # Tailscale IP
```

### Firewall

Ensure UDP port 5000 and TCP port 8000 are open in the OS firewall:

```bash
# Linux (ufw)
sudo ufw allow 5000/udp
sudo ufw allow 8000/tcp

# Windows (PowerShell — run as Administrator)
netsh advfirewall firewall add rule name="GS_UDP" dir=in action=allow protocol=UDP localport=5000
netsh advfirewall firewall add rule name="GS_WEB" dir=in action=allow protocol=TCP localport=8000
```

---

## Docker

```bash
# Build and run
cp .env.example .env
docker compose up --build

# Run in background
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

---

## WebSocket API

| Endpoint        | Type   | Description                          |
|-----------------|--------|--------------------------------------|
| `/ws/video`     | binary | Raw JPEG frames at up to 30 FPS      |
| `/ws/telemetry` | text   | JSON telemetry packets at 5 Hz       |
| `/ws/system`    | text   | JSON system events / log messages    |

### REST Endpoints

| Endpoint              | Method | Description                    |
|-----------------------|--------|--------------------------------|
| `/`                   | GET    | Ground Station UI              |
| `/health`             | GET    | Server health + video stats    |
| `/api/video/status`   | GET    | Video receiver statistics      |
| `/api/telemetry/latest` | GET  | Latest telemetry snapshot      |
| `/api/system/events`  | GET    | Last 100 system events         |
| `/api/system/info`    | GET    | Server info                    |

### Telemetry Packet Schema

```json
{
  "timestamp":           1718000000.0,
  "uptime_s":            42.5,
  "vehicle_id":          1,
  "vehicle_name":        "UAV-01",
  "lat":                 -7.7956000,
  "lon":                 110.3695000,
  "altitude_m":          50.0,
  "relative_alt_m":      50.0,
  "ground_speed_ms":     8.5,
  "air_speed_ms":        9.0,
  "heading_deg":         270.0,
  "climb_rate_ms":       0.2,
  "roll_deg":            1.2,
  "pitch_deg":           -0.8,
  "yaw_deg":             270.0,
  "battery_voltage":     15.8,
  "battery_current":     14.2,
  "battery_remaining_pct": 82,
  "rssi":                -68,
  "link_quality_pct":    95,
  "flight_mode":         "AUTO",
  "armed":               true,
  "mission_state":       "WAYPOINT",
  "current_waypoint":    2,
  "total_waypoints":     5,
  "distance_to_wp_m":    38.4,
  "gps_fix":             3,
  "satellites_visible":  12,
  "hdop":                0.9,
  "ekf_ok":              true,
  "pre_arm_check":       true
}
```

---

## Future Expansion

### Adding Real MAVLink Telemetry

1. Uncomment `pymavlink` in `requirements.txt` and install it.
2. Implement `MAVLinkConnection` and `MAVLinkTelemetryBridge` from
   `app/services/mavlink/interfaces.py`.
3. In `app/main.py`, replace `TelemetryGenerator` with your concrete
   `MAVLinkTelemetryBridge` subclass.

### Adding YOLO Detection

1. Uncomment `ultralytics` in `requirements.txt` and install it.
2. Implement `BaseDetector` from `app/services/yolo/detector.py`
   (the example stub is included in comments).
3. Start the detector pipeline as an asyncio Task in `main.py`.
4. Push `DetectionFrame` JSON over `/ws/video` or a new `/ws/detection`
   channel; call `window.GS_setDetections()` from the frontend.

### Adding Multiple UAVs

- `VideoManager` is a single-UAV service; add a `vehicle_id` namespace
  to the WebSocket paths: `/ws/video/{vehicle_id}`.
- `TelemetryGenerator` generates data for one vehicle; instantiate one
  per vehicle and broadcast on separate sub-channels.
- Left sidebar vehicle list already renders multiple cards once the
  `vehicle_id` field in telemetry is used.

### Swarm Operations

- Add `/ws/swarm` channel with aggregated multi-vehicle telemetry.
- Create `services/swarm/coordinator.py` that subscribes to all
  vehicle telemetry streams and re-publishes a merged view.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| **"No Signal" displayed** | Ensure the UDP sender is running and targeting the correct IP/port. Check firewall rules for UDP 5000. |
| **Port already in use** | Change `UDP_PORT` or `WEB_PORT` in `.env`. |
| **ModuleNotFoundError** | Activate the virtual environment and re-run `pip install -r requirements.txt`. |
| **Very high CPU** | Lower `VIDEO_FPS_LIMIT` and/or `VIDEO_JPEG_QUALITY` in `.env`. |
| **Browser shows blank canvas** | Check browser console for WebSocket errors. Verify the server is reachable on the configured port. |
| **Docker UDP not receiving** | Confirm the port mapping is `5000:5000/udp` (not TCP) in `docker-compose.yml`. |
| **Windows firewall blocking** | Add inbound rules for UDP 5000 and TCP 8000 (see Tailscale section above). |

---

## Configuration Reference

All options are read from environment variables or `.env`:

| Variable              | Default     | Description                                   |
|-----------------------|-------------|-----------------------------------------------|
| `HOST`                | `0.0.0.0`   | Web server bind host                          |
| `WEB_PORT`            | `8000`      | HTTP / WebSocket port                         |
| `UDP_PORT`            | `5000`      | UDP video receive port                        |
| `VIDEO_FPS_LIMIT`     | `30`        | Max FPS forwarded to browsers                 |
| `VIDEO_JPEG_QUALITY`  | `80`        | Re-encode JPEG quality (1–100)                |
| `VIDEO_MAX_CLIENTS`   | `10`        | Max simultaneous video WebSocket clients      |
| `TAILSCALE_ENABLED`   | `false`     | Enable Tailscale-specific logging             |
| `LOG_LEVEL`           | `INFO`      | Python logging level                          |
| `TELEMETRY_HZ`        | `5.0`       | Simulated telemetry rate in Hz                |
| `SNAPSHOT_DIR`        | `snapshots` | Directory for server-side snapshots           |

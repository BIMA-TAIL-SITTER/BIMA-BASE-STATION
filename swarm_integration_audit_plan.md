# 🔍 Swarm Live Stitching — Audit & Integration Plan ke Base Station Baru

> **Tujuan**: Panduan audit dan integrasi `live_stitching_service` dari GCS-Backup ke base station swarm baru
> **Status**: PLANNED — menunggu repo base station baru tersedia di local
> **Konteks**: Base station baru sudah memiliki topologi port tersendiri (video stream + MAVLink telemetry). Port untuk stitching perlu disesuaikan agar tidak tabrakan.
> **Last Updated**: July 2026

---

## Table of Contents

1. [Istilah & Klarifikasi](#1-istilah--klarifikasi)
2. [Port Topology yang Sudah Diketahui (GCS-Backup)](#2-port-topology-yang-sudah-diketahui-gcs-backup)
3. [Checklist Audit Base Station Baru](#3-checklist-audit-base-station-baru)
4. [Komponen yang Akan Diintegrasikan](#4-komponen-yang-akan-diintegrasikan)
5. [Port Allocation Strategy](#5-port-allocation-strategy)
6. [Integration Plan — Step by Step](#6-integration-plan--step-by-step)
7. [File yang Perlu Diedit Setelah Audit](#7-file-yang-perlu-diedit-setelah-audit)
8. [Risiko & Mitigasi](#8-risiko--mitigasi)

---

## 1. Istilah & Klarifikasi

Sebelum mulai, beberapa klarifikasi istilah yang perlu disepakati:

### "Payload Detection" / Video Stream Trigger

Yang dimaksud rekan kerja dengan **"video stream untuk deteksi payload sebagai trigger misi swarm"** kemungkinan adalah salah satu dari:

| Istilah yang tepat | Penjelasan |
|---|---|
| **Object Detection Stream** | Video stream dari kamera yang diproses model ML (YOLO, dll) untuk mendeteksi objek/target di lapangan |
| **Payload Drop Detection** | Kamera yang memantau apakah payload (muatan) sudah dijatuhkan/di-deploy |
| **Target Acquisition Stream** | Stream video untuk mengunci/mengidentifikasi target sebelum swarm misi dimulai |

> [!IMPORTANT]
> **Perlu dikonfirmasi ke rekan kerja**: Apakah video stream ini diproses di GCS (ground) atau di drone (edge)? Ini menentukan apakah port yang digunakan adalah TCP socket (seperti stitching) atau WebRTC/RTSP.

### "Multi UAV Image Stitching" dalam konteks ini

Ini adalah pipeline yang sudah dibangun di GCS-Backup:
- `receiver_socket.py` → terima gambar via TCP dari drone
- `live_stitching_service.py` → stitch gambar menjadi orthomosaic
- Hasilnya ditampilkan di frontend GCS

---

## 2. Port Topology yang Sudah Diketahui (GCS-Backup)

Berikut semua port yang digunakan di repo GCS-Backup saat ini — ini adalah baseline sebelum melihat base station baru:

### HTTP/WebSocket Services (Software Ports)

| Port | Service | File | Protokol | Keterangan |
|---|---|---|---|---|
| **9002** | FastAPI Backend | `GCS-Backend-Backup/run.py`, `config.py` | HTTP + WebSocket | Main backend API |
| **9003** | PyMavlink Flask API | `GCS-PyMavlink-Backup/src/main.py` | HTTP | Telemetry health endpoint |
| **6379** | Redis | `app/redis_handler.py` | TCP | In-memory cache untuk telemetry |
| **5173** | Vite Dev Server | Frontend | HTTP | React frontend |

### TCP Socket Services (Custom Protocol — untuk stitching)

| Port | Service | File | Protokol | Keterangan |
|---|---|---|---|---|
| **5001** | Image receiver UAV-1 | `receiver_socket.py`, `UAV_CONFIG` | Raw TCP | Terima JPEG dari drone 1 |
| **5002** | Image receiver UAV-2 | `receiver_socket.py`, `UAV_CONFIG` | Raw TCP | Terima JPEG dari drone 2 |
| **5003** | Image receiver UAV-3 | `receiver_socket.py` (commented) | Raw TCP | Reserved, belum aktif |

### MAVLink / Serial Ports (Hardware Level)

| "Port" | Service | File | Protokol | Keterangan |
|---|---|---|---|---|
| **14550** | MAVLink SITL UDP | `GCS-PyMavlink-Backup/src/config.py` | UDP | Simulasi SITL ArduPilot |
| **/dev/ttyUSB0** | Serial FC | `GCS-PyMavlink-Backup/src/config.py` | Serial 57600 baud | Hardware flight controller |

### WebSocket Endpoints (dalam FastAPI port 9002)

| Path | Service | Keterangan |
|---|---|---|
| `ws://host:9002/ws` | Telemetry WebSocket | Push telemetry ke frontend |
| `ws://host:9002/ws/mapping-images` | Image WebSocket | Stream gambar mapping (sistem lama) |
| `ws://host:9002/api/stitching/ws/{session_id}` | Stitching progress WS | Live update per drone (sistem baru) |

---

## 3. Checklist Audit Base Station Baru

Saat repo base station baru sudah tersedia, lakukan audit berikut **sebelum** melakukan integrasi apapun.

### 3.1 Port Audit — Yang Harus Dicari

Jalankan grep berikut di root folder base station baru untuk inventarisasi port:

```bash
# Cari semua angka yang kemungkinan adalah port (4-5 digit)
grep -rn --include="*.py" --include="*.sh" --include="*.js" --include="*.env" \
  -E ":[0-9]{4,5}|port[[:space:]]*=[[:space:]]*[0-9]{4,5}|PORT[[:space:]]*=[[:space:]]*[0-9]{4,5}" \
  ./

# Cari khusus video stream (RTSP, WebRTC, GStreamer)
grep -rn --include="*.py" -iE "rtsp|webrtc|gstreamer|ffmpeg|mjpeg|port.*video|video.*port" ./

# Cari khusus MAVLink port
grep -rn --include="*.py" -iE "14550|14551|14552|mavlink.*port|udp.*mavlink" ./

# Cari launch script untuk melihat semua service yang dijalankan
find . -name "*.sh" | xargs grep -l "port\|PORT" 2>/dev/null
```

### 3.2 Pertanyaan yang Harus Dijawab dari Audit

Isi tabel ini setelah audit selesai:

| Pertanyaan | Jawaban (diisi saat audit) |
|---|---|
| Port berapa yang dipakai backend utama? | `___` |
| Port berapa yang dipakai video stream (RTSP/WebRTC)? | `___` |
| Port berapa yang dipakai MAVLink telemetry? | `___` |
| Apakah ada port 5001/5002 yang sudah dipakai? | `___` |
| Apakah ada Redis di sistem baru? | `___` |
| Apakah frontend sudah ada komponen mapping/stitching? | `___` |
| Framework frontend-nya apa? (React/Vue/dll) | `___` |
| Apakah sudah ada FastAPI? Versi berapa? | `___` |
| Apakah ada sistem manajemen proses (systemd/supervisor)? | `___` |

### 3.3 Checklist File Kunci yang Dicari

```
□ Launch script (*.sh) → lihat semua proses yang dijalankan + portnya
□ Backend main entry point (main.py / app.py) → port HTTP server
□ Config/env file (.env / config.py / settings.py) → port definitions
□ Video stream script → port RTSP/WebRTC/TCP untuk video
□ MAVLink script → port UDP/serial untuk telemetry
□ Frontend config (vite.config.js / webpack.config.js) → dev server port
□ Docker Compose (docker-compose.yml) → jika containerized, lihat port mappings
□ README → dokumentasi port yang sudah ada
```

---

## 4. Komponen yang Akan Diintegrasikan

Berikut yang dibawa dari GCS-Backup ke base station baru:

### Komponen Wajib (Core Stitching Pipeline)

| File Asal | Fungsi | Catatan |
|---|---|---|
| `service/live_stitching_service.py` | FastAPI router — orchestrator stitching | Perlu di-mount ke backend baru |
| `service/stitch_main/Combiner.py` | Core stitching engine | Tidak ada port — pure computation |
| `service/stitch_main/blending.py` | ROI feather blending | Tidak ada port — pure computation |
| `service/stitch_main/geometry.py` | IMU unrotation + canvas | Tidak ada port — pure computation |
| `service/stitch_main/utilities.py` | Image loading + GPS | Tidak ada port — pure computation |
| `service/stitch_main/redundant_filter.py` | Frame deduplication | Tidak ada port — pure computation |
| `receiver_socket.py` | TCP receiver gambar dari drone | **Port perlu disesuaikan** |

### Komponen Opsional (tergantung arsitektur base station baru)

| File Asal | Fungsi | Keputusan |
|---|---|---|
| `service/mappings_service.py` | CRUD mapping missions | Mungkin sudah ada di base station baru |
| `service/image_websocket.py` | WebSocket stream gambar (sistem lama) | **Kemungkinan tidak dipakai** — arsitektur baru pakai `live_stitching_service` |
| `sender_socket_sim.py` | Simulator sender drone | Dipakai untuk testing, tidak diintegrasikan ke base station |
| `sender_socket_raspi.py` | Sender di Raspberry Pi | Jalan di drone, bukan di base station |

### Komponen yang TIDAK Diintegrasikan

| File Asal | Alasan |
|---|---|
| `GCS-PyMavlink-Backup/` | Base station baru sudah punya MAVLink sendiri |
| `GCS-Frontend-Backup/` | Base station baru sudah punya frontend sendiri |
| `app/redis_handler.py` | Bergantung pada arsitektur cache base station baru |

---

## 5. Port Allocation Strategy

### Prinsip Utama

> [!IMPORTANT]
> **Pisahkan port berdasarkan jenis traffic:**
> - **HTTP/WebSocket API** → satu port untuk backend FastAPI
> - **Video Stream** → port terpisah, jangan campur dengan stitching TCP
> - **MAVLink UDP** → port standar industri (14550/14551), jangan diganggu
> - **Stitching TCP** → port tersendiri di range yang tidak bertabrakan

### Recommended Port Allocation (Sebelum Audit)

Ini adalah *proposal awal* yang perlu diverifikasi setelah audit base station baru:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SWARM BASE STATION PORT MAP                       │
├────────────────────┬──────────────┬──────────────────────────────────┤
│ Service            │ Port         │ Protokol                         │
├────────────────────┼──────────────┼──────────────────────────────────┤
│ MAVLink SITL (sim) │ 14550        │ UDP — JANGAN DIUBAH              │
│ MAVLink Real       │ /dev/ttyUSB* │ Serial — hardware                │
│                    │              │                                  │
│ Video Stream UAV-1 │ ???? (audit) │ RTSP/WebRTC/TCP — cek base stn  │
│ Video Stream UAV-2 │ ???? (audit) │ RTSP/WebRTC/TCP — cek base stn  │
│                    │              │                                  │
│ Backend API        │ ???? (audit) │ HTTP + WebSocket — cek base stn │
│ Frontend Dev       │ ???? (audit) │ HTTP Vite — cek base stn        │
│                    │              │                                  │
│ [PROPOSED] Redis   │ 6379         │ TCP — jika base stn punya Redis │
│ [PROPOSED] Stitch  │ 6001         │ TCP raw — receiver_socket.py     │
│   receiver UAV-1   │              │ (BUKAN 5001 — hindari konflik)  │
│ [PROPOSED] Stitch  │ 6002         │ TCP raw — receiver_socket.py     │
│   receiver UAV-2   │              │ (BUKAN 5002 — hindari konflik)  │
│ [PROPOSED] Stitch  │ 6000         │ TCP raw — single-port mode       │
│   negotiation port │              │ (jika pakai hello packet design) │
└────────────────────┴──────────────┴──────────────────────────────────┘
```

> [!NOTE]
> Range `6000–6099` dipilih sebagai proposal awal karena:
> - Tidak digunakan oleh RTSP (554), WebRTC (3478), MAVLink (14550+)
> - Tidak bertabrakan dengan port web umum (80, 443, 3000, 5173, 8080, 9000)
> - Masih dalam range unprivileged ports (1024–65535)
> - Mudah diingat dan konsisten dengan tema "enam ribu untuk stitching"

**Finalisasi port ini harus dilakukan SETELAH audit base station baru.**

---

## 6. Integration Plan — Step by Step

### Phase 1: Audit (Lakukan saat repo base station sudah tersedia)

```
□ Step 1.1 — Clone / copy repo base station baru ke local
□ Step 1.2 — Jalankan grep audit (lihat Section 3.1)
□ Step 1.3 — Isi tabel pertanyaan di Section 3.2
□ Step 1.4 — Gambar diagram topologi port base station baru
□ Step 1.5 — Tentukan port final untuk stitching (update Section 5)
□ Step 1.6 — Konfirmasi ke rekan kerja: apakah video stream pakai port TCP atau protokol lain?
```

### Phase 2: Backend Integration

```
□ Step 2.1 — Copy folder stitch_main/ ke direktori service base station baru
□ Step 2.2 — Copy live_stitching_service.py ke service/ base station baru
□ Step 2.3 — Mount live_stitching_service router ke main FastAPI app:
             app.include_router(live_stitching_router, prefix="/api", tags=["live-stitching"])
□ Step 2.4 — Pastikan dependencies terpasang (watchdog, opencv-python, numpy)
□ Step 2.5 — Update mapping_result/ path jika struktur folder base station baru berbeda
□ Step 2.6 — Test endpoint: GET /api/stitching/ → harus return service info
```

### Phase 3: Port Adjustment (receiver_socket.py)

```
□ Step 3.1 — Update UAV_CONFIG dengan port baru hasil audit:
             UAV_CONFIG = {
                 "uav1": {"port": 6001, "session_id": "uav_1"},  # ganti dari 5001
                 "uav2": {"port": 6002, "session_id": "uav_2"},  # ganti dari 5002
             }
             ATAU implementasi Single Port + Header (port 6000) sesuai
             dynamic_uav_negotiation_plan.md

□ Step 3.2 — Update sender_socket_raspi.py di drone dengan port baru
□ Step 3.3 — Update sender_socket_sim.py default port untuk testing
□ Step 3.4 — Verifikasi tidak ada firewall/iptables yang block port baru
```

### Phase 4: Frontend Integration

```
□ Step 4.1 — Audit komponen frontend base station baru:
             Apakah sudah ada mapping/stitching UI?
             Framework apa yang dipakai?

□ Step 4.2 — Jika belum ada: port komponen dari GCS-Frontend-Backup:
             - MappingResultModal.jsx (atau buat ulang sesuai framework base station)
             - MappingsList.jsx
             - Hooks untuk WebSocket ke /api/stitching/ws/{session_id}

□ Step 4.3 — Implementasi swarmSlice.js (Redux) sesuai multi_uav_display_plan.md
             jika base station baru pakai Redux

□ Step 4.4 — Update API base URL di frontend agar mengarah ke backend baru
```

### Phase 5: End-to-End Testing

```
□ Step 5.1 — Jalankan base station baru (semua service)
□ Step 5.2 — Jalankan receiver_socket.py (dengan port baru)
□ Step 5.3 — Buat mapping baru dari frontend
□ Step 5.4 — Jalankan sender_socket_sim.py (dua instance untuk simulasi 2 UAV)
             python3 sender_socket_sim.py --dataset-dir ./uav1 --port 6001
             python3 sender_socket_sim.py --dataset-dir ./uav2 --port 6002
□ Step 5.5 — Verifikasi images masuk ke mapping_result/{id}/{session}/images/
□ Step 5.6 — Trigger manual stitching via API: POST /api/stitching/session/{id}/stitch
□ Step 5.7 — Verifikasi hasil stitching muncul di frontend
□ Step 5.8 — Test video stream + stitching berjalan bersamaan (tidak ada port conflict)
□ Step 5.9 — Test MAVLink telemetry + stitching berjalan bersamaan
```

---

## 7. File yang Perlu Diedit Setelah Audit

Tabel ini diisi setelah audit base station baru selesai:

### Di GCS-Backup (files yang dibawa)

| File | Baris yang Perlu Diedit | Nilai Lama | Nilai Baru |
|---|---|---|---|
| `receiver_socket.py` | `UAV_CONFIG` port values | `5001`, `5002` | `????` (hasil audit) |
| `receiver_socket.py` | `get_latest_mapping_id()` URL | `http://127.0.0.1:9002` | URL backend baru |
| `sender_socket_sim.py` | `--port` default | `5001` | port baru |
| `sender_socket_raspi.py` | `SERVER_PORT` | `5001` | port baru |

### Di Base Station Baru (files yang perlu ditambah/diedit)

| File | Aksi | Deskripsi |
|---|---|---|
| `app/main.py` | **EDIT** | Mount `live_stitching_router` |
| `requirements.txt` | **EDIT** | Tambah: `watchdog`, `opencv-python`, `numpy` |
| `service/live_stitching_service.py` | **ADD** | Copy dari GCS-Backup |
| `service/stitch_main/` | **ADD** | Copy seluruh folder dari GCS-Backup |
| Frontend mapping component | **ADD/EDIT** | Tergantung hasil audit frontend |

---

## 8. Risiko & Mitigasi

| Risiko | Kemungkinan | Dampak | Mitigasi |
|---|---|---|---|
| Port video stream bertabrakan dengan TCP stitching | Sedang | Tinggi | Audit terlebih dahulu, gunakan range 6000+ |
| `live_stitching_service` bergantung path relatif (`./mapping_result/`) | Tinggi | Sedang | Buat path configurable via env variable |
| Base station baru tidak pakai Redis | Sedang | Sedang | Pastikan backend baru tetap bisa serve telemetry tanpa Redis, stitching tidak bergantung Redis |
| Framework frontend berbeda (bukan React/Redux) | Sedang | Tinggi | Mungkin perlu buat ulang komponen stitching UI dari scratch |
| Dependencies Python berbeda versi | Sedang | Sedang | Uji di virtual environment baru sebelum merge |
| Watchdog tidak trigger di mount point berbeda | Rendah | Tinggi | Test Watchdog secara terpisah sebelum full integration |
| Video stream adalah RTSP — tidak pakai TCP socket | Tinggi | Rendah | Tidak ada konflik jika RTSP (port 554 atau range 8554) — konfirmasi ke rekan kerja |

> [!CAUTION]
> **Jangan merge ke base station baru sebelum audit selesai.** Port conflict antara video stream dan stitching receiver bisa menyebabkan keduanya gagal bind dan sistem tidak bisa digunakan sama sekali.

---

## Appendix: Pertanyaan untuk Rekan Kerja

Sebelum atau saat audit, konfirmasi hal-hal berikut:

1. **Video stream protocol**: Apakah video dari drone ke base station menggunakan RTSP, WebRTC, GStreamer pipeline, atau raw TCP socket seperti stitching?
2. **Port yang sudah fix**: Port mana saja yang sudah di-hardcode dan tidak boleh diubah?
3. **Arsitektur backend**: Apakah base station baru pakai FastAPI? Kalau iya, versi berapa dan sudah ada service apa saja?
4. **Swarm trigger logic**: Payload detection yang dimaksud — apakah outputnya berupa sinyal/event yang dikirim ke backend, atau langsung trigger MAVLink command?
5. **Jumlah UAV maksimal**: Berapa drone maksimal yang akan beroperasi dalam satu swarm mission? Ini menentukan berapa port range yang perlu disiapkan untuk stitching.

---

*Plan ini bersifat template — bagian yang perlu diisi (ditandai `????`) harus dilengkapi setelah audit repo base station baru selesai.*
*Referensi: GCS-Backup repo, dynamic_uav_negotiation_plan.md, multi_uav_display_plan.md, network_architecture_comparison.md*
*Last updated: July 2026*

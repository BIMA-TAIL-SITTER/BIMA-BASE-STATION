# BIMA SWARM UGM - Ground Control Station (GCS)

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Build](https://img.shields.io/badge/build-passing-brightgreen.svg)

BIMA SWARM UGM Ground Control Station (GCS) adalah sebuah *Command Centre* modern dengan arsitektur *Split-Stack* untuk mengendalikan sistem *Multi-UAV*. Proyek ini menggabungkan *backend* **FastAPI** berkecepatan tinggi untuk streaming video UDP, penerimaan telemetri dan deteksi secara *Edge AI*, *bridge* telemetri MAVLink Dual-Slot, dan pemetaan GIS luring (offline) dengan antarmuka **Next.js 15 & React 19** yang interaktif secara *real-time*.

## Table of Contents
- [Fitur Utama](#fitur-utama)
- [Demo / Screenshot](#demo--screenshot)
- [Prasyarat](#prasyarat)
- [Instalasi](#instalasi)
- [Cara Penggunaan](#cara-penggunaan)
- [Konfigurasi](#konfigurasi)
- [Struktur Folder](#struktur-folder)
- [Protokol Video & Telemetri](#protokol-video--telemetri)
- [Kontribusi](#kontribusi)
- [Testing](#testing)
- [Roadmap](#roadmap)
- [Lisensi](#lisensi)
- [Kontak](#kontak)

## Fitur Utama
- **Arsitektur Split-Stack Terpisah:** Backend FastAPI untuk pemrosesan *network I/O* dan MAVLink dipisahkan secara murni dari dashboard Next.js modern berbasis *React*.
- **Rendering HUD Canvas Performa Tinggi:** Pemutaran *multi-stream video* (UDP JPEG) dan visualisasi target hasil deteksi *Edge AI* langsung digambar di lapisan `<canvas>` HTML5 demi mencapai *Frame per Second* (FPS) tinggi tanpa hambatan render DOM.
- **Instrumen Penerbangan MAVLink Dual-Slot:** Telemetri langsung dari *autopilot* (seperti ArduPilot/PX4) dengan instrumen *Primary Flight Display* (PFD) interaktif (*Attitude Indicator*, dll).
- **Pemetaan Satelit GIS Luring:** *Server* peta luring internal menggunakan *database* SQLite (MBTiles) yang dapat mengunduh secara otomatis (*auto-cache fallback*) menggunakan satelit Esri.
- **Kesiapan Modul AI Decision:** Basis kode telah disiapkan untuk menyambut sistem *AI Decision Layer* (otonomi multi-UAV) memanfaatkan sistem deteksi objek pada komputasi *edge* masing-masing wahana.

## Demo / Screenshot
*(Tambahkan gambar atau tautan demo proyek di sini)*
![Dashboard Screenshot Placeholder](https://via.placeholder.com/800x400?text=BIMA+GCS+Dashboard+Screenshot)

## Prasyarat
Sebelum menginstal proyek ini, pastikan sistem Anda telah memiliki:
- **Python** (versi 3.10 atau lebih baru) untuk server API *backend*.
- **Node.js** (versi 18 atau lebih baru) dan `npm` / `pnpm` untuk *frontend dashboard*.

## Instalasi

Proyek ini direkomendasikan berjalan pada lingkungan terpisah (*split-stack*).

### 1. Mengatur Backend (FastAPI)
```bash
# Clone repositori dan masuk ke dalam folder proyek
git clone https://github.com/BIMA-TAIL-SITTER/BIMA-BASE-STATION.git
cd BIMA-BASE-STATION

# Buat dan aktifkan virtual environment
python -m venv venv
# Windows: .\venv\Scripts\Activate.ps1
# Linux/Mac: source venv/bin/activate

# Instal semua pustaka Python yang dibutuhkan
pip install -r requirements.txt

# Salin konfigurasi environment default
cp .env.example .env
```

### 2. Mengatur Frontend (Next.js)
```bash
# Buka terminal baru dan masuk ke folder frontend
cd BIMA-BASE-STATION/gcs_js

# Instal pustaka Node.js
npm install
```

## Cara Penggunaan

### Menjalankan via Terminal Terpisah (Rekomendasi)

**Terminal 1 (Backend FastAPI):**
```bash
# Pastikan berada di root direktori BIMA-BASE-STATION dan venv telah aktif
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*Tunggu hingga server muncul pesan:* `Ground Station ready — open http://0.0.0.0:8000`

**Terminal 2 (Frontend Next.js):**
```bash
# Pastikan berada di dalam folder gcs_js
npm run dev
```
*Buka peramban (browser) dan akses:* `http://localhost:3000`

### Menjalankan via Docker Compose
Jika lebih menyukai *deployment* berbasis *container*:
```bash
cp .env.example .env
docker compose up -d --build
docker compose logs -f
```

## Konfigurasi

Ubah atau tambahkan variabel lingkungan (*environment variables*) pada berkas `.env` sesuai kebutuhan operasional:

| Variabel | Bawaan | Deskripsi |
| :--- | :--- | :--- |
| `HOST` | `0.0.0.0` | IP *Bind* untuk backend FastAPI |
| `WEB_PORT` | `8000` | Port server FastAPI & WebSocket |
| `UDP_PORT` | `5000` | Port UDP dasar untuk stream video UAV 1 |
| `TAILSCALE_ENABLED` | `false` | Pengaktifan jaringan SD-WAN Tailscale MagicDNS |
| `TELEMETRY_HZ` | `5.0` | Kecepatan broadcast MAVLink via WebSocket dalam Hz |
| `MAVLINK_HOSTS` | `100.x.x.x` | Alamat IP host TCP MAVLink (pisahkan dengan koma) |

*Untuk dukungan Tailscale (jaringan terdistribusi aman jarak jauh), aktifkan `TAILSCALE_ENABLED=true`.*

## Struktur Folder

```text
BIMA-BASE-STATION/
├── app/                             # Mesin API Backend FastAPI (Port 8000)
│   ├── config/                      # Pengaturan environment (Pydantic)
│   ├── routers/                     # Endpoint API REST & WebSocket (/ws/video, dll)
│   └── services/                    # Thread worker (MAVLink bridge, video receiver)
├── gcs_js/                          # Frontend Command Centre Next.js (Port 3000)
│   ├── src/app/                     # Layout, halaman utama dashboard
│   └── src/components/              # Komponen visual (Peta GIS, HUD Canvas, Telemetri)
├── data/                            # Database SQLite peta offline (MBTiles)
├── logs/                            # Berkas penyimpanan log
├── requirements.txt                 # Dependensi Python backend
└── docker-compose.yml               # Konfigurasi containerized deployment
```

## Protokol Video & Telemetri
* Fitur streaming video menangkap paket JPEG via UDP dari klien eksternal ke host `127.0.0.1` pada port spesifik.
* Hasil deteksi dari *Edge AI* diterima dalam bentuk JSON via protokol WebSocket UDP dan akan di-*render* (berupa *bounding box* target) secara sinkron dengan *frame* video melalui `Canvas HUD` di *frontend*.

## Kontribusi
Kami menyambut baik semua bentuk dukungan terhadap proyek ini! Cara berkontribusi:
1. Lakukan _Fork_ pada repositori ini.
2. Buat *branch* fitur Anda (`git checkout -b feature/FiturKeren`).
3. Terapkan kode (*Commit*) (`git commit -m 'Menambahkan FiturKeren'`).
4. Unggah ke *branch* Anda (`git push origin feature/FiturKeren`).
5. Buat *Pull Request* baru ke *branch* utama kami.

## Testing
Saat ini proyek memuat konfigurasi dasar di dalam modul `tests/` yang menyertakan kerangka Python *pytest*.
```bash
pytest tests/
```

## Roadmap
- [ ] Stabilisasi *AI Decision Layer* (Targeting dan Otonomi Multi-UAV).
- [ ] Penggabungan kontrol misi yang lebih ketat dengan sinkronisasi `MAVLinkCommandSender`.
- [ ] Kompresi stream *Video/HUD* via WebRTC untuk skenario koneksi minim.
- [ ] Integrasi otentikasi operator terpusat.

## Lisensi
Didistribusikan di bawah lisensi MIT. Silakan periksa file `LICENSE` untuk rincian selengkapnya.

## Kontak
**Tim Pengembang BIMA UGM**
- [GitHub Repositori Utama](https://github.com/BIMA-TAIL-SITTER/BIMA-BASE-STATION)
- Laporan isu dan pertanyaan: silakan hubungi kami via menu **Issues** GitHub.

# LLM Execution Brief: Migrasi & Regenerasi Arsitektur GCS ke Next.js (Split-Stack Architecture)

Dokumen ini adalah **Prompt / System Instruction Lengkap** yang dirancang khusus untuk dijalankan oleh **LLM / AI Agentic Coder** guna menginisialisasi proyek **Next.js (App Router + TypeScript + Tailwind CSS)** dan merestrukturisasi arsitektur *Ground Control Station* (GCS) dari monolithic vanilla HTML/JS menjadi **Decoupled Split-Stack Architecture (FastAPI Backend + Next.js Frontend)** tanpa kesalahan (*error-free*).

---

## 1. Tujuan Utama & Kondisi Eksisting

### 1.1 Kondisi Eksisting
- **Backend Eksisting**: Aplikasi FastAPI ([app/main.py](file:///c:/Users/M%20S%20I/Documents/BIMA/ground_station/ground_station/app/main.py)) yang menyajikan REST API, WebSocket (*telemetry, video stream, system logs*), serta merender template statis Jinja2 ([app/templates/index.html](file:///c:/Users/M%20S%20I/Documents/BIMA/ground_station/ground_station/app/templates/index.html)).
- **Frontend Eksisting**: File HTML monolitik (`index.html`) > 850 baris yang dikontrol oleh Vanilla JS ([app/static/js/telemetry.js](file:///c:/Users/M%20S%20I/Documents/BIMA/ground_station/ground_station/app/static/js/telemetry.js), [app/static/js/video.js](file:///c:/Users/M%20S%20I/Documents/BIMA/ground_station/ground_station/app/static/js/video.js), [app/static/js/camera.js](file:///c:/Users/M%20S%20I/Documents/BIMA/ground_station/ground_station/app/static/js/camera.js), [app/static/js/system.js](file:///c:/Users/M%20S%20I/Documents/BIMA/ground_station/ground_station/app/static/js/system.js)) menggunakan manipulasi DOM langsung (`document.getElementById`).

### 1.2 Target Arsitektur Baru (Split-Stack)
1. **Backend Server (FastAPI - Port `8000`)**:
   - Bertindak murni sebagai **API & Real-time WebSocket Engine**.
   - Dilengkapi **CORS Middleware** yang mengizinkan request dari frontend Next.js (`http://localhost:3000` atau IP lokal jaringan).
2. **Frontend UI Server (Next.js 14+ App Router - Port `3000`)**:
   - Bertindak sebagai **Modern Real-Time GCS Dashboard**.
   - Modular, reaktif, dan dioptimalkan untuk pengiriman data frekuensi tinggi (10-30 FPS telemetry & video frame).

---

## 2. Instruksi Langkah demi Langkah untuk LLM

> [!IMPORTANT]
> **Kepada LLM yang memproses dokumen ini:** Ikuti tahapan di bawah secara berurutan. Jangan mengubah struktur logika penerimaan data UDP/MAVLink di backend Python. Fokus pada pemisahan layer presentasi dan pengamanan komunikasi data.

---

### TAHAP 1: Konfigurasi CORS & REST Endpoint di FastAPI Backend

1. Buka file [app/main.py](file:///c:/Users/M%20S%20I/Documents/BIMA/ground_station/ground_station/app/main.py).
2. Pastikan konfigurasi `CORSMiddleware` mengizinkan origin frontend:
   ```python
   app.add_middleware(
       CORSMiddleware,
       allow_origins=["*"],  # Atau secara spesifik ["http://localhost:3000"]
       allow_credentials=True,
       allow_methods=["*"],
       allow_headers=["*"],
   )
   ```
3. Tambahkan endpoint `/api/config` agar Next.js dapat mengambil informasi host server, Tailscale IP, dan status YOLO secara dinamis tanpa bergantung pada variabel Jinja2 template:
   ```python
   @app.get("/api/config", tags=["system"])
   async def get_config(request: Request):
       return {
           "ws_host": request.headers.get("host", f"{settings.HOST}:{settings.WEB_PORT}"),
           "tailscale_ip": get_tailscale_ip(),
           "yolo_enabled": settings.YOLO_ENABLED,
       }
   ```

---

### TAHAP 2: Inisialisasi Proyek Next.js (`gcs-client`)

1. Buat direktori baru bernama `gcs-client` di root workspace atau jalankan perintah non-interaktif:
   ```bash
   npx -y create-next-app@latest gcs-client --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm
   ```
2. Pastikan struktur folder Next.js terorganisir dengan arsitektur berikut:
   ```text
   gcs-client/
   ├── src/
   │   ├── app/
   │   │   ├── layout.tsx         # Root layout + Global theme providers
   │   │   ├── page.tsx           # Halaman utama GCS Dashboard (4-Column Layout)
   │   │   └── globals.css        # Tailwind custom CSS & GCS design variables
   │   ├── components/
   │   │   ├── header/
   │   │   │   └── TopBar.tsx     # Header dengan status Tailscale IP, toggle YOLO & Theme
   │   │   ├── modal/
   │   │   │   └── ConnectionSetupModal.tsx # Modal konfigurasi koneksi UAV 1 & UAV 2
   │   │   ├── video/
   │   │   │   ├── VideoPanel.tsx # Container kamera (UDP/Webcam) + HUD Overlay
   │   │   │   └── HudCanvas.tsx  # Optimized Canvas renderer untuk YOLO bbox & Crosshair
   │   │   └── telemetry/
   │   │       ├── AttitudeIndicator.tsx # Artificial Horizon / PFD (Roll, Pitch, Heading)
   │   │       ├── AltitudeTape.tsx      # Vertical Altitude Tape
   │   │       └── TelemetryStats.tsx    # Angka GPS, Speed, Battery, & Target UDP
   │   ├── hooks/
   │   │   ├── useWebSocket.ts    # Custom hook untuk manajemen WebSocket re-connect
   │   │   └── useGCSStore.ts     # Global State Management untuk konfigurasi UAV
   │   └── types/
   │       ├── telemetry.ts       # Interface TypeScript untuk data MAVLink & UDP
   │       └── video.ts           # Interface TypeScript untuk frame & bbox YOLO
   ```

---

### TAHAP 3: Aturan Manajemen Data Frekuensi Tinggi (CRITICAL PERFORMANCE RULES)

LLM **WAJIB** mematuhi aturan berikut agar UI Next.js tidak mengalami *lag/freeze* akibat *re-render* React yang berlebihan:

#### 1. Telemetry & Attitude Indicator (10-30 Hz)
- **JANGAN** menyimpan stream telemetri mentah langsung ke `useState` pada komponen induk (`page.tsx`) jika memicu re-render seluruh halaman.
- Gunakan kombinasi **`useRef`** untuk menyimpan nilai instan dan **`requestAnimationFrame`** (atau throttling 15-30 FPS) untuk memperbarui visual SVG pada `<AttitudeIndicator />`.

#### 2. Video Frame & HUD Canvas Rendering
- Terima binary data (JPEG frames) atau WebSocket base64 stream di dalam hook/komponen `<VideoPanel />`.
- Gunakan **HTML5 Canvas (`useRef<HTMLCanvasElement>`)** untuk menggambar frame video dan bounding box YOLO `[x1, y1, x2, y2]`.
- Jangan pernah merender bounding box sebagai elemen DOM HTML (`<div>`) terpisah yang dibuat/dihapus puluhan kali per detik. Selalu gunakan `ctx.strokeRect` pada layer `<canvas id="hud-canvas">`.

---

### TAHAP 4: Spesifikasi Komponen & Kontrak Data

#### 4.1 `ConnectionSetupModal.tsx`
- Harus menyimpan konfigurasi (Stream Port, TCP IP, MAVLink Port, JSON Port untuk UAV 1 & UAV 2) ke `sessionStorage` atau Context/Store (`useGCSStore`).
- Melakukan validasi input sebelum menutup overlay.

#### 4.2 `AttitudeIndicator.tsx`
- Menerima prop `roll`, `pitch`, dan `heading` (dalam derajat).
- Menerapkan transformasi SVG secara presisi:
  - **Pitch**: Menggeser elemen tangga pitch (`translateY(pitch * scale)`).
  - **Roll**: Memutar seluruh horizon (`rotate(-roll deg)`).
  - **Heading Compass**: Memutar kompas melingkar (`rotate(-heading deg)`).

#### 4.3 `VideoPanel.tsx`
- Menyediakan tombol kontrol interaktif: **Fullscreen**, **Snapshot** (unduh frame canvas sebagai gambar `.png`), **Crosshair Toggle**, dan **HUD Toggle**.

---

### TAHAP 5: Rencana Verifikasi & Pengujian (Verification Checklist)

Setelah LLM selesai mengimplementasikan kode Next.js, lakukan verifikasi berikut:
- [ ] **Build Check**: Jalankan `npm run build` di dalam folder `gcs-client` untuk memastikan tidak ada kesalahan tipe TypeScript atau impor yang rusak.
- [ ] **CORS & Config Check**: Pastikan Next.js dapat mengambil data dari `http://localhost:8000/api/config` atau endpoint health check.
- [ ] **UI Rendering**: Pastikan layout 4 kolom (Video UAV 1 -> Telemetry UAV 1 -> Telemetry UAV 2 -> Video UAV 2) responsif, rapi, dan bertema gelap (*dark/tactical theme*) yang elegan.

---

## 3. Contoh Prompt Eksekusi Langsung untuk LLM

Jika Anda ingin langsung menugaskan LLM dengan satu instruksi cepat berdasarkan dokumen ini, salin dan jalankan perintah berikut:

```text
Baca dokumen NEXTJS_MIGRATION_LLM_BRIEF.md ini secara cermat. 
Pertama, tambahkan konfigurasi CORS dan endpoint /api/config pada app/main.py. 
Kedua, inisialisasi folder gcs-client dengan Next.js App Router + TypeScript + Tailwind CSS. 
Ketiga, migrasikan seluruh tampilan dan fitur index.html beserta logic telemetry.js dan video.js ke dalam komponen React modular di gcs-client sesuai standar optimasi performa tinggi pada dokumen ini.
```

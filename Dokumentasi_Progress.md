# Dokumentasi Pengembangan BIMA Base Station
**Fokus Pengembangan:** Fitur Swarm, Artificial Potential Field (APF), Data Logging, dan Pembaruan UI/UX Frontend
**Periode:** 31 Agustus 2026 – 11 September 2026

---

## 1. Pendahuluan
Dokumentasi ini merangkum proses pengembangan dan pembaruan fitur pada perangkat lunak *Ground Control Station* (GCS) BIMA Base Station. Pada iterasi pengembangan kali ini, fokus utama diberikan pada penerapan kontrol multi-UAV (Swarm), algoritma penghindaran tabrakan otomatis menggunakan APF, sistem pencatatan data telemetri (Logging), serta antarmuka pemantauan pada Base Station.

---

## 2. Fitur Data Logging Telemetri
Sistem logging yang baru memungkinkan pengguna (operator GCS) untuk secara dinamis menyimpan data telemetri yang mengalir dari UAV ke dalam penyimpanan lokal, sehingga berguna untuk proses post-flight analysis.

### A. Arsitektur Backend (Python/FastAPI)
- **`app/services/data_logger.py`**: Merupakan *core service* yang mengatur I/O stream ke dalam file lokal (mendukung format `.csv` dan `.jsonl`). Modul ini meng-handle multi-threading agar proses penulisan log tidak memblokir laju data MAVLink.
- **`app/routers/logging.py`**: REST API endpoints (`/start`, `/pause`, `/stop`, `/status`) yang diekspos ke frontend untuk mengendalikan state dari logging mesin.

### B. Arsitektur Frontend (Next.js/React)
- **`HeaderLoggingControl.tsx`**: Komponen UI *quick-access* pada navbar atas yang berisi tombol indikator sederhana (Record/Stop) dengan animasi berkedip merah saat *recording* sedang berlangsung.
- **`LoggingManager.tsx`**: Panel terdedikasi bagi operator untuk mengelola sesi logging secara mendetail, memonitor ukuran file yang sedang ditulis, dan durasi logging secara *real-time*.

---

## 3. Fitur Swarm dan Algoritma APF
Salah satu pembaruan masif adalah kapabilitas GCS untuk mengawasi dan mengkoordinasikan banyak armada UAV (Drone Swarm). Untuk memastikan setiap armada tidak bertabrakan, digunakan metode *Artificial Potential Field* (APF).

### A. Artificial Potential Field (APF)
Algoritma penghindaran tabrakan didesain dalam modul **`app/services/mavlink/apf_coordinator.py`**. Prinsip kerjanya:
1. **Gaya Tarik (Attractive Force):** Menarik UAV menuju titik tujuan / waypoint yang telah didefinisikan.
2. **Gaya Tolak (Repulsive Force):** Menghasilkan tolakan yang semakin kuat jika jarak antar UAV saling berdekatan melebihi batas toleransi.
Resultan dari kedua vektor gaya tersebut akan menghasilkan vektor arah kecepatan baru (velocity command) bagi tiap drone secara dinamis.

### B. Integrasi Swarm Backend
- **`swarm_coordinator.py`**: Mengelola status *fleet* (identifikasi *System ID* tiap UAV), meneruskan perintah gabungan (Takeoff All, Land All, RTL All) menuju jembatan MAVLink.
- **`routers/swarm.py` & `schemas/swarm.py`**: Mendefinisikan endpoint API yang aman untuk mendistribusikan koordinat misi ke setiap node drone di lapangan.

### C. Pembaruan Frontend Swarm
- **`SwarmSurveyMap.tsx`**: Peta (Mapbox/Leaflet) khusus yang mampu merender marker lebih dari 1 drone sekaligus, melacak jejak jalur penerbangan (*flight path*), serta menampilkan *geofence* batas area aman armada terbang.
- **`SwarmControlPanel.tsx`**: Pusat kontrol komando (`swarmApi.ts`) untuk melakukan *mass-action* terhadap seluruh drone yang terkoneksi pada satu waktu.

---

## 4. Pengujian Simulasi In The Loop (SITL)
Seluruh kegiatan teknis telah divalidasi menggunakan **SITL (Software In The Loop)** dengan skenario sebagai berikut:
1. **Uji Coba Fungsi Logging**: Memastikan start/stop API dapat berfungsi dengan jeda waktu minimal, serta memastikan data telemetri yang tersimpan sinkron dengan data asli (tanpa *packet loss* berlebih).
2. **Uji Coba Manuver Swarm**: Drone virtual berjumlah 2 hingga 4 diterbangkan pada rute yang berpotongan di area sempit.
3. **Validasi APF**: Mengevaluasi reaksi repulsif pada drone saat nyaris bersinggungan; terbukti APF berhasil merekalibrasi *heading* dan *velocity* untuk menghindari *mid-air collision*.
4. **Unit Testing (`test_apf_coordinator.py`)**: Skrip pengujian otomatis berbasis PyTest yang mengeksekusi *edge cases* seperti kalkulasi gaya apabila koordinat 2 drone identik.

---

## 5. Kesimpulan
Penambahan *Swarm Coordinator* membawa BIMA Base Station menjadi aplikasi terpusat untuk misi multikopter tingkat lanjut. Diperkuat dengan sistem *data logging* yang mulus, keseluruhan progres ini siap diterapkan pada prototipe perangkat keras (*Hardware In The Loop* / *Real Flight*).

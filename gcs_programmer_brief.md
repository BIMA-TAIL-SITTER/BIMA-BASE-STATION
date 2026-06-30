# Panduan Integrasi Telemetri & Video UAV (Ground Control Station)

Dokumen ini ditujukan untuk *Programmer Ground Control Station* (GCS) sebagai panduan integrasi sistem. UAV (Raspberry Pi) mengirimkan data hasil *Object Detection* (YOLO) beserta *Video Stream* murni (Raw) menggunakan protokol UDP.

Tugas utama sistem GCS adalah **menangkap data tersebut, me-render *bounding box* secara mandiri, dan menampilkan data ke layar antarmuka pengguna (UI).**

---

## 1. Arsitektur Komunikasi Jaringan

Data dikirimkan langsung dari UAV ke IP Ground Control Station menggunakan protokol **UDP (User Datagram Protocol)**. 
Terdapat dua *port* terpisah yang digunakan agar *bandwidth* tidak bertabrakan:

| Jenis Data | Protokol | Port | Tipe Konten | Keterangan |
| :--- | :--- | :--- | :--- | :--- |
| **JSON Telemetri** | UDP | `5005` | String UTF-8 | Berisi koordinat MAVLink, status AI, & Bounding Box. |
| **Raw Video Stream** | UDP | `5006` | Binary (Bytes) | *Frame* kamera murni (tanpa anotasi) berformat JPEG. |

### Frekuensi Pengiriman (Dynamic Frame Rate)
UAV memiliki logika cerdas untuk menghemat trafik jaringan (*bandwidth*):
- **Jika Tidak Ada Target**: Data JSON dan Video dikirim lambat dengan batas maksimal **5 FPS** (tiap 0.2 detik).
- **Jika Target Terdeteksi**: Data dikirim secara *continuous* dan secepat mungkin mengikuti FPS asli dari proses *Inference* YOLO (bisa mencapai belasan FPS).

---

## 2. Struktur Data Telemetri (Port 5005)

Data yang ditangkap pada Port `5005` merupakan JSON *String* yang harus di-*decode* dari UTF-8.
Berikut adalah contoh struktur payload JSON:

```json
{
    "timestamp": 1723456789.123,
    "fps_inference": 15.2,
    "detection": true,
    "conf": 0.95,
    "frame_size": [640, 480],
    "camera_fov": [70.0, 55.0],
    "lokasi_uav": {
        "lat": -7.123456,
        "lon": 110.123456,
        "alt_m": 50.0,
        "heading_deg": 90.0
    },
    "lokasi_target": {
        "lat": -7.123510,
        "lon": 110.123120,
        "dx_east_m": 5.2,
        "dy_north_m": -1.2,
        "distance_m": 5.3,
        "offset_px": [45.2, -12.1],
        "gsd_x": 0.051,
        "gsd_y": 0.051
    },
    "lokasi_deteksi_px": [365.2, 227.9],
    "bbox_px": [310, 200, 420, 255]
}
```

> [!NOTE]
> Jika `"detection": false`, maka *keys* `"lokasi_target"`, `"lokasi_deteksi_px"`, dan `"bbox_px"` akan bernilai `null`. Pastikan kode GCS mengecek status `"detection"` sebelum memproses *key* tersebut.

---

## 3. Struktur Data Video (Port 5006)

Data yang dikirim di Port `5006` adalah murni urutan **Bytes (Binary Data)**. 
- Bytes ini adalah gambar **JPEG** dengan kualitas (*compression*) menengah yang ukurannya dipastikan di bawah **65 KB** agar lolos limitasi 1 paket IPv4 UDP.
- Frame **TIDAK memiliki kotak hijau** (*bounding box*). Video sengaja dikirimkan bersih untuk meringankan beban komputasi UAV.

---

## 4. Instruksi Implementasi (To-Do List untuk GCS Programmer)

Untuk membangun antarmuka (*dashboard*) GCS yang berfungsi penuh seperti arsitektur Edge-Computing, lakukan langkah-langkah berikut secara *real-time*:

1. **Listen & Decode**:
   - Buat fungsi/thread yang me-*listen* `UDP Port 5006`. Lakukan *decode bytes* menjadi matriks gambar menggunakan *library* pengolahan gambar (Misal di Python: `cv2.imdecode()`).
   - Buat fungsi/thread yang me-*listen* `UDP Port 5005`. Lakukan `json.loads()` untuk mengubahnya menjadi struktur *Dictionary* atau *Object*.

2. **Render Bounding Box di Ground Station**:
   - Sinkronisasi: Saat JSON yang terbaru diterima dan `"detection"` bernilai `true`, ambil array `bbox_px`.
   - Array tersebut memuat 4 angka: `[x1, y1, x2, y2]`.
   - Gambarlah persegi panjang di atas gambar hasil *decode* video (Port 5006) menggunakan titik sudut **kiri-atas** `(x1, y1)` dan **kanan-bawah** `(x2, y2)`.

3. **Render UI & HUD Tambahan**:
   - **Crosshair**: Gambar tanda tambah (+) statis tepat di tengah layar video menggunakan nilai `"frame_size"` (Misal: 640/2 dan 480/2).
   - **Teks Confidence**: Gambar teks di atas Bounding Box berdasarkan nilai `"conf"`.
   - **Dashboard Geospasial**: Tampilkan nilai `"gsd_x"` (Ground Sample Distance), jarak target `"distance_m"`, koordinat UAV `"lokasi_uav"`, dan koordinat target `"lokasi_target"` ke dalam label/panel terpisah di UI.

> [!TIP]
> Karena paket UDP JSON (5005) dan Video (5006) datang secara terpisah dan asinkron, simpan JSON terbaru ke dalam *global variable / state*. Saat frame Video terbaru siap di-*render* ke layar, aplikasikan fungsi penggambaran (*drawing*) menggunakan data JSON yang ada di memori saat itu.

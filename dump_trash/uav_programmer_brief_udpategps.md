# Panduan Pembaruan Sistem UAV (Drone Programmer Brief)

Dokumen ini ditujukan untuk *Programmer Drone / UAV* untuk memahami pembaruan arsitektur pada kode sumber `stream_obj.py` dan `get_mav.py`. Sistem sekarang telah dikonversi menjadi aplikasi **Headless Edge-Computing** dengan fokus utama pada maksimalisasi *Framerate* (FPS) dan stabilisasi pengiriman telemetri.

Berikut adalah rangkuman struktur teknis dan pembaruan terkini:

---

## 1. Arsitektur Headless (Tanpa Flask Webserver)
- **Problem Sebelumnya**: Penggunaan Flask dengan generator `yield` membuat proses AI hanya berjalan jika ada yang membuka browser. Jika 2 orang membuka browser, AI akan dijalankan 2 kali lipat secara bersamaan yang berakibat pada *overheat* dan *lag* pada CPU Raspberry Pi.
- **Update Terbaru**: Flask telah dihapus total. Skrip `stream_obj.py` kini berjalan secara **Headless** (sebagai *Infinite Loop* murni). UAV akan mulai membaca kamera, mendeteksi objek, dan menyebarkan paket data via UDP secara otonom sejak skrip dijalankan.

## 2. Optimasi Kamera (Threaded Buffer)
- Pemanggilan sinkron `cap.read()` seringkali memunculkan *delay* (latency) karena antrean *buffer* frame USB Camera.
- **Update Terbaru**: Sistem menggunakan *class* `ThreadedCamera` yang berjalan pada *Background Daemon Thread*. *Thread* ini secara konstan menyedot dan membuang *frame* lawas, memastikan *Inference Loop* utama (YOLO) selalu memproses gambar *real-time* yang paling baru (tanpa *delay* sekecil apapun).

## 3. Optimasi Komputasi CPU (No Rendering)
- Karena CPU Raspberry Pi sangat terbatas, segala jenis proses menggambar piksel/grafis (`cv2.rectangle`, `cv2.putText`, `cv2.line`, `frame.copy()`) telah **dihapus**.
- **Edge-Computing**: UAV kini 100% dikhususkan untuk **Math & AI** (YOLO Inference + Kalkulasi Geolokasi). Tugas menggambar kotak hijau (Bounding Box) dan HUD telah dilimpahkan sepenuhnya ke komputer *Ground Control Station* (GCS).

## 4. Sistem Pengiriman Data (Dual-Port UDP)
Skrip kini mengirimkan dua jenis aliran data UDP secara bersamaan ke IP Ground Station (disimpan dalam *array* `GCS_IPS`):
1. **Port 5005 (JSON Telemetri)**: Memuat seluruh parameter penting: status deteksi, `bbox_px` (koordinat 4 titik), GSD (Ground Sample Distance), jarak, `offset_px`, dan data MAVLink UAV.
2. **Port 5006 (Raw JPEG Video)**: Frame kamera mentah (tanpa coretan) yang dikompres menjadi JPEG kualitas menengah (Quality = 50). Ini memastikan ukuran 1 *frame* video tetap berada di bawah batas maksimal 1 paket UDP IPv4 (**< 65 KB**), sehingga tidak terjadi kegagalan jaringan.

### Bandwidth Limiter (Dynamic FPS)
Untuk menghemat *bandwidth* radio telemetri:
- **Mode Standby**: Jika AI tidak melihat target, UAV hanya akan mengirim JSON dan Video maksimal **5 kali per detik** (5 FPS / interval 0.2 detik).
- **Mode Tracking**: Begitu target (Tarp) terlihat, UAV akan mengirim data secara *continuous* (mem-bombardir GCS secepat mungkin, setara dengan FPS YOLO Inference).

## 5. Keamanan Geolokasi (GPS HDOP Validation)
- **Problem Sebelumnya**: Saat drone di-*booting* dan belum mendapat sinyal GPS (Lat/Lon = 0), program tetap menghitung geolokasi yang berujung pada pengiriman koordinat ngawur (seperti koordinat di samudra Atlantik).
- **Update Terbaru**: File `get_mav.py` sekarang membaca parameter HDOP (`eph`) dari paket MAVLink `GPS_RAW_INT`. Di dalam `stream_obj.py`, perhitungan geolokasi *HANYA* akan dieksekusi jika fungsi `get_mav.is_gps_valid()` bernilai `True` (HDOP tidak sama dengan 0 atau 65535). Jika GPS belum mengunci (*lock*), sistem akan mengabaikan kalkulasi target dan mengembalikan `null`.

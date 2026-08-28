# Prompt: Program Pengiriman & Monitoring Misi GCS → Companion Computer (Raspi) → Flight Controller

## 1. Konteks

Sistem terdiri dari 3 pihak yang saling terhubung lewat MAVLink:

```
GCS  <--(udpout/udpin, MAVLink)-->  Raspi (companion computer)  <--(serial/udp, MAVLink)-->  FC (ArduPilot)
```

Sudah ada 3 script referensi yang jadi basis logic:

1. **`copter_control.py`** — logic kendali langsung ke FC: connect → cek misi ada → arm → takeoff →
   mode `AUTO` → `MAV_CMD_MISSION_START` → monitor `MISSION_ITEM_REACHED` per waypoint (hold 10 detik
   di tiap waypoint via `ALT_HOLD`, lalu balik `AUTO`) → `LAND` otomatis di waypoint terakhir → deteksi
   disarm sebagai tanda mission selesai.
2. **`gcs_uploader.py`** (nama sementara) — sisi GCS: build mission list, connect ke Raspi lewat
   `udpout`, heartbeat terus-menerus di thread terpisah, upload mission pakai MAVLink Mission Protocol
   penuh (`MISSION_COUNT` → `MISSION_REQUEST(_INT)` → `MISSION_ITEM_INT` → `MISSION_ACK`), bisa kirim
   ulang mission kapan saja (`update`).
3. **`companion_bridge.py`** (nama sementara) — sisi Raspi: listen terus dari GCS (`udpin`) dan FC secara
   bersamaan pakai thread terpisah (`gcs_listener_thread`, `fc_upload_worker`), terima `MISSION_COUNT`
   unsolicited dari GCS kapan saja, forward mission ke FC lewat Mission Protocol yang sama.

Program baru yang diminta adalah **penggabungan & perluasan** dari ketiganya, dengan tambahan gate
keamanan: **misi yang sudah ter-upload ke FC tidak boleh langsung membuat copter terbang** — copter
baru boleh arm & takeoff kalau user secara eksplisit memicu "Start Mission" dari sisi GCS.

## 2. Tujuan Program

Buat 3 file Python yang bekerja sama:

- `control_uav.py` — **definisi misi manual**, satu-satunya tempat waypoint didefinisikan/di-edit oleh user.
- `gcs_mission_client.py` — jalan di GCS: baca misi dari `control_uav.py`, upload ke Raspi, kirim sinyal
  "Start Mission" hanya saat user memintanya, menampilkan status/progress misi secara real-time.
- `companion_bridge.py` — jalan di Raspi: terima misi dari GCS lalu forward-upload ke FC, **tidak**
  langsung arm/takeoff hanya karena upload selesai; baru menjalankan urutan
  arm → takeoff → `AUTO` → `MISSION_START` (logic dari `copter_control.py`) saat menerima sinyal start
  eksplisit dari GCS; mem-forward event `MISSION_ITEM_REACHED` / status armed / mode balik ke GCS untuk
  monitoring.

## 3. Struktur Folder

```
project/
├── control_uav.py          # definisi mission manual (build_mission())
├── gcs_mission_client.py   # dijalankan di laptop/GCS
├── companion_bridge.py     # dijalankan di Raspberry Pi
└── README.md
```

## 4. Sumber Data Misi — `control_uav.py`

- Berisi fungsi `build_mission() -> list[dict]`, formatnya sama seperti contoh di `gcs_uploader.py`
  (list of dict dengan `command`, `param1..4`, `x`, `y`, `z`), tapi **diedit manual oleh user** setiap
  mau ganti rencana terbang (bukan digenerate otomatis dari sensor/algoritma).
- `gcs_mission_client.py` **mengimpor langsung** dari sini (`from control_uav import build_mission`),
  tidak boleh duplikasi definisi mission di file lain.
- Kalau user re-run atau memanggil `update`, `gcs_mission_client.py` harus re-import/reload
  `control_uav.py` supaya perubahan manual di file itu langsung terpakai tanpa restart total program
  (boleh pakai `importlib.reload` atau minta user restart client — sebutkan trade-off-nya di kode).

## 5. Alur Kerja End-to-End

1. User edit waypoint di `control_uav.py`.
2. `gcs_mission_client.py` dijalankan → connect ke `companion_bridge.py` (heartbeat thread aktif).
3. Client baca `build_mission()`, upload ke Raspi pakai Mission Protocol penuh (seperti
   `upload_mission()` di `gcs_uploader.py`).
4. `companion_bridge.py` terima mission lengkap dari GCS (`gcs_listener_thread` +
   `receive_mission_from_gcs`), lalu forward-upload ke FC (`fc_upload_worker` +
   `upload_mission_to_fc`) — **FC menerima misi, tapi tidak arm dan tidak takeoff.**
5. Client GCS menampilkan status: `"Mission uploaded ke FC, menunggu perintah Start Mission..."`.
6. **User mengetik/klik `start`** di sisi GCS — ini yang memicu penerbangan (lihat Bagian 6).
7. Sinyal start diteruskan Raspi → dijalankan Raspi lewat logic yang setara `copter_control.py`:
   `GUIDED` → arm → takeoff ke altitude default → `AUTO` → `MAV_CMD_MISSION_START`.
8. Raspi memantau `MISSION_ITEM_REACHED` dari FC dan mem-forward tiap event ke GCS (lewat
   `STATUSTEXT` atau custom message) supaya GCS bisa print progress real-time.
9. Waypoint terakhir tercapai → Raspi set mode `LAND` (reuse logic `monitor_mission()`), lalu deteksi
   disarm → forward status "mission selesai" ke GCS.
10. Setelah selesai/disarm, `companion_bridge.py` kembali idle, siap terima mission baru dari GCS
    (adaptive update, sesuai TODO safety di `companion_bridge.py` versi awal).

## 6. Mekanisme "Start Mission" (Safety Gate) — WAJIB

Ini requirement paling penting, jangan sampai terlewat saat implementasi:

- **Upload mission ≠ mulai terbang.** Setelah `MISSION_ACK` diterima FC, status harus tetap `IDLE`,
  motor tidak boleh armed.
- Sediakan command eksplisit di sisi GCS untuk memicu takeoff, minimal versi CLI dulu:
  ```
  [GCS] Ketik 'start' untuk menerbangkan copter menjalankan mission yang sudah di-upload, atau 'update'/'exit': 
  ```
  (boleh dikembangkan ke tombol GUI/web nanti — desain kode supaya fungsi "kirim sinyal start" terpisah
  dari UI, jadi gampang diganti CLI → GUI belakangan.)
- Sinyal "start" dikirim dari GCS ke Raspi sebagai pesan MAVLink tersendiri, terpisah dari Mission
  Protocol — pakai `command_long_send()` dengan command id khusus (mis. `MAV_CMD_USER_1`) atau
  konvensi `STATUSTEXT` dengan prefix tetap (mis. `"CMD:START_MISSION"`) supaya gampang di-parse Raspi
  dan tidak bentrok dengan pesan mission item lainnya.
- Di sisi Raspi (`companion_bridge.py`), sinyal start **hanya diterima/dieksekusi kalau**:
  - mission sudah selesai ter-upload penuh ke FC (`MISSION_ACCEPTED` sudah diterima), **dan**
  - tidak ada mission yang sedang berjalan (state flag `mission_running = False`).
- Kalau start diterima saat state tidak valid (belum ada mission, atau mission lagi jalan), Raspi
  balas STATUSTEXT/error ke GCS dan **tidak** melakukan apa-apa ke FC.
- Setelah start valid dieksekusi, set `mission_running = True`; reset ke `False` lagi setelah disarm
  terdeteksi (akhir mission).

## 7. Monitoring & Feedback Real-time (Raspi → GCS)

Raspi harus mem-forward status berikut ke GCS selama mission berjalan, minimal via `STATUSTEXT`:

- Konfirmasi mission ter-upload ke FC (`MISSION_ACCEPTED`/`MISSION_ERROR`).
- Konfirmasi sinyal start diterima & valid/ditolak.
- Perubahan mode (`GUIDED`, `AUTO`, `ALT_HOLD`, `LAND`) dan status armed/disarmed.
- Tiap `MISSION_ITEM_REACHED` (nomor waypoint).
- Status akhir: mission selesai (disarm setelah landing).

`gcs_mission_client.py` harus punya loop `recv_match` non-blocking/berjalan di thread terpisah supaya
bisa terus print status ini tanpa mengganggu input user (`start`/`update`/`exit`).

## 8. Penanganan Mission Baru Saat Terbang (Adaptive Update)

- Raspi tetap harus bisa menerima `MISSION_COUNT` baru dari GCS kapan saja, termasuk saat
  `mission_running = True` (sesuai desain awal `companion_bridge.py`).
- **Tapi**: kalau mission baru diterima saat `mission_running = True`, **jangan langsung full-reload**
  ke FC (bisa reset `current_seq` FC dan bikin copter bingung). Pilihan yang harus diimplementasikan
  (pilih salah satu, dan jelaskan di komentar kode kenapa):
  - antrikan mission baru, baru diupload otomatis setelah mission berjalan selesai/disarm; atau
  - gunakan `MISSION_WRITE_PARTIAL_LIST` untuk update sebagian waypoint tanpa mengganggu waypoint yang
    sedang dieksekusi, lalu panggil ulang `MISSION_SET_CURRENT` kalau perlu.
- Mission baru yang diterima Raspi TIDAK otomatis memicu start baru — tetap butuh sinyal `start`
  eksplisit lagi dari GCS kalau mission lama sudah selesai.

## 9. Requirement Teknis MAVLink

- Library: `pymavlink`.
- Mission Protocol lengkap untuk upload: `mission_count_send` → balas `MISSION_REQUEST(_INT)` →
  `mission_item_int_send` → `MISSION_ACK`.
- Heartbeat wajib dikirim terus-menerus dari GCS dan Raspi di thread `daemon=True` terpisah (reuse
  pola `heartbeat_sender()` yang sudah ada).
- Arm/takeoff/mission-start harus reuse logic `copter_control.py` (arm dengan retry, takeoff dengan
  monitor `GLOBAL_POSITION_INT`, `MISSION_START` command).
- Semua `recv_match(..., blocking=True, timeout=...)` harus punya timeout & penanganan `None`
  (jangan biarkan thread hang selamanya).

## 10. Logging & Format Output

- Ikuti gaya print yang sudah ada di script referensi: prefix `[*]` untuk aksi berjalan, `[+]` untuk
  sukses, `[-]` untuk gagal/warning.
- Semua pesan log tetap dalam Bahasa Indonesia, konsisten dengan script yang sudah ada.

## 11. Yang Perlu Diklarifikasi/Diasumsikan Kalau Implementasi Lanjut

- Trigger "Start Mission" versi awal diasumsikan **CLI** (`input()`), bukan GUI — kalau nanti mau
  tombol GUI/web dashboard, tinggal ganti pemicu event-nya saja karena fungsi pengirim sinyal start
  dibuat terpisah dari UI.
- Altitude default takeoff & durasi hold per waypoint diasumsikan sama seperti `copter_control.py`
  (5m takeoff, 10 detik hold) kecuali user tentukan lain.
- Command id/konvensi pesan untuk sinyal "start" (`MAV_CMD_USER_1` vs `STATUSTEXT` prefix) dipilih
  saat implementasi — pastikan konsisten dipakai di kedua sisi (GCS & Raspi).
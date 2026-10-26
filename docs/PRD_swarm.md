# Product Requirements Document (PRD)

## Integrasi Swarm Mission ke Main Dashboard & Nearest-Drone Waypoint Dispatch

**Versi:** 1.0 (Draft)  
**Tanggal:** 8 Oktober 2026  
**Status:** Spesifikasi perubahan, belum diimplementasikan  
**Area:** Main dashboard, `Swarm Information`, background map, GCS/base station, companion Raspberry Pi  
**Target sistem:** 2 UAV, 1 base station/GCS

> **Catatan cakupan audit:** Dokumen ini didasarkan pada analisis `companion_bridge.py` yang tersedia dari percakapan sebelumnya dan kebutuhan produk yang diberikan. Source code halaman `/swarm`, halaman utama, dan implementasi base station saat ini **belum tersedia untuk ditinjau**, sehingga isi tentang frontend/backend GCS di bawah adalah **desain usulan**, bukan klaim kondisi kode yang sudah ada. Belum ada perubahan source code aplikasi yang dilakukan.

## 1. Ringkasan produk

Pindahkan operasional swarm dari halaman terpisah `/swarm` ke **dashboard utama**. Operator menentukan waypoint dengan **klik kanan pada background map**, mengelola draft waypoint, dan menekan **Upload Waypoints** melalui panel **Swarm Information**. Saat operator menekan **Start Mission** secara eksplisit, base station menyiapkan swarm serta mendistribusikan tugas waypoint ke UAV yang paling dekat dan *eligible* (terhubung, posisi valid, sehat, dan tersedia). **Kedua drone menerima daftar waypoint sebagai informasi bersama, tetapi hanya pemilik tugas yang memperoleh perintah eksekusi navigasi untuk waypoint tersebut.** Keputusan assignment selalu di base station, bukan browser atau flight controller.

Tujuan: satu alur operasi yang mudah dilihat, mencegah waypoint ganda dieksekusi, transparan mengenai drone terpilih, dan tetap mempertahankan failsafe companion.

## 2. Fakta sistem existing yang berhasil diverifikasi

Dari `companion_bridge.py`:

- Companion menerima misi dari GCS melalui `MISSION_COUNT` dan `MISSION_ITEM_INT`/`MISSION_ITEM`; waypoint disimpan di antrean lokal, **bukan di-upload ke FC**.
- Upload misi **tidak** otomatis memicu arm/takeoff. `MAV_CMD_USER_1` (`31010`) adalah sinyal START terpisah.
- `FlightEngine` menggunakan ArduPilot `GUIDED` dengan position setpoint ~10 Hz. Urutan status: `IDLE → PRECHECK → ARMING → TAKEOFF → HOVER_STABILIZING → NAVIGATING ↔ HOLDING → RETURNING → LANDING → COMPLETED`, termasuk kondisi gagal.
- Misi saat ini berupa lintasan berurutan; indeks waypoint `0` diperlakukan sebagai `home`, dan indeks `1..N` dijalankan satu demi satu. Misi baru saat flight aktif disimpan sebagai `pending_mission`.
- Ada watchdog heartbeat GCS (default 3 detik) dan FC (default 5 detik), failsafe LOITER, serta mekanisme APF/safety untuk interaksi antardrone.

**Belum terverifikasi:** struktur komponen `/swarm`, routing Next.js yang sekarang, panel `Swarm Information` saat ini, library map, endpoint FastAPI, koneksi frontend–base station, dan apakah dispatch terpusat sudah memiliki implementasi tersendiri. Audit repository perlu mengonfirmasi bagian-bagian tersebut sebelum perubahan source code.

## 3. Masalah yang diselesaikan

1. Workflow swarm terpisah dari pemantauan peta utama sehingga operator harus berpindah halaman.
2. Pembuatan waypoint belum tersedia dalam workflow peta utama yang diinginkan.
3. Upload waypoint dan Start Mission perlu dipisahkan dengan status yang jelas dan ACK aktual.
4. Mendistribusikan misi yang sama dan memberi START pada kedua companion **tidak sama dengan assignment waypoint**, karena engine sekarang akan memulai navigasi mandiri.
5. Pemilihan UAV terdekat perlu deterministik dan bergantung pada telemetry aktual, bukan keputusan manual di frontend.

## 4. Target hasil dan batasan (MVP)

### Di dalam scope

- Semua kontrol operasional swarm tersedia di panel `Swarm Information` halaman utama.
- Klik kanan pada background map menampilkan menu `Add Waypoint Here` dan membaca koordinat geografis titik yang diklik.
- Marker waypoint memiliki nomor, koordinat, altitude target, urutan, status, dan pemilik UAV.
- Edit, hapus, clear, dan reorder waypoint saat masih berstatus draft.
- Tombol `Upload Waypoints`, `Start Mission`, `Pause/Hold`, `Abort/RTL` (sesuai safety policy), beserta progress dan status ACK.
- Base station sebagai sumber kebenaran assignment: nearest **eligible available** UAV menggunakan posisi mutakhir.
- Kedua UAV tersinkronisasi tentang plan waypoint, tetapi **hanya UAV yang di-assign** menerima/menjalankan `EXECUTE_WAYPOINT`.
- Status dan telemetry real-time menampilkan keputusan assignment serta progres per waypoint.
- Deduplikasi perintah, state machine, validasi, audit trail, dan failsafe.

### Di luar scope MVP

- Optimasi global multi-vehicle routing/TSP/VRP, prioritas berbasis baterai, estimasi ETA, atau prediksi trajektori kompleks.
- Otoritas navigasi otomatis dipindahkan ke browser.
- Penggantian algoritma avoidance/APF yang sudah ada.
- Reassignment saat drone masih bergerak tanpa kondisi aman yang terverifikasi.
- Penambahan UAV lebih dari dua (tetapi struktur data disiapkan agar dapat diperluas).

## 5. Pengalaman operator pada dashboard utama

### 5.1 Panel `Swarm Information`

Tampilkan satu panel operasional berisi:

| Kelompok | Elemen | Perilaku |
|---|---|---|
| Ringkasan | `Swarm: DISCONNECTED / READY / ACTIVE / HOLD / ABORTED / COMPLETED` | Status dari base station, bukan asumsi tombol frontend |
| Drone 1 dan Drone 2 | online, flight mode, armed, GPS fix, usia telemetry, baterai, posisi, jarak ke target, status `AVAILABLE/BUSY/FAULT` | Update live |
| Waypoint | `Total`, `Pending`, `Assigned`, `In Progress`, `Reached`, `Failed` | Selalu sinkron dengan state backend |
| Mission | mission ID, version, upload state, current task, assigned UAV, alasan assignment | Jelaskan hasil pemilihan drone |
| Aksi | `Upload Waypoints`, `Start Mission`, `Hold/Pause`, `Resume`, `Abort/RTL` | Gated sesuai status dan safety |
| Detail | expandable task queue, log event, error terakhir | Tidak menutupi peta |

**Aturan tombol:** `Start Mission` nonaktif sebelum semua validasi dan ACK upload terpenuhi; upload tidak boleh membuat drone arm. Perintah yang memengaruhi flight memerlukan konfirmasi jelas. Hanya satu operasi mutasi misi aktif pada satu waktu.

### 5.2 Pembuatan waypoint dari background map

1. Operator klik kanan pada area geografis peta (bukan panel atau kontrol UI).
2. Map menghitung latitude/longitude dari lokasi kursor; gunakan koordinat hasil map projection, **bukan pixel layar**.
3. Context menu menampilkan `Add Waypoint Here` beserta `Lat`, `Lon` dan pilihan altitude, menggunakan default altitude mission yang dapat diubah.
4. Setelah disimpan, marker `WP-01`, `WP-02`, dan seterusnya langsung muncul beserta daftar di `Swarm Information`.
5. Marker bisa dipilih untuk edit koordinat/altitude, hapus, dan lihat status; drag-to-move hanya jika library map mendukung dan misi masih draft.
6. Saat misi sudah di-upload, setiap edit mengubah draft dan membuat status `UNSYNCED`; harus upload ulang sebelum START. Saat misi aktif, edit tugas aktif terkunci (MVP: perubahan rencana ditahan sampai misi selesai).

**Catatan map:** cegah browser native context menu hanya di canvas map; jangan mengganggu klik kanan normal di bagian lain.

### 5.3 Visualisasi peta

- Marker drone 1 dan 2 dengan identitas berbeda dan data usia posisi.
- Marker waypoint bernomor dan berstatus: `DRAFT`, `PENDING`, `ASSIGNED`, `EN_ROUTE`, `REACHED`, `FAILED`, `CANCELLED`.
- Garis menghubungkan posisi drone menuju **tugas yang sedang dimilikinya**, bukan garis navigasi palsu menuju semua titik.
- Tooltip `Assigned: UAV-1` atau `Pending`; progres assignment muncul tanpa refresh manual.
- Jika marker drone stale, tampilkan indikator eksplisit dan nonaktifkan assignment untuk drone tersebut.

## 6. Alur utama

### 6.1 Merencanakan dan mengunggah

1. Kedua drone mengirim heartbeat, posisi GPS, status flight, dan health ke base station.
2. Operator membuat beberapa waypoint via klik kanan peta dan memeriksa urutan serta altitude.
3. Operator memilih `Upload Waypoints`.
4. Frontend mengirim snapshot draft ke backend dengan `mission_id` dan `mission_version`.
5. Base station memvalidasi schema, jumlah, koordinat, altitude, geofence, sistem koordinat altitude, kesiapan protokol, dan safety config.
6. Base station menyimpan plan secara atomik, membroadcast **PLAN_SYNC** ke kedua companion, lalu menunggu ACK plan/version dari **keduanya**.
7. UI menampilkan status `UPLOADED` hanya ketika ACK kedua UAV diterima. Jika salah satu gagal, status `PARTIAL/FAILED`; defaultnya `Start Mission` ditolak.

### 6.2 Memulai misi dan alokasi tugas

1. Operator menekan `Start Mission`; modal konfirmasi menampilkan mission ID, versi, jumlah waypoint, dua drone, dan pemeriksaan keselamatan.
2. Base station melakukan precheck baru pada heartbeat, GPS/posisi, baterai, arm/mode, komunikasi, geofence, dan readiness kedua drone.
3. Setelah START dikonfirmasi, base station mengirim perintah persiapan/takeoff dengan ACK terpisah **sesuai flight state masing-masing companion**, lalu menunggu keadaan `AVAILABLE`/hover stabil. Tidak ada auto-arm hanya karena upload.
4. Untuk setiap waypoint `PENDING`, scheduler menghitung jarak terhadap UAV yang `AVAILABLE` serta valid.
5. Scheduler mengunci `task_id → drone_id`, mengirim **TASK_ASSIGN** terarah ke pemilik, dan menunggu `TASK_ACK`.
6. UAV non-pemilik tetap berada pada mode standby/hold aman; tidak melakukan navigasi ke task tersebut, walaupun sudah memiliki salinan plan.
7. Companion terpilih menggerakkan UAV melalui GUIDED setpoint dengan safety controller yang ada dan melapor `EN_ROUTE`, `REACHED` atau `FAILED`.
8. Setelah task terminal, drone kembali `AVAILABLE` jika secara fisik dan operasional masih sehat. Base station memilih tugas berikutnya berdasarkan posisi mutakhir.
9. Scheduler dapat memberi dua **waypoint yang berbeda** secara bersamaan kepada dua UAV yang sama-sama available; tidak boleh memberi satu waypoint ke dua UAV. Aturan urutan adalah **urutan dispatch antrean**, bukan persyaratan bahwa seluruh waypoint dikerjakan satu per satu.
10. Setelah seluruh task terminal, base station melakukan end-action yang sudah dikonfigurasi (hold/RTL/land), melaporkan `COMPLETED`, dan mengarsipkan event log.

### 6.3 Hold, abort, dan link loss

- `Hold/Pause`: jangan keluarkan assignment baru; companion yang sedang navigasi masuk hold/LOITER sesuai kemampuan dan ACK. `Resume` memerlukan revalidation.
- `Abort/RTL`: hentikan scheduler, batalkan task pending, kirim instruksi flight aman ke setiap UAV dan tampilkan ACK per drone. Jangan menganggap stop UI = drone berhenti.
- Telemetry hilang atau ACK timeout: hentikan **assignment baru** ke drone tersebut. Task yang terlanjur diberikan masuk `UNKNOWN/HOLD_REQUIRED`; hindari otomatis memerintah drone lain ke area yang sama sampai aman.
- GCS heartbeat hilang: pertahankan kebijakan failsafe companion eksisting (LOITER/konfigurasi site); base station menghentikan dispatch baru.
- Penugasan ulang dilakukan hanya setelah memastikan pemilik lama tidak lagi melaksanakan tugas dan tidak ada risiko dua drone menuju target yang sama.

## 7. Nearest-drone assignment (base station)

**Input:** waypoint `W=(lat,lon,alt)`, telemetry drone D1 dan D2 terkini, status dan health.  
**Ukuran jarak MVP:** jarak permukaan bumi (Haversine dalam meter) antara posisi GPS drone dan lokasi waypoint. Altitude tetap diperiksa oleh validator flight, tetapi bukan skor nearest dasar.  
**Eligible:** connected, heartbeat/posisi masih fresh (threshold konfigurabel), GPS valid, `AVAILABLE`, tidak failsafe, tidak dalam hold, tidak sudah memegang task aktif, serta memenuhi safety checks.  
**Tie-breaker:** pilih ID UAV terkecil bila selisih jarak berada di dalam toleransi tie (misalnya 1 m, nilai konfigurabel).  
**Kapan dihitung:** tepat sebelum assignment, **bukan** ketika operator menambahkan marker.  
**Kunci task:** assignment disimpan secara atomik pada base station dan diberi `assignment_version` untuk mencegah duplicate command.

```python
# Pseudocode base station, bukan kode existing

def choose_owner(waypoint, drone_states):
    eligible = [d for d in drone_states if d.connected
                and d.telemetry_is_fresh
                and d.gps_valid
                and d.status == "AVAILABLE"
                and d.safety_ok]
    if not eligible:
        return None  # waypoint tetap PENDING
    eligible.sort(key=lambda d: (haversine_m(d.lat, d.lon,
                                             waypoint.lat, waypoint.lon),
                                 d.drone_id))
    return eligible[0]

# Dispatch harus dilakukan dalam transaksi/lock:
# PENDING -> ASSIGNED(owner, version) -> TASK_ACK -> EN_ROUTE -> REACHED
```

**Perilaku bila salah satu BUSY:** assign ke UAV available terdekat dari kandidat eligible; jika tidak ada kandidat, antre task. Tidak melakukan preemption terhadap UAV yang sedang melaksanakan tugas. Jika suatu waypoint harus mengikuti urutan geografis ketat, jalankan opsi `sequential_mode` terpisah di masa depan.

## 8. Kontrak data dan API yang diusulkan

Endpoint berikut adalah **usulan**, sesuaikan dengan router FastAPI/WebSocket yang ditemukan saat audit repo:

| Route / event | Tujuan |
|---|---|
| `GET /api/swarm/state` | Snapshot drone, link, mission, task status |
| `POST /api/swarm/missions` | Buat/ubah draft versioned, validate |
| `POST /api/swarm/missions/{id}/upload` | Sinkronisasi plan ke kedua UAV, kumpulkan ACK |
| `POST /api/swarm/missions/{id}/start` | Start eksplisit setelah precheck dan konfirmasi |
| `POST /api/swarm/missions/{id}/hold` | Pause assignment dan safe hold |
| `POST /api/swarm/missions/{id}/resume` | Resume setelah precheck |
| `POST /api/swarm/missions/{id}/abort` | Stop scheduler dan command per drone |
| `WS /ws/swarm` | Update telemetry, task, ACK, error, assignment tanpa polling berat |

Contoh data plan:

```json
{
  "mission_id": "swarm-20261008-001",
  "version": 3,
  "coordinate_frame": "GLOBAL_RELATIVE_ALT",
  "waypoints": [
    {"task_id": "wp-001", "sequence": 1, "lat": -7.7710171, "lon": 110.3731779, "alt_m": 10.0},
    {"task_id": "wp-002", "sequence": 2, "lat": -7.7710345, "lon": 110.3732442, "alt_m": 10.0}
  ]
}
```

Contoh event dispatch:

```json
{
  "type": "TASK_ASSIGN",
  "mission_id": "swarm-20261008-001",
  "mission_version": 3,
  "task_id": "wp-001",
  "owner_drone_id": 2,
  "assignment_version": 1,
  "target": {"lat": -7.7710171, "lon": 110.3731779, "alt_m": 10.0},
  "distance_at_assignment_m": 23.7,
  "command_id": "cmd-sw-00001"
}
```

**Transport:** WebSocket/API hanya UI ↔ base station. Gunakan koneksi MAVLink/GCS ↔ companion yang sudah ada sejauh memungkinkan. Karena `MISSION_COUNT` dan `MAV_CMD_USER_1` saat ini berkonotasi **jalankan misi lokal**, jangan langsung reuse pasangan perintah itu untuk broadcast plan + start dua UAV. Tambahkan semantics yang terpisah dan tervalidasi seperti `PLAN_SYNC`, `SWARM_PREPARE`, `TASK_ASSIGN`, `TASK_ACK`, `TASK_CANCEL`, `TASK_RESULT`, `SWARM_HOLD`, dengan transport aktual (MAVLink custom messages/komando terstruktur lain) yang disepakati saat audit. Jangan menambahkan nomor MAV_CMD arbitrer tanpa desain kompatibilitas.

## 9. Perubahan teknis yang harus dikerjakan

| Lapisan | Perubahan |
|---|---|
| Frontend dashboard utama | Tambah map right-click context menu, layer waypoint, daftar editor, marker assignment, panel `Swarm Information` sebagai pusat kontrol |
| Frontend `/swarm` | Migrasikan logic state/command yang reusable ke komponen/shared service; setelah validasi, `/swarm` jadi redirect atau tampilan read-only sesuai navigasi produk |
| Frontend state | Satu sumber state untuk mission draft/ack/live task, subscription WebSocket dengan reconnect/snapshot recovery |
| FastAPI/base station | `MissionStore`, `WaypointScheduler`, telemetry freshness validator, assignment lock, command dispatcher, ACK tracker, audit log |
| Protokol komunikasi | Bedakan `PLAN_SYNC` (dua UAV), `TASK_ASSIGN` (satu UAV), `PREPARE/START` (terkendali), status dan ACK dengan versioning |
| Companion Raspberry Pi | Ganti asumsi 'semua waypoint lokal dieksekusi setelah START' menjadi task-per-assignment; pertahankan GUIDED setpoint, safety, APF, heartbeat, dan phase logic |
| Observability | Event mission/task/drone, metrik assignment decision, jarak dan freshness, latency ACK, gagal upload, failsafe |
| Testing | Unit scheduler, integration protocol, UI test, dua companion simulasi/SITL, negative/safety tests |

**Kompatibilitas:** tetap sediakan mode legacy mission upload untuk client lama melalui feature flag; jangan aktifkan kedua mode pada sesi swarm yang sama. Mapping `seq=0 home` hanya untuk legacy; task waypoint UI baru harus diberi `task_id` independen, dan home setiap UAV berasal dari home aktual masing-masing.

## 10. Model state

```text
Mission:  DRAFT -> VALIDATED -> UPLOADING -> UPLOADED -> READY
              -> ACTIVE <-> HELD -> COMPLETED
              -> ABORTING -> ABORTED
              -> FAILED

Task:     DRAFT -> PENDING -> ASSIGNED -> ACKED -> EN_ROUTE
                                      -> REACHED
                                      -> FAILED / CANCELLED / UNKNOWN

UAV:      DISCONNECTED -> CONNECTED -> PRECHECK -> PREPARING
                  -> AVAILABLE <-> BUSY -> HOLD/RTL/LAND
                  -> FAULT
```

State server otoritatif; frontend tidak mengubah status `UPLOADED`, `ACTIVE`, atau `REACHED` secara optimistis. State transisi yang tidak sah menghasilkan `409 Conflict` dan alasan kegagalan.

## 11. Safety dan ketahanan

- **Tidak ada auto-arm saat upload.** Tombol START terpisah, memerlukan autentikasi/otorisasi operator dan konfirmasi sebelum command yang dapat menyebabkan flight.
- **Single owner:** `(mission_id, task_id)` paling banyak mempunyai satu assignment aktif; command berulang dengan `command_id` sama bersifat idempotent.
- **ACK end-to-end:** HTTP sukses hanya berarti permintaan diterima server, bukan sudah diterima flight controller; UI tampilkan status dua lapis (`server accepted`, `UAV ACK`).
- **Telemetry freshness:** tolak posisi stale/0,0 dan GPS invalid; gunakan timestamp monotonic/local receive time pada server.
- **Geofence/altitude/flight readiness:** seluruh waypoint wajib diperiksa terhadap konfigurasi lokasi operasi dan batas aman sebelum upload maupun dispatch.
- **Collision avoidance:** APF/safety tetap berjalan di companion tanpa ditiadakan oleh scheduler; UAV tidak boleh saling menuju tugas yang berbahaya hanya karena jarak minimal.
- **Heartbeat loss:** stop dispatch; companion menjalankan failsafe setempat. Tampilan UI tidak boleh mengklaim UAV aman hanya karena perintah terkirim.
- **Mid-mission updates:** perubahan draft tidak diam-diam mengganti task aktif. Require version baru dan explicit upload/restart atau mekanisme append yang dirancang terpisah.
- **Recovery/restart:** simpan versi misi, task owner, result, command ID, dan event di storage server; setelah reconnect lakukan resync dan reconciliation sebelum assignment baru.

## 12. Acceptance criteria

| ID | Skenario | Hasil yang wajib |
|---|---|---|
| AC-01 | Buka halaman utama | Semua informasi dan tombol mission tersedia di `Swarm Information` tanpa perlu `/swarm` |
| AC-02 | Klik kanan peta | Menu `Add Waypoint Here` muncul di koordinat yang benar |
| AC-03 | Tambah 3 waypoint | Tiga marker dan entri daftar tampil sesuai urutan, bisa edit/hapus saat draft |
| AC-04 | Klik `Upload Waypoints` | Mission/version yang sama dikirim ke dua UAV; status `UPLOADED` hanya setelah dua ACK |
| AC-05 | Upload saja | Tidak ada UAV yang otomatis arm atau takeoff |
| AC-06 | Klik `Start Mission` dengan data belum lengkap | Ditolak dan alasan ditampilkan |
| AC-07 | Dua UAV sehat, posisi valid, jarak D1=35m dan D2=20m | WP ditugaskan D2; D1 tidak menerima command navigasi ke WP itu |
| AC-08 | D2 busy, D1 available | Task berikutnya dapat ditugaskan ke D1; jika semua busy task tetap pending |
| AC-09 | Dua UAV distance tie | Pemenang konsisten berdasarkan aturan tie-breaker |
| AC-10 | Task sudah di-assign lalu request terduplikasi | Tetap hanya satu owner dan satu eksekusi per command ID |
| AC-11 | GPS D1 stale atau invalid | D1 tidak masuk kandidat nearest dan UI menandai stale |
| AC-12 | Task aktif menerima `REACHED` terverifikasi | Marker status berubah, owner kembali available jika sehat |
| AC-13 | ACK task timeout | Tidak ada assignment otomatis yang menyebabkan dua UAV ke target sama |
| AC-14 | Koneksi GCS putus saat flight | Scheduler berhenti dispatch; failsafe companion dipertahankan |
| AC-15 | Hold, abort, reconnect | Status UAV dan task direkonsiliasi dari telemetry/ACK nyata |
| AC-16 | Uji SITL 2 UAV dengan beberapa waypoint | Setiap task selesai maksimal satu kali, owner valid, log assignment lengkap, tanpa auto-arm saat upload |

## 13. Rencana pengerjaan dan prioritas

**P0 — audit & kontrak:** telaah source `/swarm`, main page, map, panel, router/backend, konfigurasi port, dan packet MAVLink aktual. Petakan ownership state/UI dan semua safety path.

**P1 — backend scheduler:** definisikan mission/task model, mission versioning, telemetry snapshot, nearest selector, atomic assignment, ACK/idempotensi, persistence, command protocol.

**P2 — companion:** tambah plan-only synchronization dan execution-by-owner tanpa memutus jalur GUIDED/APF/watchdog/RTL yang ada; uji bahwa non-owner **tidak navigasi**.

**P3 — frontend:** migrasi tombol ke `Swarm Information`, right-click background map, editable waypoint list, progress and assignment overlays, real-time subscription.

**P4 — integrasi & validasi:** unit tests, protocol failures, reconnect, dua SITL, safety drills, hardware-in-the-loop dengan propeller dilepas, lalu uji terbang hanya di area dan prosedur yang disetujui.

## 14. Keputusan desain yang ditetapkan

1. **Base station adalah otoritas assignment**; frontend hanya operasi dan visualisasi.
2. **Semua waypoint tersinkronisasi ke dua drone sebagai plan**, tetapi target navigasi hanya dikirim ke satu pemilik tugas.
3. **Nearest** dihitung dari posisi terkini dalam meter di waktu dispatch, dan hanya dari UAV yang eligible.
4. **Plan upload berbeda dari start**; keduanya membutuhkan ACK/status berbeda.
5. **Satu drone maksimal satu task aktif** untuk MVP; dua drone dapat menjalankan task *berbeda* secara paralel.
6. **Safety companion existing tetap prioritas** terhadap instruksi scheduler.
7. **Belum menghapus `/swarm` sampai audit routing dan fitur legacy selesai.**

## 15. Definition of Done

- Operator bisa merencanakan, meng-upload, memulai, mengamati, dan menghentikan swarm dari main dashboard.
- Dua drone mempunyai salinan plan yang sama, tetapi hanya owner yang mengeksekusi tiap task.
- Pemilihan berdasarkan jarak adalah reproducible, terlog, dan diverifikasi dengan SITL.
- Semuanya aman terhadap stale GPS, partial upload, ACK hilang, reconnection, duplicate command, dan GCS heartbeat loss.
- Unit/integration/UI/SITL tests lulus; perubahan source code, API, dan cara operasi terdokumentasi.

---

**Status aktual setelah penyusunan PRD:** PRD selesai dibuat. **Kode aplikasi belum diubah** karena repository `/swarm` dan halaman utama tidak tersedia dalam konteks yang dapat ditinjau saat ini.

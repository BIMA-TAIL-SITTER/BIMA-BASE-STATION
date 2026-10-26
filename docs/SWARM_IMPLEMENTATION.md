# Implementasi swarm dashboard dan nearest-owner dispatch

## Hasil audit repository

PRD dibaca seluruhnya. Temuan source berbeda dari asumsi awal PRD:

- Empat slot monitoring tetap digunakan: fixed wing **1/2**, copter swarm **3/4**.
- Dashboard: `gcs_js/src/app/page.tsx`; background map memakai Leaflet/react-leaflet dan MBTiles. `SwarmStatusOverlay` sebelumnya hanya telemetry/APF dan polling legacy.
- `/swarm` sebelumnya merender `SwarmControlPanel`: generator survey polygon, import `.waypoints`, upload dua lintasan berbeda, START legacy, abort, reset.
- `SwarmCoordinator` menjalankan CLI subprocess melalui UDP mission port. START memakai `MAV_CMD_USER_1`. APF existing adalah `app/services/mavlink/apf_coordinator.py` di GCS.
- Companion repository **bukan** `FlightEngine` GUIDED yang dideskripsikan PRD. Ia menyimpan upload secara lokal, lalu START menjalankan mini-mission `[home,target]` melalui `AUTO`. Watchdog existing memerintahkan LOITER saat GCS hilang.
- Timestamp telemetry dashboard diperbarui saat broadcast. Timestamp itu tidak dipakai sebagai bukti freshness scheduler baru.

## Implementasi

### Operasi utama

1. Buka dashboard dan atur **Raspi IP / Mission UDP Port** UAV-3 serta UAV-4 di Edit Connection.
2. Klik kanan background map → **Add Waypoint Here**. Koordinat berasal dari `LeafletMouseEvent.latlng`.
3. Di **Swarm Information**, edit koordinat/altitude, drag marker, reorder, hapus atau clear draft. Edit setelah upload menandai `UNSYNCED`. Draft lokal disimpan di session storage; secret operator hanya di memori.
4. Masukkan operator token dan pilih **Upload Waypoints**. Plan/version/hash yang sama dikirim ke dua companion. Upload tidak mengirim ARM/takeoff atau mengunggah mission AUTO ke FC.
5. START aktif hanya setelah dua ACK dan precheck baru. Konfirmasi menyebut mission/version, kedua UAV, altitude persiapan, dan end action.
6. PREPARE terpisah menjalankan GUIDED → ARM dengan pre-arm checks FC → takeoff → hover stabil. Scheduler menunggu kedua companion `AVAILABLE`.
7. Saat START (copter masih di darat) base station menjalankan route planner min-max (`route_planner.solve`) dari posisi takeoff: waypoint dibagi dan diurutkan per UAV agar makespan minimum. Planner gagal berarti START ditolak. Tiap UAV lalu menerima waypoint berikutnya di antreannya sendiri, hanya bila sehat dan AVAILABLE. Satu owner/task dan satu task aktif/drone; dua task berbeda berjalan paralel. Target yang melanggar clearance terhadap posisi/target peer tetap pending; bila UAV peer idle tanpa antrean menghalanginya lebih dari `SWARM_DEFER_S`, waypoint itu dialihkan ke peer. Waypoint tambahan (append) atau UAV yang kehabisan antrean sementara peer masih punya waypoint memicu replan di background (thread, lock tidak ditahan); dispatch baru menunggu hasilnya, dan replan gagal berarti HOLD. Parameter model biaya: `SWARM_PLANNER_*`.
8. Hanya owner menerima `TASK_ASSIGN`. Kedua drone menyimpan plan bersama. Companion menjalankan setpoint GUIDED sekitar 10 Hz; APF existing dihitung pada tick rate konfigurasinya. Standby menahan posisi sendiri, bukan menuju target peer.
9. REACHED mensyaratkan posisi, altitude, kecepatan dan dwell aktual di companion, lalu diverifikasi kembali oleh base station bersama identity task/command/version. End action default RTL. COMPLETED menunggu disarm aktual untuk RTL/LAND, atau LOITER terkonfirmasi untuk end action HOLD.

Route `/swarm` dan menu duplikatnya sudah dihapus. Survey generator/import dan kontrol lama tersedia di **`/swarm/legacy`**, melalui tautan panel. `SWARM_LEGACY_ENABLED` mengatur API legacy. Mode companion `legacy` tetap default; mode `swarm` terpisah. API legacy/direct mission/ARM tidak dapat mengambil alih copter yang dimiliki dispatcher. Mode aman LOITER/RTL/LAND existing masih dapat dikirim operator.

### Tambah waypoint saat misi aktif

- Pada fase `ACTIVE` atau `HELD`, isi token operator, klik kanan peta, isi altitude, lalu pilih **Tambah ke misi aktif**. Tidak perlu upload ulang atau menekan Mulai. WP lama tetap tidak dapat diedit, dihapus, diurut ulang, atau digeser. Total maksimal 200 WP.
- API terautentikasi `POST /api/swarm/missions/{mission_id}/append` menerima `version`, `confirmation: CONFIRM_APPEND`, dan hanya waypoint tambahan dengan sequence lanjutan. Server memeriksa capability `PLAN_APPEND` kedua companion, health, geofence, ID unik, dan versi saat ini.
- Server menyimpan revisi `APPENDING` secara atomik sebelum mengirim `PLAN_APPEND` (candidate plan lengkap, `base_version`, `base_hash`) kepada kedua UAV. Companion hanya menerima prefix plan yang identik; target, task owner, fase, timer dwell, dan ledger eksekusi tetap dipertahankan. Perintah ini tidak mengirim perintah flight ke FC.
- Penugasan baru berhenti sementara selama sinkronisasi. WP tambahan baru menjadi `PENDING` setelah ACK hash dan telemetry plan terbaru dari kedua UAV cocok. Tugas yang sudah berjalan tetap berjalan.
- ACK hilang atau tidak cocok menyebabkan HOLD kedua UAV. Tambahan tetap tersimpan sebagai `append_pending`, belum masuk antrean dispatch. Setelah Hold terkonfirmasi, pilih **Ulangi sinkronisasi WP**, lalu **Lanjut** secara eksplisit. Retry tidak menggandakan task. Jika restart terjadi saat sinkronisasi, lakukan Hold/reconciliation terlebih dahulu; tidak ada auto-resume.
- Companion lama tidak mengumumkan capability `PLAN_APPEND`, sehingga fitur tidak dibuka sampai kedua companion diperbarui. Jalankan ulang companion hanya setelah operasi penerbangan selesai. Runtime mandiri di folder `swarm1/bima_swarm` juga membutuhkan pembaruan `companion.py` dan `protocol.py`.

### Safety dan recovery

- Geofence lingkaran lokasi, altitude relatif home, battery, GPS, sensor health, FC mode/armed, heartbeat dan posisi diperiksa. Tidak ada bypass jarak takeoff untuk lokasi identik.
- FC/home berasal dari FC masing-masing; waypoint pertama bukan dummy home. APF membandingkan altitude peer dalam referensi MSL yang sama.
- GCS/FC/peer stale menghentikan navigasi/assignment baru. Companion melakukan LOITER tanpa disarm dan menghormati RTL/LAND yang telah aktif.
- HOLD dan ABORT memiliki ACK per companion setelah heartbeat FC mengonfirmasi mode. `ABORTED` berarti perintah RTL telah terkonfirmasi, bukan berarti drone sudah mendarat.
- ACK tugas hilang → `UNKNOWN`, owner tetap terkunci, scheduler hold. Tidak ada reassignment otomatis.
- State/assignment/command ID dan append-only audit disimpan dalam transaksi SQLite (`data/swarm.sqlite3`, WAL/FULL). Companion memiliki journal atomik sendiri. Snapshot lengkap dikirim melalui WebSocket setiap 500 ms.
- Restart base station saat flight → `RECOVERY_REQUIRED`. Operator harus HOLD lalu RESUME setelah reconciliation; tidak ada dispatch otomatis dari state lama. Restart saat upload plan-only → PARTIAL dan wajib upload ulang.
- Restart companion saat task aktif → UNKNOWN/FAULT; task tersebut tidak boleh di-resume. Abort, konfirmasi kedua drone disarmed, kemudian buat/upload versi baru.
- Jika end action HOLD, plan tetap terkunci selama airborne. Abort/RTL atau mode aman existing dapat mengakhiri penerbangan sebelum plan baru.
- Data posisi usang tidak digambar sebagai garis assignment aktif. Map tidak membuat marker drone dengan koordinat default/fiktif saat belum ada posisi.

## Kontrak MAVLink

Tidak ada nomor MAV_CMD baru. Transport memakai **MAVLink 2 `TUNNEL` (message 385)**, payload type privat lokal **32768**, antara GCS `255/190` dan companion `3/191` atau `4/191` pada UDP mission endpoint existing. FC tidak menerima pesan plan swarm.

Framing: payload maksimum 128 byte; header network-endian `!2s8sHH` berisi magic `S1`, SHA-256 8-byte message identity, index chunk, jumlah chunk. Sisa 114 byte merupakan JSON envelope. Reassembly menerima reorder/duplicate, dibatasi 1024 chunk/message dan 16 assembly dengan expiry 5 detik. Envelope `body` canonical JSON + HMAC-SHA256 memakai `SWARM_LINK_KEY`.

Body: `protocol=1`, `session_id`, `drone_id`, `kind`; command membawa `boot_id`, `command_id`, `command_seq`, `mission_id`, `version`. `TASK_ASSIGN` juga membawa `task_id`, `assignment_version=1`, `owner_drone_id`, dan target identik dengan plan. Command ID/payload deduplicated dan urutan command mencegah START terlambat mengalahkan ABORT. ACK cocok dengan source/target MAVLink, boot, operation, command ID, mission/version; plan ACK menyertakan hash plan.

Operasi: `HELLO`, `GCS_HEARTBEAT`, `PLAN_SYNC`, `PREPARE`, `TASK_ASSIGN`, `HOLD`, `RESUME`, `ABORT`, `END`; balasan `ACK` dan `STATE`. Tidak ada fallback ke legacy saat handshake gagal. STATE membawa sequence, actual FC telemetry/usia per message, task/result, phase, plan hash, safety hash, boot, dan echoed GCS heartbeat counter. Freshness menggunakan monotonic receive time ditambah usia FC dan conservative round-trip bound, tanpa sinkronisasi jam Pi/laptop.

HOLD/ABORT tetap dapat diterima pada plan-version mismatch karena merupakan perintah keselamatan terautentikasi; navigasi/PREPARE/RESUME tetap mensyaratkan plan/version yang sama. Journal tidak mengizinkan kedua mode mission aktif dalam proses companion yang sama.

## Konfigurasi deployment

### Base station

Isi `.env` berdasarkan `.env.example`:

- `SWARM_OPERATOR_TOKEN`: token operator untuk API mutasi, dimasukkan di panel.
- `SWARM_LINK_KEY`: secret berbeda, minimum 32 karakter; sama di kedua Pi.
- `SWARM_CENTER_LAT`, `SWARM_CENTER_LON`: lokasi operasi aktual. Default belum diisi dan memblokir upload/start.
- Radius, altitude minimum/maksimum/takeoff, battery minimum, APF separation/tuning, freshness, ACK timeout, tie tolerance, dan end action.

### Kedua companion

Deploy source `mission_scripts` dan module APF existing dari repository pada Pi. Salin `mission_scripts/swarm_safety.example.json` ke file site lokal, isi latitude/longitude aktual, dan samakan semua safety/APF parameter dengan base station. Hash konfigurasi harus cocok. Contoh template sengaja belum memiliki lokasi operasi.

Jalankan dari root repository (environment `SWARM_LINK_KEY` harus diisi):

```bash
# Pi UAV-3; sesuaikan serial, baud dan SYSID FC aktual
python -m mission_scripts.companion_bridge --mission-mode swarm --uav-id 3 \
  --listen-port 14560 --fc-connection /dev/ttyACM0 --fc-system-id 1 \
  --swarm-safety /path/to/site.json --swarm-journal /path/to/uav3-journal.json

# Pi UAV-4 menggunakan --uav-id 4 dan journal sendiri.
# UDP port boleh sama pada IP Pi yang berbeda.
```

Swarm mensyaratkan heartbeat autopilot ArduPilot copter nyata sebelum engine dimulai. Tidak ada simulated telemetry, artificial ACK, atau dummy FC dalam jalur produksi. Mode lama tetap dapat dijalankan dengan `--mission-mode legacy`. Keduanya tidak boleh dijalankan bersamaan pada FC yang sama.

## API

| Route | Keterangan |
|---|---|
| `GET /api/swarm/state` | Snapshot otoritatif, eligibility blockers, ACK, tasks, events |
| `POST /api/swarm/missions` | Plan versioned + endpoints slot 3/4; validasi dan atomic save |
| `POST /api/swarm/missions/{id}/upload` | PLAN_SYNC dan ACK kedua companion |
| `POST /api/swarm/missions/{id}/start` | PREPARE setelah fresh precheck |
| `POST /api/swarm/missions/{id}/hold` | Hentikan dispatch, konfirmasi LOITER |
| `POST /api/swarm/missions/{id}/resume` | Revalidate/reconcile owner, lanjutkan |
| `POST /api/swarm/missions/{id}/abort` | Cancel pending, RTL kedua UAV dengan ACK |
| `WS /ws/swarm` | Full snapshot/reconnect recovery, read-only |

Mutasi memakai `Authorization: Bearer <operator-token>`. Action body: `{ "version": 1, "confirmation": "CONFIRM_START" }` (sesuaikan suffix START/HOLD/RESUME/ABORT). Upload hanya membutuhkan version. State/version conflict → 409; schema/geofence invalid → 422. Status `SERVER_ACCEPTED` terpisah dari `UAV_ACK`; PREPARE ACK bukan bukti hover/takeoff selesai.

## Peta file perubahan

- `app/services/mission/{waypoint_scheduler,dispatch_store}.py`: eligibility, antrean rute per UAV, replan/handoff, state machine, locks, persistence/audit dan recovery.
- `app/services/mission/{route_planner,route_cost}.py`: min-max route planner (Held–Karp / CP-SAT / OR-Tools Routing / cluster-first) dan model biaya waktu (yaw, angin, dwell).
- `app/services/mavlink/swarm_link.py`: persistent real UDP MAVLink, handshake, fragmentation, ACK tracking, heartbeat/peer relay.
- `mission_scripts/{swarm_protocol,swarm_companion}.py`, `companion_bridge.py`: shared wire contract, assignment-only GUIDED engine, mode selection. Algoritma `apf_coordinator.py` existing digunakan kembali.
- `app/schemas/waypoint_dispatch.py`, `app/routers/waypoint_dispatch.py`, `app/main.py`: schema/API/authorization/WebSocket dan lifecycle.
- `app/routers/{swarm,control}.py`: mutual exclusion legacy/direct controls; konfigurasi endpoint per slot tetap menyimpan field legacy `gcs`.
- `app/config/settings.py`, `.env.example`, `mission_scripts/swarm_safety.example.json`, `.gitignore`: konfigurasi dan local operational storage.
- `gcs_js/src/components/swarm/*`, `src/types/dispatch.ts`: shared draft/server state, queue editor, ACK, confirmation dan flight controls.
- `gcs_js/src/components/map/{PetaOfflineUav,SwarmWaypointLayer}.tsx`: right-click geografis, markers, drag, active-owner lines, stale indication.
- `gcs_js/src/components/telemetry/SwarmStatusOverlay.tsx`, `src/app/{page,layout}.tsx`, `src/app/swarm-mission.css`: integrasi panel/dashboard dan styling mengikuti theme existing.
- `gcs_js/src/app/swarm/{page,legacy/page}.tsx`: redirect main dan akses planner legacy. `src/types/swarm.ts`: memperbaiki type endpoint START existing.
- `tests/test_{waypoint_dispatch,swarm_companion,dispatch_api}.py`, `gcs_js/tests/swarmMission.test.mjs`, `requirements-dev.txt`, `gcs_js/package.json`: verification dan runner.

## Pengujian dan batas verifikasi

Perintah:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pytest -q
cd gcs_js
npm test
npx tsc --noEmit
npm run build
npm run lint
```

Suite baru memeriksa nearest/tie/busy, dual plan ACK/no-arm, partial upload, authorization, concurrent mutation, versioning, stale GPS, lost ACK/single owner, verified REACHED, recovery, HOLD/abort, delayed commands, companion restart, dan **dua koneksi UDP/MAVLink loopback sungguhan**. FC test doubles hanya berada di test code; loopback ini bukan validasi dinamika penerbangan. UI component tests mengeksekusi event right-click/submit, lock/drag gating, owner lines, serta upload/start/confirmation gating.

Hasil verifikasi: **81 test Python lulus**, **10 test frontend lulus**, TypeScript dan build produksi Next.js lulus, lint terarah pada file fitur ini lulus. `git diff --check` lulus. Lint global gagal dengan **26 error existing** pada FullDataManager, HeaderLoggingControl, LoggingManager, SwarmControlPanel, SwarmSurveyMap, StitchingSessionControl, CopterTelemetryPanel, TelemetryStats, swarmApi, types/telemetry dan telemetryFormatters.

**Belum tervalidasi:** AC-16 dua ArduPilot SITL, hardware-in-the-loop, actual FC/home/health streaming pada kedua Pi, APF tuning/dinamika terbang, dan visual browser end-to-end. Lingkungan kerja tidak menyediakan executable `arducopter`/`sim_vehicle.py` atau Playwright. Tidak ada perintah flight yang dikirim ke UAV pengguna selama pengujian.

Untuk AC-16, jalankan dua ArduPilot SITL dengan SYSID/port/posisi awal berbeda dan separation sesuai site config, lalu dua companion dalam mode swarm pada endpoint nyata masing-masing. Upload beberapa task melalui dashboard; pastikan keduanya tetap disarmed setelah upload. START eksplisit, verifikasi event SQLite `TASK_ASSIGN/TASK_ACK/TASK_REACHED` tiap task maksimal sekali dengan owner valid. Ulangi dengan GPS/link stale, drop ACK, hold/resume, abort dan restart base station. Sampai pengujian tersebut dilakukan, Definition of Done PRD terkait SITL/flight belum dinyatakan selesai.

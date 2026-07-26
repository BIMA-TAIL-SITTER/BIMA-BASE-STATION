# BIMA-BASE-STATION — Project Cleanup & Fix Plan

> **Status: DOCUMENT ONLY.** Ini rencana tertulis untuk direview. Approval terhadap dokumen ini TIDAK otomatis berarti eksekusi langsung — eksekusi baru jalan kalau user secara eksplisit minta lanjut, langkah per langkah, terutama untuk perubahan git (`git rm --cached`) dan keputusan terbuka di bawah.

## Context

BIMA GCS adalah multi-UAV Ground Control Station (FastAPI backend `app/` + Next.js 15 frontend `gcs-client/`) untuk swarm field mapping — monitoring telemetry, video/YOLO detection, dan peta offline. User dan rekan aktif kerja di project ini dan mau proyek dirapikan dulu sebelum lanjut fitur baru (swarm integration, 4-slot MAVLink — lihat `swarm_integration_audit_plan.md`).

Repo sudah diverifikasi dua kali (audit awal + re-verifikasi setelah percobaan cleanup sebelumnya di-revert penuh) — kondisi saat ini konsisten dengan temuan di bawah. Tujuan cleanup: bikin repo rapi, git history bersih ke depan, install/run gak rusak — tanpa hilangin kerjaan asli atau data penting (`data/peta_offline.mbtiles`).

---

## Struktur Repo (ringkas, hasil re-verifikasi)

```
BIMA-BASE-STATION/
├── app/                          # FastAPI backend
│   ├── main.py                   # entrypoint, mount /static, Jinja2Templates, GET / (legacy UI)
│   ├── config/settings.py        # Pydantic Settings — sumber kebenaran semua env var
│   ├── routers/{peta,system,telemetry,video}.py
│   ├── services/
│   │   ├── mavlink/{connection,interfaces,telemetry_bridge}.py
│   │   ├── telemetry/{generator,udp_telemetry}.py
│   │   ├── video/{manager,receiver}.py
│   │   ├── websocket/manager.py
│   │   └── yolo/detector.py
│   ├── static/, templates/index.html   # legacy vanilla-JS fallback UI, masih di-mount main.py
│   └── unduh_ubin_awal.py        # standalone, ORPHAN — gak direferensi file manapun
├── gcs-client/src/                # Next.js 15 frontend
│   ├── app/{layout,page,globals.css}
│   ├── components/{header,map,modal,telemetry,video}/...
│   ├── hooks/{useGCSStore.tsx,useWebSocket.ts}   # useGCSStore = React Context+useState, BUKAN Zustand
│   └── types/{telemetry.ts,video.ts}
├── data/peta_offline.mbtiles     # 38MB+, SQLite auto-cache tile — terus tumbuh saat dipakai, akan di-gitignore
├── logs/, snapshots/             # runtime output, tracked di git (harusnya di-ignore)
├── dump_trash/                   # junk drawer tracked di git: cekkk.jpg, drone.pt, simgeo.py, testmav.py
├── best.pt, yolo11n.pt, yolov8n.pt   # model weights tracked di git di root
├── bus.jpg, testcuda.py, testingcuda.py, git_diff.txt   # stray/junk tracked di git
├── requirements.txt              # missing Pillow, ada baris duplikat komentar ultralytics
├── .env.example                  # gak sinkron sama settings.py (kurang MAVLINK_*, YOLO_*)
├── README.md                     # klaim salah: "Zustand" di baris 31 & 95
└── [6 file markdown root: README, TECHNICAL_DOCUMENT, NEXTJS_MIGRATION_LLM_BRIEF,
     AI_DECISION_LAYER_AUDIT, gcs_programmer_brief, uav_programmer_brief_udpategps] — banyak overlap
```

`app/static/` + `app/templates/` **bukan dead code** — `main.py` baris 144 (`app.mount("/static", ...)`), 145 (`Jinja2Templates`), dan 184 (`GET /` render `index.html`) masih aktif jadi fallback UI lama, coexist sama Next.js.

`main.py` mount `router` (prefix `/ws`) dan `api_router` (prefix `/api/...`) terpisah per domain — ini **sengaja** (WebSocket vs REST split), bukan duplikasi, tidak perlu diapa-apain.

---

## Temuan & Rencana Perbaikan

> **Revisi (dari user, setelah draft pertama):**
> - `*.pt` **JANGAN** di-gitignore — model weight tetap perlu tracked biar gak ribet fetch manual (keputusan user, beda dari draft awal).
> - Klaim "Zustand" di README **BUKAN salah** — itu emang arsitektur yang dituju. Yang salah itu code-nya (`useGCSStore.tsx` masih pakai React Context, belum Zustand). Jadi bukan "perbaiki teks README", tapi **migrasi code React Context → Zustand** (lihat kategori D baru).
> - Poin A5 lama (commit `TECHNICAL_DOCUMENT.md` + `swarm_integration_audit_plan.md`) — sudah di-push user ke branch lain, dihapus dari plan ini.
>
> **Revisi kedua — `data/peta_offline.mbtiles` (setelah investigasi lebih lanjut):**
> Ternyata file ini **BUKAN data statis** — dia SQLite database yang terus nambah/berubah tiap kali user browsing area peta baru (`app/routers/peta.py`: `dapatkan_potongan_gambar_satelit()` → cache-miss → `unduh_ubin_satelit_eksternal()` download dari Esri → `simpan_ubin_satelit_ke_basis_data()` langsung `INSERT OR REPLACE` + `commit()` ke file itu juga). Jadi tiap kali main-map, file berubah (`modified` terus di `git status`) — commit ke git jadi berat & terus-menerus kalau tetap tracked.
>
> Keputusan baru (user pilih **opsi 2**): **`*.mbtiles` DI-GITIGNORE**, file tetap dipertahankan di disk masing-masing user, TIDAK didistribusikan lewat git. Alasan ini gak bertentangan sama kebutuhan "clone baru bisa load peta": app ini punya **auto-cache self-heal** built-in — begitu ada internet sekali, tile yang belum ada di database bakal otomatis di-download & disimpan sendiri (lihat alur di atas). Jadi clone baru TETAP bisa pakai peta normal asal ada koneksi internet minimal sekali; yang gak bisa didapat otomatis cuma "pre-seeded offline-ready dari detik pertama" — itu perlu dibagikan manual di luar git (USB/shared-drive/Tailscale file transfer), bukan lewat commit.
>
> **Verifikasi asal data (biar gak ragu):** Dicek langsung ke code — semua isi `data/peta_offline.mbtiles` 100% berasal dari server publik Esri World Imagery (`server.arcgisonline.com`), bukan data privat/manual. Seed awal di `app/unduh_ubin_awal.py:30-31` pakai koordinat hardcode `-7.7956, 110.3695`; tile tambahan di-fetch on-demand lewat `app/routers/peta.py:87-98`. Jadi datanya bisa di-generate ulang kapan aja asal ada internet — aman di-gitignore, gak ada yang hilang permanen.
>
> **⚠️ Catatan penting buat deployment lapangan:** Kalau file `.mbtiles` di laptop tertentu udah ke-cache tile buat lokasi terbang/survey yang SPESIFIK (bukan cuma area seed default), cache itu SEKARANG cuma ada di laptop itu — gak lagi otomatis kebagi ke rekan lain lewat `git clone` (karena di-gitignore). Kalau mau bawa tim ke lokasi survey yang sama dan di sana **gak ada internet sama sekali**, laptop yang belum punya cache buat area itu bakal cuma dapet placeholder abu-abu (`buat_gambar_ubin_pengganti`), bukan peta beneran. **Wajib**: sebelum berangkat ke lokasi tanpa internet, copy manual `data/peta_offline.mbtiles` dari laptop yang udah punya cache lengkap ke laptop-laptop tim lainnya (USB / shared-drive / Tailscale file transfer) — jangan andelin git buat distribusi ini.

### A. Aman dieksekusi langsung (additive / non-destruktif terhadap data)

| # | File | Masalah | Fix |
|---|---|---|---|
| 1 | `.gitignore` | Gak cover `logs/`, `snapshots/`, `dump_trash/`, `*.mbtiles` | Tambah pattern-pattern itu. `*.pt` sengaja TIDAK di-ignore (lihat revisi pertama); `*.mbtiles` SEKARANG di-ignore (lihat revisi kedua) |
| 2 | `requirements.txt` | `Pillow` hilang padahal `app/routers/peta.py` import `PIL` langsung → clean install rusak; ada baris duplikat komentar `ultralytics` | Tambah `Pillow`, hapus baris duplikat, perbaiki label "optional" di torch |
| 3 | `.env.example` | Gak ada `MAVLINK_HOSTS`, `MAVLINK_DEFAULT_PORT`, blok `YOLO_*` | Sinkronkan dengan `app/config/settings.py` |

### B. Butuh eksekusi git yang eksplisit dikonfirmasi user dulu

| # | Aksi | File | Catatan |
|---|---|---|---|
| 6 | `git rm --cached` (file tetap di disk) | `dump_trash/*`, `git_diff.txt`, `bus.jpg`, `testcuda.py`, `testingcuda.py`, `logs/ground_station.log(.1)` | Aman: gak direferensi app manapun, `logs/` dibuat ulang otomatis saat startup. `*.pt` TIDAK termasuk di sini — tetap tracked |
| 7 | `git rm --cached data/peta_offline.mbtiles` (file tetap di disk) | `data/peta_offline.mbtiles` | Lihat revisi kedua — file ini terus berubah tiap dipakai, gak cocok terus-menerus tracked di git. Setelah untrack, rekan yang belum punya data lokal perlu copy manual (bukan git) kalau butuh versi offline-ready langsung |

### C. Keputusan terbuka — ✅ SUDAH TERJAWAB

1. **`app/static/` + `app/templates/`** (fallback UI lama) — ✅ **Dieksekusi**. `app/static/` dan `app/templates/` dihapus, `app/main.py` udah dibersihin (import `StaticFiles`/`Jinja2Templates`/`time`, mount block, route `GET /` semua dicabut; `get_tailscale_ip()` dan `/api/config` tetap utuh). Diverifikasi manual: `/health` dan `/api/config` normal, `/` sekarang 404 (expected). Draft asli ada di `docs/fix/remove-legacy-static-ui.md`.
2. **`best.pt`** (6.2MB, gak ada referensi code) — ✅ **Tetap tracked**, no action.
3. **`yolov8n.pt`** — ✅ **Tetap tracked**, no action.
4. **`app/unduh_ubin_awal.py`** — ✅ **Dieksekusi**. Docstring diganti jadi dokumentasi CLI tool lengkap (cara pakai, tujuan preload lapangan). Logic inti gak berubah. Draft asli ada di `docs/fix/unduh-ubin-awal-cli-tool.md`.
5. **6 dokumen markdown root yang overlap** — ✅ **Selesai** (dikonfirmasi ulang: 5 file non-README udah dipindah ke `docs/` oleh user, `README.md` tetap di root).

### D. Migrasi kode — React Context → Zustand (belum dieksekusi, perlu konfirmasi scope dulu)

`gcs-client/src/hooks/useGCSStore.tsx` saat ini pakai `createContext` + `useState` + `useCallback` manual (`GCSProvider` wrap seluruh app di `layout.tsx`, konsumen panggil `useGCSStore()` via `useContext`). README/TECHNICAL_DOCUMENT menyebut Zustand sebagai arsitektur yang dituju — code perlu disesuaikan.

Langkah migrasi (draft, belum jalan):
1. `npm install zustand` di `gcs-client/` (`package.json` saat ini belum ada `zustand` sama sekali).
2. Rewrite `useGCSStore.tsx`: ganti `createContext`/`GCSProvider` jadi `create<GCSStore>()(...)` dari `zustand` — state + actions gabung dalam satu store, localStorage sync (`bima_gcs_uav_1/2`, `bima_gcs_configured`) tetap dipertahankan (bisa pakai `zustand/middleware persist` atau manual seperti sekarang).
3. Grep semua pemakai `useGCSStore()` / `GCSProvider` (`layout.tsx` dan semua komponen yang import dari `@/hooks/useGCSStore`) — pastikan API pemanggilan tetap kompatibel (Zustand hook dipanggil sama seperti custom hook, tapi tanpa perlu `<GCSProvider>` wrapper — `layout.tsx` perlu diubah untuk drop provider wrapper).
4. Hapus `GCSProvider` dari `layout.tsx` setelah migrasi (Zustand gak butuh context provider).
5. Test: `npm run dev`, jalanin golden path (config awal, connect UAV, toggle theme, toggle YOLO) — pastikan state persist ke localStorage tetap jalan sama seperti sebelumnya.

**Catatan:** ini refactor lintas-file (bukan quick fix), disarankan dieksekusi sebagai task tersendiri setelah kategori A/B/C selesai, bukan digabung ke "cleanup cepat".

---

## Verifikasi (setelah eksekusi nanti dilakukan)

- `pip install -r requirements.txt` di venv bersih → harus sukses tanpa `ModuleNotFoundError: PIL`.
- `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload` → jalan normal, `/health` return 200.
- `cd gcs-client && npm run dev` → jalan normal, gak kesentuh sama sekali (frontend gak diubah plan ini).
- `git status` → clean, cuma perubahan yang disengaja.
- `git log --stat` → commit baru gak nyertain file besar yang harusnya di-ignore.

---

## Urutan Eksekusi (kalau/ketika user minta lanjut)

1. Kategori A (item 1–5) — aman, additive.
2. Tanya user kategori C (5 poin) satu-satu.
3. Kategori B (`git rm --cached`) — baru jalan setelah user eksplisit bilang "lanjut"/"jalankan".
4. Commit (baru kalau user eksplisit minta commit — bukan otomatis setelah staging).
5. Jalankan verifikasi di atas.

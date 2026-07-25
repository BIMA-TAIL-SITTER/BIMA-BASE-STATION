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
├── data/peta_offline.mbtiles     # 38MB, DATA ASLI — bukan clutter
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

### A. Aman dieksekusi langsung (additive / non-destruktif terhadap data)

| # | File | Masalah | Fix |
|---|---|---|---|
| 1 | `.gitignore` | Gak cover `*.pt`, `logs/`, `*.mbtiles`, `snapshots/`, `dump_trash/` | Tambah pattern-pattern itu (mbtiles pattern gak lepas `data/peta_offline.mbtiles` yang udah tracked) |
| 2 | `requirements.txt` | `Pillow` hilang padahal `app/routers/peta.py` import `PIL` langsung → clean install rusak; ada baris duplikat komentar `ultralytics` | Tambah `Pillow`, hapus baris duplikat, perbaiki label "optional" di torch |
| 3 | `.env.example` | Gak ada `MAVLINK_HOSTS`, `MAVLINK_DEFAULT_PORT`, blok `YOLO_*` | Sinkronkan dengan `app/config/settings.py` |
| 4 | `README.md:31,95` | Klaim "Zustand" — implementasi asli `useGCSStore.tsx` pakai React Context+useState | Ganti teks jadi akurat |
| 5 | `TECHNICAL_DOCUMENT.md`, `swarm_integration_audit_plan.md` | Untracked, tapi dokumen yang memang diinginkan | `git add` (staging aja, commit nunggu izin eksplisit) |

### B. Butuh eksekusi git yang eksplisit dikonfirmasi user dulu

| # | Aksi | File | Catatan |
|---|---|---|---|
| 6 | `git rm --cached` (file tetap di disk) | `dump_trash/*`, `git_diff.txt`, `bus.jpg`, `testcuda.py`, `testingcuda.py`, `logs/ground_station.log(.1)` | Aman: gak direferensi app manapun, `logs/` dibuat ulang otomatis saat startup |

### C. Keputusan terbuka — JANGAN diasumsikan, tanya user satu-satu sebelum eksekusi

1. **`app/static/` + `app/templates/`** (fallback UI lama) — hapus (Next.js udah primary) atau simpan (fallback darurat)?
2. **`best.pt`** (6.2MB, gak ada referensi code, cuma disebut "custom trained model" di dokumen) — untrack-tapi-simpan-di-disk, atau hapus total?
3. **`yolov8n.pt`** — cuma dipakai stray script yang bakal dihapus di langkah B6. Aman dihapus total, tapi tetap konfirmasi.
4. **`app/unduh_ubin_awal.py`** — hapus (dead code, duplikat logic `unduh_ubin_satelit_eksternal` di `peta.py`) atau simpan sebagai CLI tool yang didokumentasikan?
5. **6 dokumen markdown root yang overlap** — konsolidasi ke folder `docs/` sekarang, atau ditunda?

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

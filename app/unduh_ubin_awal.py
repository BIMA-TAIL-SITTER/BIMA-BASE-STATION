"""
CLI Tool: Preload Ubin Satelit ke MBTiles Offline (Persiapan Deployment Lapangan)

Skrip standalone (BUKAN dipanggil otomatis oleh aplikasi) untuk mengunduh citra satelit
Esri World Imagery di sekitar satu koordinat pusat, lalu menyimpannya ke
`data/peta_offline.mbtiles`. Tujuannya: preload cache peta SEBELUM berangkat ke lokasi
survey/terbang, supaya operator lapangan tidak bergantung pada auto-download on-demand
milik `app/routers/peta.py` (yang butuh internet real-time saat drone terbang).

Cara pakai:
    1. Edit `posisi_lintang_pusat` dan `posisi_bujur_pusat` di bawah, sesuai koordinat
       pusat lokasi survey yang akan dituju.
    2. Jalankan dari root repo (pastikan working directory di root project, karena
       path `data/peta_offline.mbtiles` relatif terhadap cwd):
           python -m app.unduh_ubin_awal
       atau:
           python app/unduh_ubin_awal.py
    3. Skrip akan mengunduh ubin level zoom 13-14-15 dalam radius 2 ubin di sekeliling
       koordinat pusat, dan menyimpannya ke MBTiles lokal. Tile yang sudah ada di
       database (hasil pemakaian sebelumnya) otomatis dilewati (tidak diunduh ulang).
    4. Setelah selesai, salin `data/peta_offline.mbtiles` ke laptop lain di tim
       (USB / shared-drive / Tailscale file transfer) jika mereka juga akan bertugas
       di lokasi yang sama tanpa akses internet — lihat catatan distribusi cache di
       `docs/CLEANUP_PLAN.md`.

Catatan: file ini di-gitignore (lihat revisi kedua di `docs/CLEANUP_PLAN.md`) karena
isinya berubah terus tiap dipakai — jangan andalkan `git pull` untuk menyamakan cache
peta antar anggota tim.

Wajib menggunakan variabel deskriptif berbahasa Indonesia.
"""

import math
import os
import sqlite3
import urllib.request

JALUR_BERKAS_BASIS_DATA_MBTILES = "data/peta_offline.mbtiles"


def konversi_koordinat_ke_ubin(
    posisi_lintang: float, posisi_bujur: float, tingkat_pembesaran: int
):
    """Mengubah koordinat lintang dan bujur menjadi indeks ubin horizontal dan vertikal."""
    rasio_lintang = math.radians(posisi_lintang)
    jumlah_ubin = 2**tingkat_pembesaran
    indeks_horizontal = int((posisi_bujur + 180.0) / 360.0 * jumlah_ubin)
    indeks_vertikal = int(
        (1.0 - math.asinh(math.tan(rasio_lintang)) / math.pi) / 2.0 * jumlah_ubin
    )
    return indeks_horizontal, indeks_vertikal


def jalankan_pengunduhan_ubin_awal():
    """Mengunduh ubin satelit awal dan menyimpannya ke SQLite MBTiles."""
    posisi_lintang_pusat = -7.7956
    posisi_bujur_pusat = 110.3695

    koneksi_basis_data_mbtiles = sqlite3.connect(JALUR_BERKAS_BASIS_DATA_MBTILES)
    kursor_penyimpanan = koneksi_basis_data_mbtiles.cursor()
    kursor_penyimpanan.execute(
        "CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);"
    )
    kursor_penyimpanan.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row);"
    )

    jumlah_terunduh = 0

    for tingkat_pembesaran in [13, 14, 15]:
        indeks_horizontal_pusat, indeks_vertikal_pusat = konversi_koordinat_ke_ubin(
            posisi_lintang_pusat, posisi_bujur_pusat, tingkat_pembesaran
        )
        for selisih_horizontal in range(-2, 3):
            for selisih_vertikal in range(-2, 3):
                koordinat_horizontal = indeks_horizontal_pusat + selisih_horizontal
                koordinat_vertikal = indeks_vertikal_pusat + selisih_vertikal
                koordinat_vertikal_terbalik = (
                    (1 << tingkat_pembesaran) - 1 - koordinat_vertikal
                )

                # Periksa apakah sudah tersimpan
                kursor_penyimpanan.execute(
                    "SELECT 1 FROM tiles WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                    (
                        tingkat_pembesaran,
                        koordinat_horizontal,
                        koordinat_vertikal_terbalik,
                    ),
                )
                if kursor_penyimpanan.fetchone():
                    continue

                alamat_sumber_satelit = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{tingkat_pembesaran}/{koordinat_vertikal}/{koordinat_horizontal}"
                try:
                    permintaan_pengunduhan = urllib.request.Request(
                        alamat_sumber_satelit,
                        headers={"User-Agent": "BIMA-GroundStation-UAV/1.0"},
                    )
                    tanggapan_pengunduhan = urllib.request.urlopen(
                        permintaan_pengunduhan, timeout=4
                    )
                    data_gambar_unduhan = tanggapan_pengunduhan.read()
                    kursor_penyimpanan.execute(
                        "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                        (
                            tingkat_pembesaran,
                            koordinat_horizontal,
                            koordinat_vertikal_terbalik,
                            data_gambar_unduhan,
                        ),
                    )
                    koneksi_basis_data_mbtiles.commit()
                    jumlah_terunduh += 1
                except Exception:
                    pass

    koneksi_basis_data_mbtiles.close()
    print(f"Selesai mengunduh dan menyimpan {jumlah_terunduh} ubin satelit ke MBTiles.")


if __name__ == "__main__":
    jalankan_pengunduhan_ubin_awal()

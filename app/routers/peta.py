"""
Modul Pelayan Peta Satelit Offline (MBTiles SQLite Database)
Melayani potongan gambar satelit secara offline tanpa koneksi internet.
Dilengkapi pengunduhan otomatis dan penyimpanan ke basis data MBTiles jika ubin belum tersedia.
Wajib menggunakan nama variabel deskriptif berbahasa Indonesia.
"""

import io
import os
import sqlite3
import urllib.request
from fastapi import APIRouter, Response
from PIL import Image, ImageDraw

peta_router = APIRouter(prefix="/api/peta", tags=["Peta Offline"])

JALUR_BERKAS_BASIS_DATA_MBTILES = "data/peta_offline.mbtiles"


def siapkan_basis_data_contoh_jika_belum_ada():
    """Membuat direktori data dan basis data mbtiles contoh jika belum tersedia."""
    direktori_penyimpanan = os.path.dirname(JALUR_BERKAS_BASIS_DATA_MBTILES)
    if direktori_penyimpanan and not os.path.exists(direktori_penyimpanan):
        os.makedirs(direktori_penyimpanan, exist_ok=True)

    koneksi_basis_data = sqlite3.connect(JALUR_BERKAS_BASIS_DATA_MBTILES)
    kursor_basis_data = koneksi_basis_data.cursor()
    kursor_basis_data.execute(
        "CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);"
    )
    kursor_basis_data.execute(
        "CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT);"
    )
    kursor_basis_data.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS tile_index ON tiles (zoom_level, tile_column, tile_row);"
    )
    koneksi_basis_data.commit()
    koneksi_basis_data.close()


siapkan_basis_data_contoh_jika_belum_ada()


def buat_gambar_ubin_pengganti(
    tingkat_pembesaran: int, koordinat_horizontal: int, koordinat_vertikal: int
) -> bytes:
    """Membuat gambar ubin satelit gelap grid offline sebagai cadangan jika ubin belum tersimpan di basis data."""
    gambar_ubin = Image.new("RGB", (256, 256), color=(18, 24, 32))
    pelukis_gambar = ImageDraw.Draw(gambar_ubin)
    pelukis_gambar.rectangle([0, 0, 255, 255], outline=(35, 48, 64), width=1)
    teks_koordinat = f"Z:{tingkat_pembesaran} X:{koordinat_horizontal} Y:{koordinat_vertikal}"
    pelukis_gambar.text((20, 120), teks_koordinat, fill=(80, 110, 140))
    penyangga_byte = io.BytesIO()
    gambar_ubin.save(penyangga_byte, format="PNG")
    return penyangga_byte.getvalue()


def simpan_ubin_satelit_ke_basis_data(
    tingkat_pembesaran: int,
    koordinat_horizontal: int,
    koordinat_vertikal_terbalik: int,
    data_gambar_ubin: bytes,
):
    """Menyimpan potongan gambar satelit ke basis data SQLite MBTiles lokal."""
    try:
        koneksi_basis_data_mbtiles = sqlite3.connect(JALUR_BERKAS_BASIS_DATA_MBTILES)
        kursor_penyimpanan = koneksi_basis_data_mbtiles.cursor()
        perintah_simpan = """
            INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data)
            VALUES (?, ?, ?, ?)
        """
        kursor_penyimpanan.execute(
            perintah_simpan,
            (
                tingkat_pembesaran,
                koordinat_horizontal,
                koordinat_vertikal_terbalik,
                data_gambar_ubin,
            ),
        )
        koneksi_basis_data_mbtiles.commit()
        koneksi_basis_data_mbtiles.close()
    except Exception:
        pass


def unduh_ubin_satelit_eksternal(
    tingkat_pembesaran: int, koordinat_horizontal: int, koordinat_vertikal: int
) -> bytes:
    """Mengunduh ubin satelit resolusi tinggi dari peladen satelit Esri World Imagery dan menyimpannya secara offline."""
    alamat_sumber_satelit = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{tingkat_pembesaran}/{koordinat_vertikal}/{koordinat_horizontal}"
    permintaan_pengunduhan = urllib.request.Request(
        alamat_sumber_satelit,
        headers={"User-Agent": "BIMA-GroundStation-UAV/1.0"},
    )
    tanggapan_pengunduhan = urllib.request.urlopen(permintaan_pengunduhan, timeout=4)
    data_gambar_unduhan = tanggapan_pengunduhan.read()
    return data_gambar_unduhan


@peta_router.get("/ubin/{tingkat_pembesaran}/{koordinat_horizontal}/{koordinat_vertikal}.png")
def dapatkan_potongan_gambar_satelit(
    tingkat_pembesaran: int,
    koordinat_horizontal: int,
    koordinat_vertikal: int,
):
    """
    Membaca basis data SQLite MBTiles dan melayani permintaan potongan gambar satelit offline.
    Melakukan kalkulasi pembalikan sumbu vertikal (MBTiles Y-axis inversion).
    Jika ubin belum ada, otomatis mengunduh, menyimpan ke MBTiles, dan melayaninya.
    """
    koordinat_vertikal_terbalik = (1 << tingkat_pembesaran) - 1 - koordinat_vertikal

    try:
        koneksi_basis_data_mbtiles = sqlite3.connect(JALUR_BERKAS_BASIS_DATA_MBTILES)
        kursor_kueri_basis_data = koneksi_basis_data_mbtiles.cursor()

        perintah_kueri_satelit = """
            SELECT tile_data
            FROM tiles
            WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?
        """

        kursor_kueri_basis_data.execute(
            perintah_kueri_satelit,
            (tingkat_pembesaran, koordinat_horizontal, koordinat_vertikal_terbalik),
        )
        baris_hasil_kueri = kursor_kueri_basis_data.fetchone()
        koneksi_basis_data_mbtiles.close()

        if baris_hasil_kueri and baris_hasil_kueri[0]:
            data_ubin_satelit = baris_hasil_kueri[0]
            return Response(content=data_ubin_satelit, media_type="image/png")
    except Exception:
        pass

    try:
        data_ubin_satelit_baru = unduh_ubin_satelit_eksternal(
            tingkat_pembesaran, koordinat_horizontal, koordinat_vertikal
        )
        simpan_ubin_satelit_ke_basis_data(
            tingkat_pembesaran,
            koordinat_horizontal,
            koordinat_vertikal_terbalik,
            data_ubin_satelit_baru,
        )
        return Response(content=data_ubin_satelit_baru, media_type="image/png")
    except Exception:
        data_gambar_pengganti = buat_gambar_ubin_pengganti(
            tingkat_pembesaran, koordinat_horizontal, koordinat_vertikal
        )
        return Response(content=data_gambar_pengganti, media_type="image/png")

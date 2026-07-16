"use client";

import React, { useEffect, useState } from "react";
import "leaflet/dist/leaflet.css";

interface PropertiPetaOfflineUav {
  data_telemetri_pesawat_pertama: {
    lintang: number | null;
    bujur: number | null;
    arah_hadap: number;
    ketinggian: number;
    jumlah_satelit?: number;
    hdop?: number;
  } | null;
  data_telemetri_pesawat_kedua: {
    lintang: number | null;
    bujur: number | null;
    arah_hadap: number;
    ketinggian: number;
    jumlah_satelit?: number;
    hdop?: number;
  } | null;
}

export default function PetaOfflineUav({
  data_telemetri_pesawat_pertama,
  data_telemetri_pesawat_kedua,
}: PropertiPetaOfflineUav) {
  const [komponen_peta_siap, atur_status_komponen_peta_siap] = useState(false);

  useEffect(() => {
    atur_status_komponen_peta_siap(true);
  }, []);

  if (!komponen_peta_siap) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-[#090A0C] border border-[#1A1D28] rounded-lg text-[#C8CAD4] text-xs">
        Memuat Peta Satelit Offline...
      </div>
    );
  }

  // Mengimpor secara dinamis komponen Leaflet setelah di peramban
  const pustaka_react_leaflet = require("react-leaflet");
  const pustaka_leaflet = require("leaflet");

  const KomainerPeta = pustaka_react_leaflet.MapContainer;
  const LapisanUbinPeta = pustaka_react_leaflet.TileLayer;
  const PenandaPeta = pustaka_react_leaflet.Marker;

  const alamat_peladen_ubin_satelit = "http://localhost:8000/api/peta/ubin/{z}/{x}/{y}.png";

  const posisi_lintang_default = -7.7956; // Yogyakarta (Jogja)
  const posisi_bujur_default = 110.3695;

  const posisi_lintang_pertama =
    data_telemetri_pesawat_pertama?.lintang ?? posisi_lintang_default;
  const posisi_bujur_pertama =
    data_telemetri_pesawat_pertama?.bujur ?? posisi_bujur_default;
  const arah_hadap_pertama = data_telemetri_pesawat_pertama?.arah_hadap ?? 0;

  const posisi_lintang_kedua =
    data_telemetri_pesawat_kedua?.lintang ?? (posisi_lintang_default + 0.003);
  const posisi_bujur_kedua =
    data_telemetri_pesawat_kedua?.bujur ?? (posisi_bujur_default + 0.003);
  const arah_hadap_kedua = data_telemetri_pesawat_kedua?.arah_hadap ?? 45;

  const tampilan_satelit_pertama =
    data_telemetri_pesawat_pertama?.jumlah_satelit !== undefined
      ? `${data_telemetri_pesawat_pertama.jumlah_satelit}`
      : "--";
  const tampilan_hdop_pertama =
    data_telemetri_pesawat_pertama?.hdop !== undefined
      ? data_telemetri_pesawat_pertama.hdop.toFixed(2)
      : "--";

  const tampilan_satelit_kedua =
    data_telemetri_pesawat_kedua?.jumlah_satelit !== undefined
      ? `${data_telemetri_pesawat_kedua.jumlah_satelit}`
      : "--";
  const tampilan_hdop_kedua =
    data_telemetri_pesawat_kedua?.hdop !== undefined
      ? data_telemetri_pesawat_kedua.hdop.toFixed(2)
      : "--";

  const buat_ikon_pesawat_sayap_tetap = (
    sudut_arah_hadap: number,
    kode_warna_pesawat: string,
    label_pesawat: string
  ) => {
    const kode_sumber_svg = `
      <div style="transform: rotate(${sudut_arah_hadap}deg); display: flex; flex-direction: column; align-items: center;">
        <svg width="40" height="40" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
          <path d="M50 5 L55 35 L95 48 L95 56 L55 48 L53 80 L68 88 L68 94 L50 89 L32 94 L32 88 L47 80 L45 48 L5 56 L5 48 L45 35 Z"
                fill="${kode_warna_pesawat}" stroke="#090A0C" stroke-width="4"/>
        </svg>
      </div>
      <div style="background: rgba(9,10,12,0.85); color: ${kode_warna_pesawat}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; border: 1px solid ${kode_warna_pesawat}; margin-top: -4px; white-space: nowrap;">
        ${label_pesawat} (${Math.round(sudut_arah_hadap)}°)
      </div>
    `;

    return pustaka_leaflet.divIcon({
      className: "ikon-pesawat-kustom",
      html: kode_sumber_svg,
      iconSize: [40, 56],
      iconAnchor: [20, 20],
    });
  };

  const ikon_pesawat_sayap_tetap_pertama = buat_ikon_pesawat_sayap_tetap(
    arah_hadap_pertama,
    "#D5FF40",
    "UAV 01"
  );
  const ikon_pesawat_sayap_tetap_kedua = buat_ikon_pesawat_sayap_tetap(
    arah_hadap_kedua,
    "#34D87A",
    "UAV 02"
  );

  return (
    <div className="w-full h-full relative overflow-hidden rounded-lg border border-[#1A1D28] shadow-2xl bg-[#090A0C]">
      <KomainerPeta
        center={[posisi_lintang_pertama, posisi_bujur_pertama]}
        zoom={14}
        style={{ width: "100%", height: "100%" }}
        zoomControl={false}
      >
        <LapisanUbinPeta
          url={alamat_peladen_ubin_satelit}
          maxZoom={19}
          attribution="Peta Offline MBTiles GCS"
        />
        <PenandaPeta
          position={[posisi_lintang_pertama, posisi_bujur_pertama]}
          icon={ikon_pesawat_sayap_tetap_pertama}
        />
        <PenandaPeta
          position={[posisi_lintang_kedua, posisi_bujur_kedua]}
          icon={ikon_pesawat_sayap_tetap_kedua}
        />
      </KomainerPeta>

      {/* Teks mengambang status GPS UAV 1 di KIRI ATAS peta tanpa kotak */}
      <div className="absolute top-3 left-3 z-[1000] select-none pointer-events-none flex flex-col font-mono text-xs drop-shadow-[0_2px_4px_rgba(0,0,0,0.95)]">
        <div className="font-bold text-[#D5FF40] tracking-wide">UAV 01 GPS DATA</div>
        <div className="text-white font-semibold mt-0.5 tracking-wider">
          SAT: {tampilan_satelit_pertama} &nbsp;&nbsp; HDOP: {tampilan_hdop_pertama}
        </div>
      </div>

      {/* Teks mengambang status GPS UAV 2 di KIRI BAWAH peta tanpa kotak */}
      <div className="absolute bottom-3 left-3 z-[1000] select-none pointer-events-none flex flex-col font-mono text-xs drop-shadow-[0_2px_4px_rgba(0,0,0,0.95)]">
        <div className="font-bold text-[#34D87A] tracking-wide">UAV 02 GPS DATA</div>
        <div className="text-white font-semibold mt-0.5 tracking-wider">
          SAT: {tampilan_satelit_kedua} &nbsp;&nbsp; HDOP: {tampilan_hdop_kedua}
        </div>
      </div>

      {/* Panel status peta offline di pojok kanan atas */}
      <div className="absolute top-3 right-3 z-[1000] bg-[#12141B]/90 backdrop-blur border border-[#1A1D28] rounded px-3 py-1.5 flex items-center gap-2 text-[11px] text-[#D5FF40]">
        <span className="w-2 h-2 rounded-full bg-[#34D87A] animate-pulse" />
        <span className="font-bold">PETA SATELIT OFFLINE (MBTILES)</span>
      </div>
    </div>
  );
}

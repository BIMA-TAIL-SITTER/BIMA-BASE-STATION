"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { GCSProvider, useGCSStore } from "@/hooks/useGCSStore";
import TopBar from "@/components/header/TopBar";
import ConnectionSetupModal from "@/components/modal/ConnectionSetupModal";
import EditConnectionModal from "@/components/modal/EditConnectionModal";
import VideoPanel from "@/components/video/VideoPanel";
import { MavlinkHeader } from "@/components/telemetry/MavlinkHeader";
import { AttitudeIndicator } from "@/components/telemetry/AttitudeIndicator";
import { TelemetryStats } from "@/components/telemetry/TelemetryStats";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { TelemetryData, MavlinkStatus } from "@/types/telemetry";
import dynamic from "next/dynamic";

const PetaOfflineUav = dynamic(() => import("@/components/map/PetaOfflineUav"), {
  ssr: false,
});

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

function GCSDashboard() {
  const { config, setConfig, isConfigured, uav1, uav2, theme } = useGCSStore();

  // Telemetry state per UAV
  const [telem1, setTelem1] = useState<TelemetryData | null>(null);
  const [telem2, setTelem2] = useState<TelemetryData | null>(null);
  const [mavStatus1, setMavStatus1] = useState<MavlinkStatus>("DISCONNECTED");
  const [mavStatus2, setMavStatus2] = useState<MavlinkStatus>("DISCONNECTED");

  // Attitude values — use refs + rAF for smooth 30Hz SVG updates without re-render flood
  const attitude1 = useRef({ roll: 0, pitch: 0, heading: 0, altitude: 0 });
  const attitude2 = useRef({ roll: 0, pitch: 0, heading: 0, altitude: 0 });
  const [att1, setAtt1] = useState({ roll: 0, pitch: 0, heading: 0, altitude: 0 });
  const [att2, setAtt2] = useState({ roll: 0, pitch: 0, heading: 0, altitude: 0 });

  // Throttled attitude update at ~30fps
  const rafRef = useRef<number>(0);
  useEffect(() => {
    let lastTime = 0;
    const update = (time: number) => {
      if (time - lastTime >= 33) {
        setAtt1({ ...attitude1.current });
        setAtt2({ ...attitude2.current });
        lastTime = time;
      }
      rafRef.current = requestAnimationFrame(update);
    };
    rafRef.current = requestAnimationFrame(update);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  const [udpTarget1, setUdpTarget1] = useState({ detected: false, lat: "--", lon: "--", dist: "--", gsd: "--" });
  const [udpTarget2, setUdpTarget2] = useState({ detected: false, lat: "--", lon: "--", dist: "--", gsd: "--" });

  // Resizable Splitter State
  const [lebarKolomKiriPersen, setLebarKolomKiriPersen] = useState<number>(53);
  const isDraggingSplitter = useRef<boolean>(false);

  const handleMouseDownSplitter = useCallback(() => {
    isDraggingSplitter.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingSplitter.current) return;
      const persentaseBaru = (e.clientX / window.innerWidth) * 100;
      if (persentaseBaru >= 25 && persentaseBaru <= 78) {
        setLebarKolomKiriPersen(persentaseBaru);
        window.dispatchEvent(new Event("resize"));
      }
    };
    const handleMouseUp = () => {
      if (isDraggingSplitter.current) {
        isDraggingSplitter.current = false;
        document.body.style.cursor = "default";
        document.body.style.userSelect = "auto";
        window.dispatchEvent(new Event("resize"));
      }
    };
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  // Timeout detection
  const lastUpdate = useRef({ 1: 0, 2: 0 });
  useEffect(() => {
    const iv = setInterval(() => {
      const now = Date.now();
      if (now - lastUpdate.current[1] > 3000) setMavStatus1("DISCONNECTED");
      if (now - lastUpdate.current[2] > 3000) setMavStatus2("DISCONNECTED");
    }, 1000);
    return () => clearInterval(iv);
  }, []);

  // Fetch server config on mount
  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then((r) => r.json())
      .then((data) => setConfig(data))
      .catch(console.error);
  }, [setConfig]);

  // Telemetry WebSocket
  const wsHost = config?.ws_host;
  const telemUrl = isConfigured && wsHost ? `ws://${wsHost}/ws/telemetry` : "";

  const onTelemMessage = useCallback((data: string) => {
    try {
      const t: TelemetryData = JSON.parse(data);
      const slot = t.slot || 1;
      lastUpdate.current[slot] = Date.now();

      if (slot === 1) {
        setTelem1(t);
        if (t.armed !== undefined) setMavStatus1(t.armed ? "ARMED" : "DISARMED");
        if (t.roll_deg !== undefined) attitude1.current.roll = t.roll_deg;
        if (t.pitch_deg !== undefined) attitude1.current.pitch = t.pitch_deg;
        if (t.heading_deg !== undefined) attitude1.current.heading = t.heading_deg;
        if (t.altitude_m !== undefined) attitude1.current.altitude = t.altitude_m;
      } else {
        setTelem2(t);
        if (t.armed !== undefined) setMavStatus2(t.armed ? "ARMED" : "DISARMED");
        if (t.roll_deg !== undefined) attitude2.current.roll = t.roll_deg;
        if (t.pitch_deg !== undefined) attitude2.current.pitch = t.pitch_deg;
        if (t.heading_deg !== undefined) attitude2.current.heading = t.heading_deg;
        if (t.altitude_m !== undefined) attitude2.current.altitude = t.altitude_m;
      }
    } catch {
      // ignore
    }
  }, []);

  useWebSocket({ url: telemUrl, onMessage: onTelemMessage, enabled: !!telemUrl });

  // Auto-connect MAVLink sources after configuration
  useEffect(() => {
    if (!isConfigured) return;
    const connectUAV = async (uavId: 1 | 2) => {
      const cfg = uavId === 1 ? uav1 : uav2;
      if (!cfg?.tcpIp || !cfg?.mavlinkPort) return;
      try {
        await fetch(`${API_BASE}/api/telemetry/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            slot: uavId,
            ip: cfg.tcpIp,
            port: parseInt(cfg.mavlinkPort, 10),
          }),
        });
        console.log(`[telemetry] Connected slot ${uavId} to ${cfg.tcpIp}:${cfg.mavlinkPort}`);
      } catch (e) {
        console.error(`[telemetry] Failed to connect slot ${uavId}:`, e);
      }
    };
    const timer = setTimeout(() => {
      connectUAV(1);
      connectUAV(2);
    }, 800);
    return () => clearTimeout(timer);
  }, [isConfigured, uav1, uav2]);

  // Apply theme
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  // If not configured, show modal
  if (!isConfigured) {
    return <ConnectionSetupModal />;
  }

  return (
    <>
      <TopBar />
      <main
        id="main-content-peta"
        style={{ gridTemplateColumns: `${lebarKolomKiriPersen}% 8px minmax(0, 1fr)` }}
      >
        {/* Kolom Kiri: Pemantauan UAV 1 (Atas) dan UAV 2 (Bawah) */}
        <div className="kolom-monitoring-kiri">
          {/* Baris Atas: UAV 1 */}
          <div className="baris-pesawat-monitoring">
            <VideoPanel panelId={1} />
            <div className="telem-panel" id="telem-panel-1">
              <MavlinkHeader panelId={1} mavlinkStatus={mavStatus1} />
              <AttitudeIndicator
                roll={att1.roll}
                pitch={att1.pitch}
                heading={att1.heading}
                altitude={att1.altitude}
                panelId={1}
              />
              <TelemetryStats
                telemetry={telem1}
                mavlinkStatus={mavStatus1}
                panelId={1}
                udpTarget={udpTarget1}
              />
            </div>
          </div>

          {/* Baris Bawah: UAV 2 */}
          <div className="baris-pesawat-monitoring">
            <VideoPanel panelId={2} />
            <div className="telem-panel" id="telem-panel-2">
              <MavlinkHeader panelId={2} mavlinkStatus={mavStatus2} />
              <AttitudeIndicator
                roll={att2.roll}
                pitch={att2.pitch}
                heading={att2.heading}
                altitude={att2.altitude}
                panelId={2}
              />
              <TelemetryStats
                telemetry={telem2}
                mavlinkStatus={mavStatus2}
                panelId={2}
                udpTarget={udpTarget2}
              />
            </div>
          </div>
        </div>

        {/* Sekat Pembatas Tengah yang Dapat Digeser (Draggable Splitter) */}
        <div
          className="w-full h-full cursor-col-resize flex items-center justify-center group hover:bg-[#D5FF40]/15 transition-colors rounded select-none z-50"
          onMouseDown={handleMouseDownSplitter}
          title="Geser Kanan/Kiri untuk Mengubah Lebar Layar"
        >
          <div className="w-1.5 h-16 rounded-full bg-[#2E3344] group-hover:bg-[#D5FF40] group-hover:shadow-[0_0_8px_#D5FF40] transition-all" />
        </div>

        {/* Kolom Kanan: Peta Offline Interaktif */}
        <div className="kolom-peta-kanan">
          <PetaOfflineUav
            data_telemetri_pesawat_pertama={{
              lintang: telem1?.lat ?? null,
              bujur: telem1?.lon ?? null,
              arah_hadap: att1.heading,
              ketinggian: att1.altitude,
              jumlah_satelit: telem1?.satellites_visible,
              hdop: telem1?.hdop,
            }}
            data_telemetri_pesawat_kedua={{
              lintang: telem2?.lat ?? null,
              bujur: telem2?.lon ?? null,
              arah_hadap: att2.heading,
              ketinggian: att2.altitude,
              jumlah_satelit: telem2?.satellites_visible,
              hdop: telem2?.hdop,
            }}
          />
        </div>
      </main>
      <EditConnectionModal />
    </>
  );
}

export default function Home() {
  return (
    <GCSProvider>
      <GCSDashboard />
    </GCSProvider>
  );
}

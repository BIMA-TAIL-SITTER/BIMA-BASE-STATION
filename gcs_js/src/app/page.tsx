"use client";

import dynamic from "next/dynamic";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { UAV_IDS } from "@/config/agents";
import ConnectionSetupModal from "@/components/modal/ConnectionSetupModal";
import { CopterTelemetryPanel } from "@/components/telemetry/CopterTelemetryPanel";
import { MavlinkHeader } from "@/components/telemetry/MavlinkHeader";
import { TelemetryStats } from "@/components/telemetry/TelemetryStats";
import VideoPanel from "@/components/video/VideoPanel";
import { useGCSStore } from "@/hooks/useGCSStore";
import { useWebSocket } from "@/hooks/useWebSocket";
import type {
  MavlinkStatus,
  TelemetryData,
  UAVId,
  UAVRecord,
} from "@/types/telemetry";

const PetaOfflineUav = dynamic(() => import("@/components/map/PetaOfflineUav"), {
  ssr: false,
});

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SPLITTER_WIDTH = 8;
const DASHBOARD_COLUMN_GAP = 12;
const DASHBOARD_SPLITTER_COUNT = 2;
const DASHBOARD_COLUMN_GAP_COUNT = 4;
const MIN_RIGHT_COLUMN_WIDTH = 248;
const MAX_RIGHT_COLUMN_WIDTH = 520;
const DEFAULT_RIGHT_COLUMN_MAX_WIDTH = 400;

const EMPTY_TELEMETRY: UAVRecord<TelemetryData | null> = {
  1: null,
  2: null,
  3: null,
  4: null,
};
const DISCONNECTED_STATUSES: UAVRecord<MavlinkStatus> = {
  1: "DISCONNECTED",
  2: "DISCONNECTED",
  3: "DISCONNECTED",
  4: "DISCONNECTED",
};

function getDashboardMeasurements() {
  const mainContent = document.getElementById("main-content-peta");
  if (!mainContent) return null;

  const rect = mainContent.getBoundingClientRect();
  const styles = window.getComputedStyle(mainContent);
  const paddingLeft = Number.parseFloat(styles.paddingLeft) || 0;
  const paddingRight = Number.parseFloat(styles.paddingRight) || 0;
  const contentWidth = rect.width - paddingLeft - paddingRight;
  const mapMinimumWidth = Math.min(520, Math.max(340, contentWidth * 0.28));
  const layoutChromeWidth =
    SPLITTER_WIDTH * DASHBOARD_SPLITTER_COUNT
    + DASHBOARD_COLUMN_GAP * DASHBOARD_COLUMN_GAP_COUNT;

  return {
    rect,
    paddingLeft,
    contentWidth,
    mapMinimumWidth,
    layoutChromeWidth,
  };
}

interface MonitoringRowProps {
  children: ReactNode;
  onCardWidthChange?: (width: number) => void;
}

function MonitoringRow({ children, onCardWidthChange }: MonitoringRowProps) {
  const rowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const row = rowRef.current;
    const videoFrame = row?.querySelector<HTMLElement>(".video-frame");
    const videoSelector = row?.querySelector<HTMLElement>(".video-panel > .cam-selector");
    const telemetryPanel = row?.querySelector<HTMLElement>(".telem-panel");
    if (!row || !videoFrame || !videoSelector || !telemetryPanel) return;

    const syncCardWidth = () => {
      onCardWidthChange?.(row.getBoundingClientRect().width);
    };

    const resizeObserver = new ResizeObserver(syncCardWidth);
    resizeObserver.observe(row);
    resizeObserver.observe(videoFrame);
    syncCardWidth();

    return () => resizeObserver.disconnect();
  }, [onCardWidthChange]);

  return (
    <div ref={rowRef} className="baris-pesawat-monitoring">
      {children}
    </div>
  );
}

function GCSDashboard() {
  const { config, setConfig, isConfigured, uavs } = useGCSStore();
  const [telemetry, setTelemetry] = useState<UAVRecord<TelemetryData | null>>(
    EMPTY_TELEMETRY,
  );
  const [mavlinkStatuses, setMavlinkStatuses] = useState<UAVRecord<MavlinkStatus>>(
    DISCONNECTED_STATUSES,
  );
  const [udpTarget1, setUdpTarget1] = useState({
    detected: false,
    lat: "--",
    lon: "--",
    dist: "--",
    gsd: "--",
  });
  const [udpTarget2, setUdpTarget2] = useState({
    detected: false,
    lat: "--",
    lon: "--",
    dist: "--",
    gsd: "--",
  });

  const [leftColumnPercent, setLeftColumnPercent] = useState(24);
  const [rightColumnWidth, setRightColumnWidth] = useState<number | null>(null);
  const [measuredRightColumnWidth, setMeasuredRightColumnWidth] = useState(384);
  const activeSplitter = useRef<"left" | "right" | null>(null);
  const rightSplitterDragStart = useRef({ pointerX: 0, width: 384 });
  const initialSplitterPositionSet = useRef(false);
  const minimumLeftPercent = useRef(10);
  const lastUpdate = useRef<UAVRecord<number>>({ 1: 0, 2: 0, 3: 0, 4: 0 });

  const handleInitialCardWidth = useCallback((cardWidth: number) => {
    if (initialSplitterPositionSet.current || window.innerWidth <= 900) return;

    const measurements = getDashboardMeasurements();
    if (!measurements) return;

    const {
      contentWidth,
      mapMinimumWidth,
      layoutChromeWidth,
    } = measurements;
    const rightPanel = document.querySelector<HTMLElement>(".kolom-monitoring-kanan");
    const rightPanelWidth = rightPanel?.getBoundingClientRect().width
      ?? Math.min(
        DEFAULT_RIGHT_COLUMN_MAX_WIDTH,
        Math.max(MIN_RIGHT_COLUMN_WIDTH, window.innerWidth * 0.2),
      );
    setMeasuredRightColumnWidth(Math.round(rightPanelWidth));
    const minimumWidth = contentWidth * 0.1;
    const maximumWidth = Math.max(
      minimumWidth,
      contentWidth - layoutChromeWidth - rightPanelWidth - mapMinimumWidth,
    );
    const laptopMinimum = window.innerWidth <= 1600
      ? Math.min(300, Math.max(230, contentWidth * 0.18))
      : 0;
    const defaultWidth = Math.min(
      maximumWidth,
      Math.max(minimumWidth, laptopMinimum, cardWidth),
    );
    const defaultPercent = (defaultWidth / contentWidth) * 100;

    minimumLeftPercent.current = defaultPercent;
    initialSplitterPositionSet.current = true;
    setLeftColumnPercent(defaultPercent);
    window.dispatchEvent(new Event("resize"));
  }, []);

  const handleMouseDownSplitter = useCallback(() => {
    activeSplitter.current = "left";
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  const handleMouseDownCopterSplitter = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const rightPanel = document.querySelector<HTMLElement>(".kolom-monitoring-kanan");
      if (!rightPanel) return;

      activeSplitter.current = "right";
      rightSplitterDragStart.current = {
        pointerX: event.clientX,
        width: rightPanel.getBoundingClientRect().width,
      };
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
      event.preventDefault();
    },
    [],
  );

  const handleCopterSplitterKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;

      const measurements = getDashboardMeasurements();
      const leftPanel = document.querySelector<HTMLElement>(".kolom-monitoring-kiri");
      const rightPanel = document.querySelector<HTMLElement>(".kolom-monitoring-kanan");
      if (!measurements || !leftPanel || !rightPanel) return;

      const maximumWidth = Math.min(
        MAX_RIGHT_COLUMN_WIDTH,
        Math.max(
          MIN_RIGHT_COLUMN_WIDTH,
          measurements.contentWidth
            - measurements.layoutChromeWidth
            - leftPanel.getBoundingClientRect().width
            - measurements.mapMinimumWidth,
        ),
      );
      const step = event.shiftKey ? 32 : 16;
      const direction = event.key === "ArrowLeft" ? 1 : -1;
      const requestedWidth = rightPanel.getBoundingClientRect().width + step * direction;
      const constrainedWidth = Math.min(
        maximumWidth,
        Math.max(MIN_RIGHT_COLUMN_WIDTH, requestedWidth),
      );

      setRightColumnWidth(constrainedWidth);
      setMeasuredRightColumnWidth(Math.round(constrainedWidth));
      window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
      event.preventDefault();
    },
    [],
  );

  useEffect(() => {
    const handleMouseMove = (event: MouseEvent) => {
      const splitter = activeSplitter.current;
      if (!splitter) return;

      const measurements = getDashboardMeasurements();
      const leftPanel = document.querySelector<HTMLElement>(".kolom-monitoring-kiri");
      const rightPanel = document.querySelector<HTMLElement>(".kolom-monitoring-kanan");
      if (!measurements || !leftPanel || !rightPanel) return;

      if (splitter === "left") {
        const minimumWidth =
          measurements.contentWidth * (minimumLeftPercent.current / 100);
        const maximumWidth = Math.max(
          minimumWidth,
          measurements.contentWidth
            - measurements.layoutChromeWidth
            - rightPanel.getBoundingClientRect().width
            - measurements.mapMinimumWidth,
        );
        const requestedWidth =
          event.clientX - (measurements.rect.left + measurements.paddingLeft);
        const constrainedWidth = Math.min(
          maximumWidth,
          Math.max(minimumWidth, requestedWidth),
        );

        setLeftColumnPercent(
          (constrainedWidth / measurements.contentWidth) * 100,
        );
      } else {
        const maximumWidth = Math.min(
          MAX_RIGHT_COLUMN_WIDTH,
          Math.max(
            MIN_RIGHT_COLUMN_WIDTH,
            measurements.contentWidth
              - measurements.layoutChromeWidth
              - leftPanel.getBoundingClientRect().width
              - measurements.mapMinimumWidth,
          ),
        );
        const requestedWidth =
          rightSplitterDragStart.current.width
          - (event.clientX - rightSplitterDragStart.current.pointerX);
        const constrainedWidth = Math.min(
          maximumWidth,
          Math.max(MIN_RIGHT_COLUMN_WIDTH, requestedWidth),
        );

        setRightColumnWidth(constrainedWidth);
        setMeasuredRightColumnWidth(Math.round(constrainedWidth));
      }

      window.dispatchEvent(new Event("resize"));
    };

    const handleMouseUp = () => {
      if (!activeSplitter.current) return;
      activeSplitter.current = null;
      document.body.style.cursor = "default";
      document.body.style.userSelect = "auto";
      window.dispatchEvent(new Event("resize"));
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
      document.body.style.removeProperty("cursor");
      document.body.style.removeProperty("user-select");
    };
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      const now = Date.now();
      setMavlinkStatuses((current) => {
        let changed = false;
        const next = { ...current };
        for (const uavId of UAV_IDS) {
          if (
            now - lastUpdate.current[uavId] > 3000
            && current[uavId] !== "DISCONNECTED"
          ) {
            next[uavId] = "DISCONNECTED";
            changed = true;
          }
        }
        return changed ? next : current;
      });
    }, 1000);
    return () => window.clearInterval(interval);
  }, []);

  useEffect(() => {
    fetch(`${API_BASE}/api/config`)
      .then((response) => response.json())
      .then((data) => setConfig(data))
      .catch((error) => console.error("[config] Failed to load server config:", error));
  }, [setConfig]);

  const wsHost = config?.ws_host;
  const telemetryUrl = isConfigured && wsHost ? `ws://${wsHost}/ws/telemetry` : "";

  const onTelemetryMessage = useCallback((data: string) => {
    try {
      const packet = JSON.parse(data) as TelemetryData;
      const slot = packet.slot;
      if (!UAV_IDS.includes(slot)) return;

      lastUpdate.current[slot] = Date.now();
      setTelemetry((current) => ({ ...current, [slot]: packet }));
      if (packet.armed !== undefined) {
        setMavlinkStatuses((current) => ({
          ...current,
          [slot]: packet.armed ? "ARMED" : "DISARMED",
        }));
      }
    } catch {
      // Ignore malformed or non-telemetry messages.
    }
  }, []);

  useWebSocket({
    url: telemetryUrl,
    onMessage: onTelemetryMessage,
    enabled: Boolean(telemetryUrl),
  });

  useEffect(() => {
    if (!isConfigured) return;

    const connectUAV = async (uavId: UAVId) => {
      const connection = uavs[uavId];
      if (!connection?.tcpIp || !connection.mavlinkPort) return;

      const ip = connection.tcpIp.trim();
      const port = Number.parseInt(connection.mavlinkPort, 10);

      // Skip unconfigured / placeholder addresses
      if (!ip || ip === "0" || ip === "0.0.0.0" || !port || port <= 0) return;

      try {
        const response = await fetch(`${API_BASE}/api/telemetry/connect`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slot: uavId, ip, port }),
        });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
      } catch (error) {
        console.error(`[telemetry] Failed to connect UAV ${uavId}:`, error);
      }
    };

    const timer = window.setTimeout(() => {
      void Promise.all(UAV_IDS.map(connectUAV));
    }, 800);
    return () => window.clearTimeout(timer);
  }, [isConfigured, uavs]);

  if (!isConfigured) return <ConnectionSetupModal />;

  const mapVehicles = {
    1: {
      id: 1 as const,
      lat: telemetry[1]?.lat ?? null,
      lon: telemetry[1]?.lon ?? null,
      roll: telemetry[1]?.roll_deg ?? 0,
      pitch: telemetry[1]?.pitch_deg ?? 0,
      heading: telemetry[1]?.heading_deg ?? telemetry[1]?.yaw_deg ?? 0,
      altitude: telemetry[1]?.altitude_m ?? 0,
      satellites: telemetry[1]?.satellites_visible,
      hdop: telemetry[1]?.hdop,
      mode: telemetry[1]?.flight_mode,
      currentWaypoint: telemetry[1]?.current_waypoint,
      totalWaypoints: telemetry[1]?.total_waypoints,
      distanceToWaypoint: telemetry[1]?.distance_to_wp_m,
    },
    2: {
      id: 2 as const,
      lat: telemetry[2]?.lat ?? null,
      lon: telemetry[2]?.lon ?? null,
      roll: telemetry[2]?.roll_deg ?? 0,
      pitch: telemetry[2]?.pitch_deg ?? 0,
      heading: telemetry[2]?.heading_deg ?? telemetry[2]?.yaw_deg ?? 0,
      altitude: telemetry[2]?.altitude_m ?? 0,
      satellites: telemetry[2]?.satellites_visible,
      hdop: telemetry[2]?.hdop,
      mode: telemetry[2]?.flight_mode,
      currentWaypoint: telemetry[2]?.current_waypoint,
      totalWaypoints: telemetry[2]?.total_waypoints,
      distanceToWaypoint: telemetry[2]?.distance_to_wp_m,
    },
    3: {
      id: 3 as const,
      lat: telemetry[3]?.lat ?? null,
      lon: telemetry[3]?.lon ?? null,
      roll: telemetry[3]?.roll_deg ?? 0,
      pitch: telemetry[3]?.pitch_deg ?? 0,
      heading: telemetry[3]?.heading_deg ?? telemetry[3]?.yaw_deg ?? 0,
      altitude: telemetry[3]?.altitude_m ?? 0,
      satellites: telemetry[3]?.satellites_visible,
      hdop: telemetry[3]?.hdop,
      mode: telemetry[3]?.flight_mode,
      currentWaypoint: telemetry[3]?.current_waypoint,
      totalWaypoints: telemetry[3]?.total_waypoints,
      distanceToWaypoint: telemetry[3]?.distance_to_wp_m,
    },
    4: {
      id: 4 as const,
      lat: telemetry[4]?.lat ?? null,
      lon: telemetry[4]?.lon ?? null,
      roll: telemetry[4]?.roll_deg ?? 0,
      pitch: telemetry[4]?.pitch_deg ?? 0,
      heading: telemetry[4]?.heading_deg ?? telemetry[4]?.yaw_deg ?? 0,
      altitude: telemetry[4]?.altitude_m ?? 0,
      satellites: telemetry[4]?.satellites_visible,
      hdop: telemetry[4]?.hdop,
      mode: telemetry[4]?.flight_mode,
      currentWaypoint: telemetry[4]?.current_waypoint,
      totalWaypoints: telemetry[4]?.total_waypoints,
      distanceToWaypoint: telemetry[4]?.distance_to_wp_m,
    },
  };

  return (
    <>
      <main
        id="main-content-peta"
        style={{
          "--left-column-width": `${leftColumnPercent}%`,
          "--right-column-width": rightColumnWidth === null
            ? "clamp(248px, 20vw, 400px)"
            : `${rightColumnWidth}px`,
        } as CSSProperties}
      >
        <div className="kolom-monitoring-kiri">
          <MonitoringRow onCardWidthChange={handleInitialCardWidth}>
            <VideoPanel panelId={1} onTargetUpdate={setUdpTarget1} />
            <div className="telem-panel" id="telem-panel-1">
              <MavlinkHeader panelId={1} mavlinkStatus={mavlinkStatuses[1]} />
              <TelemetryStats
                telemetry={telemetry[1]}
                mavlinkStatus={mavlinkStatuses[1]}
                panelId={1}
                udpTarget={udpTarget1}
              />
            </div>
          </MonitoringRow>

          <MonitoringRow>
            <VideoPanel panelId={2} onTargetUpdate={setUdpTarget2} />
            <div className="telem-panel" id="telem-panel-2">
              <MavlinkHeader panelId={2} mavlinkStatus={mavlinkStatuses[2]} />
              <TelemetryStats
                telemetry={telemetry[2]}
                mavlinkStatus={mavlinkStatuses[2]}
                panelId={2}
                udpTarget={udpTarget2}
              />
            </div>
          </MonitoringRow>
        </div>

        <div
          className="dashboard-splitter"
          onMouseDown={handleMouseDownSplitter}
          title="Geser kanan atau kiri untuk mengubah lebar panel"
          role="separator"
          aria-orientation="vertical"
        >
          <span />
        </div>

        <div className="kolom-peta-tengah">
          <PetaOfflineUav
            vehicles={mapVehicles}
            mavlinkStatuses={mavlinkStatuses}
          />
        </div>

        <div
          className="dashboard-splitter dashboard-splitter-copter"
          onMouseDown={handleMouseDownCopterSplitter}
          onKeyDown={handleCopterSplitterKeyDown}
          onDoubleClick={() => {
            setRightColumnWidth(null);
            setMeasuredRightColumnWidth(
              Math.round(
                Math.min(
                  DEFAULT_RIGHT_COLUMN_MAX_WIDTH,
                  Math.max(MIN_RIGHT_COLUMN_WIDTH, window.innerWidth * 0.2),
                ),
              ),
            );
            window.requestAnimationFrame(() => {
              window.dispatchEvent(new Event("resize"));
            });
          }}
          title="Geser untuk mengubah lebar telemetry copter. Klik dua kali untuk reset."
          role="separator"
          aria-label="Ubah lebar peta dan telemetry copter"
          aria-orientation="vertical"
          aria-valuemin={MIN_RIGHT_COLUMN_WIDTH}
          aria-valuemax={MAX_RIGHT_COLUMN_WIDTH}
          aria-valuenow={Math.round(measuredRightColumnWidth)}
          tabIndex={0}
        >
          <span />
        </div>

        <aside className="kolom-monitoring-kanan" aria-label="Copter telemetry">
          <CopterTelemetryPanel
            panelId={3}
            telemetry={telemetry[3]}
            mavlinkStatus={mavlinkStatuses[3]}
          />
          <CopterTelemetryPanel
            panelId={4}
            telemetry={telemetry[4]}
            mavlinkStatus={mavlinkStatuses[4]}
          />
        </aside>
      </main>
    </>
  );
}

export default function Home() {
  return <GCSDashboard />;
}

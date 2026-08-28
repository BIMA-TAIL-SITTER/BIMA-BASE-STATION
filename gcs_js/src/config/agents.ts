import type { UAVConnectionConfig, UAVId, UAVType } from "@/types/telemetry";

export interface UAVAgentConfig {
  id: UAVId;
  label: string;
  shortLabel: string;
  type: UAVType;
  color: string;
  colorRgb: string;
  iconPath: string;
  hasVideo: boolean;
  defaultConnection: UAVConnectionConfig;
}

export const UAV_IDS: readonly UAVId[] = [1, 2, 3, 4];
export const FIXED_WING_IDS: readonly UAVId[] = [1, 2];
export const COPTER_IDS: readonly UAVId[] = [3, 4];

export const UAV_AGENTS: readonly UAVAgentConfig[] = [
  {
    id: 1,
    label: "UAV 1",
    shortLabel: "UAV 01",
    type: "FIXED WING",
    color: "#3B82F6",
    colorRgb: "59, 130, 246",
    iconPath: "/plane-blue.svg",
    hasVideo: true,
    defaultConnection: {
      streamPort: "5600",
      tcpIp: "192.168.1.10",
      mavlinkPort: "5761",
      jsonPort: "5001",
      missionUdpPort: "",
      raspiIp: "",
    },
  },
  {
    id: 2,
    label: "UAV 2",
    shortLabel: "UAV 02",
    type: "FIXED WING",
    color: "#F59E0B",
    colorRgb: "245, 158, 11",
    iconPath: "/plane-yellow.svg",
    hasVideo: true,
    defaultConnection: {
      streamPort: "5601",
      tcpIp: "192.168.1.11",
      mavlinkPort: "5762",
      jsonPort: "5002",
      missionUdpPort: "",
      raspiIp: "",
    },
  },
  {
    id: 3,
    label: "UAV 3",
    shortLabel: "UAV 03",
    type: "COPTER",
    color: "#F97316",
    colorRgb: "249, 115, 22",
    iconPath: "/copter.svg",
    hasVideo: false,
    defaultConnection: {
      streamPort: "",
      tcpIp: "192.168.1.12",
      mavlinkPort: "5763",
      jsonPort: "",
      missionUdpPort: "14560",
      raspiIp: "192.168.1.12",
    },
  },
  {
    id: 4,
    label: "UAV 4",
    shortLabel: "UAV 04",
    type: "COPTER",
    color: "#EC4899",
    colorRgb: "236, 72, 153",
    iconPath: "/copter.svg",
    hasVideo: false,
    defaultConnection: {
      streamPort: "",
      tcpIp: "192.168.1.13",
      mavlinkPort: "5764",
      jsonPort: "",
      missionUdpPort: "14561",
      raspiIp: "192.168.1.13",
    },
  },
];

export const UAV_AGENT_BY_ID = Object.fromEntries(
  UAV_AGENTS.map((agent) => [agent.id, agent]),
) as Record<UAVId, UAVAgentConfig>;

export function createEmptyConnectionRecord(): Record<UAVId, UAVConnectionConfig> {
  return Object.fromEntries(
    UAV_AGENTS.map((agent) => [
      agent.id,
      { streamPort: "", tcpIp: "", mavlinkPort: "", jsonPort: "", missionUdpPort: "", raspiIp: "" },
    ]),
  ) as Record<UAVId, UAVConnectionConfig>;
}

export function createDefaultConnectionRecord(): Record<UAVId, UAVConnectionConfig> {
  return Object.fromEntries(
    UAV_AGENTS.map((agent) => [agent.id, { ...agent.defaultConnection }]),
  ) as Record<UAVId, UAVConnectionConfig>;
}

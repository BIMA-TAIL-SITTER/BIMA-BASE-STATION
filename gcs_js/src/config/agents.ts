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
    color: "#56B4D3",
    colorRgb: "86, 180, 211",
    iconPath: "/plane-blue.svg",
    hasVideo: true,
    defaultConnection: {
      streamPort: "5600",
      tcpIp: "192.168.1.10",
      mavlinkPort: "5761",
      jsonPort: "5001",
    },
  },
  {
    id: 2,
    label: "UAV 2",
    shortLabel: "UAV 02",
    type: "FIXED WING",
    color: "#D6C15A",
    colorRgb: "214, 193, 90",
    iconPath: "/plane-yellow.svg",
    hasVideo: true,
    defaultConnection: {
      streamPort: "5601",
      tcpIp: "192.168.1.11",
      mavlinkPort: "5762",
      jsonPort: "5002",
    },
  },
  {
    id: 3,
    label: "UAV 3",
    shortLabel: "UAV 03",
    type: "COPTER",
    color: "#D78552",
    colorRgb: "215, 133, 82",
    iconPath: "/copter.svg",
    hasVideo: false,
    defaultConnection: {
      streamPort: "5602",
      tcpIp: "192.168.1.12",
      mavlinkPort: "5763",
      jsonPort: "5003",
    },
  },
  {
    id: 4,
    label: "UAV 4",
    shortLabel: "UAV 04",
    type: "COPTER",
    color: "#D56B9D",
    colorRgb: "213, 107, 157",
    iconPath: "/copter.svg",
    hasVideo: false,
    defaultConnection: {
      streamPort: "5603",
      tcpIp: "192.168.1.13",
      mavlinkPort: "5764",
      jsonPort: "5004",
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
      { streamPort: "", tcpIp: "", mavlinkPort: "", jsonPort: "" },
    ]),
  ) as Record<UAVId, UAVConnectionConfig>;
}

export function createDefaultConnectionRecord(): Record<UAVId, UAVConnectionConfig> {
  return Object.fromEntries(
    UAV_AGENTS.map((agent) => [agent.id, { ...agent.defaultConnection }]),
  ) as Record<UAVId, UAVConnectionConfig>;
}

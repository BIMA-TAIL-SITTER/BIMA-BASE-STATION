/** Common MAVLink mission command and frame metadata used by the editor. */

export interface MissionCommandPreset {
  id: number;
  name: string;
  params: readonly [string, string, string, string];
}

export const MISSION_COMMANDS: readonly MissionCommandPreset[] = [
  {
    id: 16,
    name: "NAV_WAYPOINT",
    params: ["Hold time", "Accept radius", "Pass radius", "Yaw angle"],
  },
  {
    id: 22,
    name: "NAV_TAKEOFF",
    params: ["Minimum pitch", "Unused", "Unused", "Yaw angle"],
  },
  {
    id: 21,
    name: "NAV_LAND",
    params: ["Abort altitude", "Land mode", "Unused", "Yaw angle"],
  },
  {
    id: 20,
    name: "NAV_RETURN_TO_LAUNCH",
    params: ["Unused", "Unused", "Unused", "Unused"],
  },
  {
    id: 17,
    name: "NAV_LOITER_UNLIM",
    params: ["Unused", "Unused", "Radius", "Yaw angle"],
  },
  {
    id: 18,
    name: "NAV_LOITER_TURNS",
    params: ["Turns", "Heading required", "Radius", "Xtrack location"],
  },
  {
    id: 177,
    name: "DO_JUMP",
    params: ["Target sequence", "Repeat count", "Unused", "Unused"],
  },
  {
    id: 112,
    name: "CONDITION_DELAY",
    params: ["Delay seconds", "Unused", "Unused", "Unused"],
  },
];

export const MISSION_FRAMES = [
  { id: 0, name: "MAV_FRAME_GLOBAL" },
  { id: 3, name: "MAV_FRAME_GLOBAL_RELATIVE_ALT" },
  { id: 10, name: "MAV_FRAME_GLOBAL_TERRAIN_ALT" },
] as const;

export const COMMAND_NAME_BY_ID = Object.fromEntries(
  MISSION_COMMANDS.map((command) => [command.id, command.name]),
) as Record<number, string>;

export const FRAME_NAME_BY_ID = Object.fromEntries(
  MISSION_FRAMES.map((frame) => [frame.id, frame.name]),
) as Record<number, string>;

export function createEmptyMissionItem(sequence: number) {
  return {
    seq: sequence,
    command: 16,
    frame: 3,
    lat: -7.7956,
    lon: 110.3695,
    alt: 50,
    param1: 0,
    param2: 2,
    param3: 0,
    param4: 0,
    current: sequence === 0,
    autocontinue: true,
  };
}

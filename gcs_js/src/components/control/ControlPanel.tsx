/** Future container for all flight-control actions belonging to one UAV slot. */

"use client";

import type { UAVId } from "@/types/telemetry";

interface ControlPanelProps {
  slot: UAVId;
}

export function ControlPanel({ slot }: ControlPanelProps) {
  void slot;
  // TODO: implement in control feature task.
  return null;
}

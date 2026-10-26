import type { Metadata } from "next";
import { SwarmControlPanel } from "@/components/control/SwarmControlPanel";

export const metadata: Metadata = {
  title: "Legacy Swarm Control | BIMA Base Station",
  description:
    "Dual-copter swarm orchestration with APF collision avoidance.",
};

export default function SwarmPage() {
  return (
    <main className="operations-page swarm-page">
      <SwarmControlPanel />
    </main>
  );
}

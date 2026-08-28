import type { Metadata } from "next";
import { FullDataManager } from "@/components/control/FullDataManager";

export const metadata: Metadata = {
  title: "Full Telemetry Data | BIMA Base Station",
  description: "View all real-time telemetry fields from connected UAVs.",
};

export default function FullDataPage() {
  return (
    <main className="operations-page">
      <FullDataManager />
    </main>
  );
}

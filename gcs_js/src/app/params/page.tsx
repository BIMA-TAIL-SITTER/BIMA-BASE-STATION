import type { Metadata } from "next";
import { ParameterManager } from "@/components/control/ParameterManager";

export const metadata: Metadata = {
  title: "Autopilot Parameters | BIMA Base Station",
  description: "Synchronize, search, and update UAV autopilot parameters.",
};

export default function ParamsPage() {
  return (
    <main className="operations-page">
      <ParameterManager />
    </main>
  );
}

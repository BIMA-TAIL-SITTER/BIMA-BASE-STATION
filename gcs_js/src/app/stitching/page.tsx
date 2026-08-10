import type { Metadata } from "next";
import { StitchingPanel } from "@/components/stitching/StitchingPanel";

export const metadata: Metadata = {
  title: "Live Stitching | BIMA Base Station",
  description: "Monitor live aerial image stitching and orthomosaic output.",
};

export default function StitchingPage() {
  return (
    <main className="operations-page stitching-page">
      <StitchingPanel />
    </main>
  );
}

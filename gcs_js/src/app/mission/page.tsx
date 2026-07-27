import type { Metadata } from "next";
import { MissionUploadControl } from "@/components/control/MissionUploadControl";

export const metadata: Metadata = {
  title: "Mission Control | BIMA Base Station",
  description: "Read, edit, preview, and upload UAV missions.",
};

export default function MissionPage() {
  return (
    <main className="operations-page mission-page">
      <MissionUploadControl />
    </main>
  );
}

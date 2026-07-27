import type { Metadata } from "next";
import { Barlow_Condensed, IBM_Plex_Mono } from "next/font/google";
import TopBar from "@/components/header/TopBar";
import EditConnectionModal from "@/components/modal/EditConnectionModal";
import { GCSProvider } from "@/hooks/useGCSStore";
import "./globals.css";

const barlowCondensed = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-display-next",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-data-next",
});

export const metadata: Metadata = {
  title: "UAV Ground Station",
  description: "Web-based UAV Ground Station with real-time video and telemetry",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${barlowCondensed.variable} ${ibmPlexMono.variable}`}
    >
      <body>
        <GCSProvider>
          <TopBar />
          {children}
          <EditConnectionModal />
        </GCSProvider>
      </body>
    </html>
  );
}

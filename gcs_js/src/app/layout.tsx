import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import TopBar from "@/components/header/TopBar";
import EditConnectionModal from "@/components/modal/EditConnectionModal";
import { GCSProvider } from "@/hooks/useGCSStore";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans-next",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono-next",
});

export const metadata: Metadata = {
  title: "BIMA Ground Control Station",
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
      className={`${inter.variable} ${jetbrainsMono.variable}`}
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

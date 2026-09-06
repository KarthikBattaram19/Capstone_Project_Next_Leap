import type { Metadata } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600"],
});

const mono = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
});

export const metadata: Metadata = {
  title: "Nakshatra — Voice Property Scout",
  description: "A voice-first assistant for finding a rental flat in Bengaluru.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${mono.variable}`}>
      <body>{children}</body>
    </html>
  );
}

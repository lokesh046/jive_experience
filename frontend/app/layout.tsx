import type { Metadata, Viewport } from "next";
import { Barlow_Condensed, Inter, Newsreader } from "next/font/google";
import { SITE_NAME, SITE_URL } from "@/lib/config";
import "./globals.css";

// Self-hosted by Next at build time: no render-blocking font requests, no layout shift.
const serif = Newsreader({ subsets: ["latin"], variable: "--font-serif", display: "swap" });
const sans = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const display = Barlow_Condensed({ subsets: ["latin"], weight: "700", style: "italic", variable: "--font-display", display: "swap" });

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: "JIVE — Live music evenings", template: "%s — JIVE" },
  description: "Tickets for JIVE's live music evenings in Mumbai, Bengaluru, Delhi and Goa.",
  openGraph: { siteName: SITE_NAME, type: "website", locale: "en_IN" },
  alternates: { canonical: "/" },
};

export const viewport: Viewport = { themeColor: "#000000", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" className={`${serif.variable} ${sans.variable} ${display.variable}`}>
      <body>
        {children}
      </body>
    </html>
  );
}

import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "sonner";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Throne",
  description: "Write a strategy in plain English. Throne parses it, backtests it and trades it.",
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body className="min-h-screen bg-bg font-sans">
        {children}
        <Toaster
          theme="dark"
          position="bottom-right"
          toastOptions={{
            className: "!rounded-none !border !border-line !bg-surface !font-mono !text-xs !text-fg",
          }}
        />
      </body>
    </html>
  );
}

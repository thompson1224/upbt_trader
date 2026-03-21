import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";
import Providers from "./providers";

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Upbit AI Trader",
  description: "AI 기반 업비트 자동매매 플랫폼",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="dark h-full">
      <body
        className={`${geistMono.variable} h-full bg-gray-950 text-gray-100 antialiased`}
      >
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}

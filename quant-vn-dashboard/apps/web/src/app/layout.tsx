import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quant VN Dashboard",
  description: "Personal AI-assisted quant portfolio dashboard for Vietnam equities.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}

import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "EngPulse AI",
  description: "Engineering Org Intelligence Command Center",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="topbar">
          <span className="brand">EngPulse&nbsp;AI</span>
          <span className="tagline">Engineering Org Intelligence</span>
        </header>
        <main className="container">{children}</main>
      </body>
    </html>
  );
}

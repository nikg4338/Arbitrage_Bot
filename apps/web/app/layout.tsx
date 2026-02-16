import type { Metadata } from "next";

import "./globals.css";

import { NavBar } from "@/components/NavBar";

export const metadata: Metadata = {
  title: "Cross-Exchange Mispricing Lab",
  description: "Decision support dashboard for Polymarket vs Kalshi mispricing + paper simulation"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <NavBar />
        <main className="mx-auto max-w-[1400px] px-6 py-6">{children}</main>
      </body>
    </html>
  );
}

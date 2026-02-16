"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const ITEMS = [
  { href: "/", label: "Dashboard" },
  { href: "/mappings", label: "Mappings" },
  { href: "/paper", label: "Paper Portfolio" }
];

export function NavBar() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-30 border-b border-white/10 bg-[#06111c]/85 backdrop-blur">
      <div className="mx-auto flex max-w-[1400px] items-center justify-between px-6 py-4">
        <div>
          <h1 className="font-display text-xl tracking-tight">Cross-Exchange Mispricing Lab</h1>
          <p className="text-xs text-sky-200/70">Polymarket vs Kalshi decision support + paper simulation</p>
        </div>
        <nav className="flex gap-2">
          {ITEMS.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-lg px-3 py-2 text-sm transition ${
                  active ? "bg-cyan-400/15 text-cyan-200" : "text-sky-200/80 hover:bg-white/5"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

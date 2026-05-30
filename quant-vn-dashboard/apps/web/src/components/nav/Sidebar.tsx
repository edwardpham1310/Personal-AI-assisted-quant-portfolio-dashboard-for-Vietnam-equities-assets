import Link from "next/link";
import type { Route } from "next";
import { NAV_ITEMS } from "@quant-shared/constants/nav";

export function Sidebar() {
  return (
    <aside className="hidden md:flex md:w-60 md:flex-col border-r border-border bg-bg-panel">
      <div className="px-5 py-5 border-b border-border">
        <Link href="/dashboard" className="text-ink font-semibold tracking-tight no-underline">
          Quant VN
        </Link>
        <p className="text-xs text-ink-dim mt-1">Research dashboard · MVP</p>
      </div>
      <nav className="flex-1 px-2 py-4 space-y-1">
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.href}
            // NAV_ITEMS.href is a hand-curated list of internal routes living
            // in a shared package; the cast satisfies typedRoutes without
            // forcing the shared package to import Next-specific types.
            href={item.href as Route}
            className="block rounded px-3 py-2 text-sm text-ink-muted hover:bg-bg-subtle hover:text-ink no-underline"
          >
            {item.label}
          </Link>
        ))}
      </nav>
      <div className="px-5 py-3 border-t border-border text-xs text-ink-dim">
        Recommend-only · No live orders
      </div>
    </aside>
  );
}

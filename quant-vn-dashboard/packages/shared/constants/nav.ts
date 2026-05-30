export type NavItem = {
  /** Route path under the dashboard layout. */
  href: string;
  /** Display label. */
  label: string;
  /** Sidebar order. */
  order: number;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { href: "/dashboard", label: "Dashboard Home", order: 1 },
  { href: "/market", label: "Market Overview", order: 2 },
  { href: "/watchlist", label: "Watchlist", order: 3 },
  { href: "/portfolio", label: "Portfolio", order: 4 },
  { href: "/assets-pnl", label: "Assets & PnL", order: 5 },
  { href: "/recommendations", label: "Recommendations", order: 6 },
  { href: "/data-quality", label: "Data Quality", order: 7 },
  { href: "/settings", label: "Settings", order: 8 },
] as const;

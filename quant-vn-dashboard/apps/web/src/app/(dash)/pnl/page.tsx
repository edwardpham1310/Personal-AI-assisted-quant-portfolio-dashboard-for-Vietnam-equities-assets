import { redirect } from "next/navigation";

export const metadata = { title: "Assets & PnL — Quant VN" };

/**
 * Legacy ``/pnl`` URL — the page moved to ``/assets-pnl`` during the
 * Portfolio MVP build. We issue a server-side redirect so bookmarks and
 * any stale internal links land on the canonical location.
 */
export default function PnlPage() {
  redirect("/assets-pnl");
}

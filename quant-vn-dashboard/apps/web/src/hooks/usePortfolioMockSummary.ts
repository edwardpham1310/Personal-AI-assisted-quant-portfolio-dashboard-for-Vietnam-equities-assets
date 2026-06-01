"use client";

import { useApi } from "@/lib/api";
import {
  MOCK_PORTFOLIO_SUMMARY,
  type PortfolioSummary as PortfolioMockSummary,
} from "@/lib/mock/portfolio";
import { useAsyncResource } from "./useAsyncResource";

/**
 * Legacy mock-backed portfolio summary used by the Dashboard Home KPI grid.
 *
 * The Portfolio and Assets & PnL pages use the real-backed
 * ``usePortfolioSummary`` / ``useAssetsSummary`` hooks instead. This thin
 * wrapper exists so we can keep the dashboard tile rendering while the
 * mock-shaped summary is gradually phased out.
 */
export function usePortfolioMockSummary() {
  const api = useApi();
  return useAsyncResource<PortfolioMockSummary>({
    fetcher: () => api<PortfolioMockSummary>("/portfolio/summary/legacy"),
    mockFallback: MOCK_PORTFOLIO_SUMMARY,
    // Explicit opt-in to mock-on-error: this hook is the legacy mock-backed
    // wrapper for the Dashboard Home KPI tile. Real-backed hooks live in
    // ``usePortfolioSummary`` and ``useAssetsSummary``.
    disableMockOnError: false,
  });
}

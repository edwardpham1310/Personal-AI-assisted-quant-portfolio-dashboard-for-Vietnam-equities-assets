"use client";

import { useApi } from "@/lib/api";
import { MOCK_INDICES, type IndexSnapshot } from "@/lib/mock/market";
import { useAsyncResource } from "./useAsyncResource";

type ApiIndex = {
  code: string;
  name?: string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  ts?: string;
};

function adaptIndex(row: ApiIndex): IndexSnapshot {
  const close = row.close ?? 0;
  const open = row.open ?? close;
  const change = close - open;
  return {
    code: row.code.toUpperCase(),
    name: row.name ?? row.code,
    close,
    change,
    change_pct: open ? change / open : 0,
    volume: row.volume ?? 0,
  };
}

export function useMarketIndices() {
  const api = useApi();
  return useAsyncResource<IndexSnapshot[]>({
    fetcher: async () => {
      const rows = await api<ApiIndex[]>("/market/live/indices");
      // An empty-but-successful response means the live cache is cold (poller
      // off or not yet warmed) — surface that as an empty result, not stale
      // mock numbers. Mock only substitutes on a genuine fetch *error* via
      // ``mockFallback`` below (and only when mock-on-error is enabled).
      return rows.map(adaptIndex);
    },
    mockFallback: MOCK_INDICES,
  });
}

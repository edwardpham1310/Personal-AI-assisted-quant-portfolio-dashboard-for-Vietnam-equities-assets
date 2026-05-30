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
      return rows.length === 0 ? MOCK_INDICES : rows.map(adaptIndex);
    },
    mockFallback: MOCK_INDICES,
  });
}

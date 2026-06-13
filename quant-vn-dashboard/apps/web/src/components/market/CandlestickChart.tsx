"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/AsyncStates";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { RangeSelect } from "@/components/ui/RangeSelect";
import { StaleNote } from "@/components/ui/StaleNote";
import { useDailyOhlcv } from "@/hooks/useDailyOhlcv";
import { OHLCV_RANGE_OPTIONS, rangeToDays, type RangeKey } from "@/lib/dateRange";
import type { OHLCV } from "@/lib/mock/market";
import { formatNumber } from "@/lib/format";

const UP_COLOR = "#22c55e";
const DOWN_COLOR = "#ef4444";

type Enriched = OHLCV & {
  range: [number, number];
  ma20: number | null;
  ma50: number | null;
  ma200: number | null;
};

function rollingMean(values: number[], window: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= window) sum -= values[i - window];
    out.push(i >= window - 1 ? sum / window : null);
  }
  return out;
}

function enrich(bars: OHLCV[]): Enriched[] {
  const closes = bars.map((b) => b.close);
  const ma20 = rollingMean(closes, 20);
  const ma50 = rollingMean(closes, 50);
  const ma200 = rollingMean(closes, 200);
  return bars.map((b, i) => ({
    ...b,
    range: [b.low, b.high],
    ma20: ma20[i],
    ma50: ma50[i],
    ma200: ma200[i],
  }));
}

type CandleProps = {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: Enriched;
};

export function Candle(props: CandleProps) {
  const { x = 0, y = 0, width = 0, height = 0, payload } = props;
  if (!payload) return null;
  const { open, high, low, close } = payload;
  const isUp = close >= open;
  const color = isUp ? UP_COLOR : DOWN_COLOR;
  const cx = x + width / 2;
  const bodyX = x + width * 0.15;
  const bodyW = Math.max(1, width * 0.7);

  // Flat / limit-locked day (high === low → zero range): recharts gives a
  // zero-height bar, so a normal candle would vanish. Draw a doji tick at the
  // price level instead of dropping the bar — common for VN ceiling/floor days.
  if (high === low) {
    return (
      <line x1={bodyX} y1={y} x2={bodyX + bodyW} y2={y} stroke={color} strokeWidth={1.5} />
    );
  }

  const yHighPx = y;
  const yLowPx = y + height;
  const scale = (v: number) => yHighPx + ((high - v) / (high - low)) * (yLowPx - yHighPx);
  const bodyTop = scale(Math.max(open, close));
  const bodyBottom = scale(Math.min(open, close));
  return (
    <g>
      <line x1={cx} y1={yHighPx} x2={cx} y2={yLowPx} stroke={color} strokeWidth={1} />
      <rect
        x={bodyX}
        width={bodyW}
        y={bodyTop}
        height={Math.max(1, bodyBottom - bodyTop)}
        fill={color}
        stroke={color}
      />
    </g>
  );
}

export function CandlestickChart({ initialSymbol = "FPT" }: { initialSymbol?: string }) {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [range, setRange] = useState<RangeKey>("3M");
  const days = useMemo(() => rangeToDays(range), [range]);
  const { data, isLoading, error, isMock, stale, lastUpdatedAt, hasLoadedReal, refetch } =
    useDailyOhlcv(symbol, days);
  const enriched = useMemo(() => enrich(data), [data]);
  const showChart = enriched.length > 0 && hasLoadedReal;

  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          Candlestick · {symbol}
          {isMock ? <Badge tone="mock">Mock</Badge> : null}
        </span>
      }
      hint="Daily OHLCV with MA20 / MA50 / MA200"
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          maxLength={20}
          className="w-24 rounded border border-border bg-bg px-2 py-1 font-mono text-sm text-ink uppercase"
        />
        <button
          onClick={refetch}
          className="rounded border border-border bg-bg-subtle px-2 py-1 text-xs text-ink-muted hover:border-accent hover:text-ink"
        >
          Refresh
        </button>
        <div className="ml-auto">
          <RangeSelect value={range} options={OHLCV_RANGE_OPTIONS} onChange={setRange} />
        </div>
      </div>

      {isLoading && !hasLoadedReal ? (
        <Skeleton height={240} />
      ) : !showChart && error ? (
        <p className="text-xs text-accent-down">{error}</p>
      ) : !showChart ? (
        <EmptyState>No bars for {symbol}.</EmptyState>
      ) : (
        <>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={enriched} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#21262d" vertical={false} />
                <XAxis dataKey="ts" tick={{ fill: "#8b949e", fontSize: 10 }} minTickGap={48} />
                <YAxis
                  yAxisId="price"
                  domain={["dataMin", "dataMax"]}
                  tick={{ fill: "#8b949e", fontSize: 10 }}
                  width={70}
                  tickFormatter={(v: number) => formatNumber(v)}
                />
                <Tooltip
                  contentStyle={{
                    background: "#0b0d10",
                    border: "1px solid #21262d",
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "#e6edf3" }}
                  formatter={(v: number | string, name: string) => {
                    if (name === "range" || Array.isArray(v)) return [null, null];
                    return [typeof v === "number" ? formatNumber(v) : v, name];
                  }}
                />
                <Bar
                  yAxisId="price"
                  dataKey="range"
                  // Recharts' shape prop is typed as ActiveShape but accepts a
                  // function component receiving the bar payload. Cast through
                  // any to bridge the typing gap without rewriting the chart.
                  shape={Candle as unknown as undefined}
                  legendType="none"
                  isAnimationActive={false}
                />
                <Line
                  yAxisId="price"
                  type="monotone"
                  dataKey="ma20"
                  name="MA20"
                  stroke="#4f8bf0"
                  dot={false}
                  strokeWidth={1.5}
                  isAnimationActive={false}
                />
                <Line
                  yAxisId="price"
                  type="monotone"
                  dataKey="ma50"
                  name="MA50"
                  stroke="#a855f7"
                  dot={false}
                  strokeWidth={1.5}
                  isAnimationActive={false}
                />
                <Line
                  yAxisId="price"
                  type="monotone"
                  dataKey="ma200"
                  name="MA200"
                  stroke="#f59e0b"
                  dot={false}
                  strokeWidth={1.5}
                  isAnimationActive={false}
                />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-2 h-20">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={enriched} margin={{ top: 0, right: 4, bottom: 0, left: 0 }}>
                <CartesianGrid stroke="#21262d" vertical={false} />
                <XAxis dataKey="ts" tick={{ fill: "#8b949e", fontSize: 9 }} minTickGap={48} />
                <YAxis
                  tick={{ fill: "#8b949e", fontSize: 9 }}
                  width={70}
                  tickFormatter={(v: number) => formatNumber(v)}
                />
                <Tooltip
                  contentStyle={{
                    background: "#0b0d10",
                    border: "1px solid #21262d",
                    fontSize: 11,
                  }}
                  formatter={(v: number) => formatNumber(v)}
                />
                <Bar dataKey="volume" fill="#4f8bf066" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
          <StaleNote asOf={lastUpdatedAt} stale={stale} />
        </>
      )}
    </Card>
  );
}

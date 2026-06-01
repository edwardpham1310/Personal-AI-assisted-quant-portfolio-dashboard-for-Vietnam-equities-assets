"use client";

import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { RecommendationScores } from "@/hooks/useRecommendations";

const SCORE_LABELS: Record<keyof RecommendationScores, string> = {
  trend: "Trend",
  momentum: "Momentum",
  volume: "Volume",
  liquidity: "Liquidity",
  risk: "Risk",
  risk_inverse: "Risk⁻¹",
  market_regime: "Regime",
  portfolio_fit: "Fit",
  ml_probability: "ML",
};

const COLORS: Record<string, string> = {
  trend: "#22c55e",
  momentum: "#0ea5e9",
  volume: "#a855f7",
  liquidity: "#14b8a6",
  risk: "#ef4444",
  risk_inverse: "#f97316",
  market_regime: "#eab308",
  portfolio_fit: "#6366f1",
  ml_probability: "#94a3b8",
};

type Row = { name: string; key: string; value: number; isMl: boolean };

export function ScoreBreakdown({ scores }: { scores: RecommendationScores }) {
  const data: Row[] = (Object.keys(SCORE_LABELS) as Array<keyof RecommendationScores>).map(
    (key) => {
      if (key === "ml_probability") {
        const v = scores.ml_probability;
        return {
          name: SCORE_LABELS[key],
          key,
          value: v == null ? 0 : Math.round(v * 100),
          isMl: true,
        };
      }
      return {
        name: SCORE_LABELS[key],
        key,
        value: Number(scores[key] ?? 0),
        isMl: false,
      };
    },
  );

  if (data.filter((d) => !d.isMl).every((d) => d.value === 0)) {
    return <div className="text-xs text-ink-dim">No score data available yet.</div>;
  }

  return (
    <div className="space-y-2">
      <div className="h-44 w-full" data-testid="score-breakdown-chart">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 16, right: 16 }}>
            <XAxis type="number" domain={[0, 100]} hide />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 11, fill: "currentColor" }}
              width={70}
            />
            <Tooltip
              cursor={{ fill: "rgba(255,255,255,0.05)" }}
              formatter={(value) => [`${value}`, "Score"]}
            />
            <Bar dataKey="value">
              {data.map((d) => (
                <Cell key={d.key} fill={COLORS[d.key]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {scores.ml_probability == null ? (
        <p className="text-[10px] text-ink-dim">
          ML probability: <span className="font-medium">Phase 2</span> — not included in Phase 1
          final score.
        </p>
      ) : null}
    </div>
  );
}

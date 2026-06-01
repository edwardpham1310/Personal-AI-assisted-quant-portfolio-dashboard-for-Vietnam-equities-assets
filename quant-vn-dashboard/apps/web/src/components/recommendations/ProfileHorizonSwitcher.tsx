"use client";

import {
  HORIZON_LABEL,
  horizonsForProfile,
  type RecommendationHorizon,
  type RecommendationProfile,
} from "@/hooks/useRecommendations";

export function ProfileHorizonSwitcher({
  profile,
  horizon,
  onProfileChange,
  onHorizonChange,
}: {
  profile: RecommendationProfile;
  horizon: RecommendationHorizon;
  onProfileChange: (p: RecommendationProfile) => void;
  onHorizonChange: (h: RecommendationHorizon) => void;
}) {
  const horizons = horizonsForProfile(profile);
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div
        role="radiogroup"
        aria-label="Recommendation profile"
        className="flex rounded border border-border bg-bg-subtle/40 p-0.5"
      >
        {(["short_aggressive", "long_conservative"] as const).map((p) => (
          <button
            key={p}
            type="button"
            role="radio"
            aria-checked={profile === p}
            onClick={() => {
              onProfileChange(p);
              const next = horizonsForProfile(p);
              if (!next.includes(horizon)) onHorizonChange(next[0]);
            }}
            className={`px-3 py-1 text-xs font-medium ${
              profile === p ? "bg-accent/15 text-accent" : "text-ink-dim hover:text-ink"
            }`}
          >
            {p === "short_aggressive" ? "Short / aggressive" : "Long / conservative"}
          </button>
        ))}
      </div>
      <select
        aria-label="Recommendation horizon"
        value={horizon}
        onChange={(e) => onHorizonChange(e.target.value as RecommendationHorizon)}
        className="rounded border border-border bg-bg px-2 py-1 text-xs text-ink"
      >
        {horizons.map((h) => (
          <option key={h} value={h}>
            {HORIZON_LABEL[h]}
          </option>
        ))}
      </select>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/Card";
import { useApi } from "@/lib/api";
import {
  useWatchlistRecommendations,
  type RecommendationHorizon,
  type RecommendationProfile,
  type RecommendationResult,
} from "@/hooks/useRecommendations";
import { RecoTable } from "@/components/recommendations/RecoTable";
import { ExplainabilityPanel } from "@/components/recommendations/ExplainabilityPanel";
import { RejectedRecsSection } from "@/components/recommendations/RejectedRecsSection";
import { ProfileHorizonSwitcher } from "@/components/recommendations/ProfileHorizonSwitcher";

type Watchlist = {
  id: string;
  name: string;
};

export default function RecommendationsPage() {
  const api = useApi();
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [watchlistId, setWatchlistId] = useState<string | null>(null);
  const [profile, setProfile] =
    useState<RecommendationProfile>("short_aggressive");
  const [horizon, setHorizon] =
    useState<RecommendationHorizon>("SHORT_2W");
  const [selected, setSelected] = useState<RecommendationResult | null>(null);
  const [watchlistsError, setWatchlistsError] = useState<string | null>(null);

  const loadWatchlists = useCallback(async () => {
    setWatchlistsError(null);
    try {
      const lists = await api<Watchlist[]>("/watchlists");
      if (!Array.isArray(lists)) return;
      setWatchlists(lists);
      setWatchlistId((prev) =>
        prev == null && lists.length > 0 ? lists[0].id : prev,
      );
    } catch (e) {
      setWatchlistsError(
        e instanceof Error ? e.message : "Failed to load watchlists.",
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadWatchlists();
  }, [loadWatchlists]);

  const { results, loading, error, refresh } = useWatchlistRecommendations(
    watchlistId,
    profile,
    horizon,
  );

  const validResults = useMemo(
    () => results.filter((r) => r.status !== "REJECTED"),
    [results],
  );

  const profileLabel =
    profile === "short_aggressive" ? "Short-term" : "Long-term";

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-ink">Recommendations</h1>
        <p className="text-sm text-ink-dim mt-1">
          Research signals · Rule-based · Not financial advice · No orders placed.
        </p>
      </header>

      <Card title="Controls">
        <div className="flex flex-wrap items-center gap-3">
          <ProfileHorizonSwitcher
            profile={profile}
            horizon={horizon}
            onProfileChange={setProfile}
            onHorizonChange={setHorizon}
          />
          <select
            aria-label="Watchlist"
            value={watchlistId ?? ""}
            onChange={(e) => setWatchlistId(e.target.value || null)}
            className="rounded border border-border bg-bg px-2 py-1 text-xs text-ink"
          >
            <option value="">— Select watchlist —</option>
            {watchlists.map((wl) => (
              <option key={wl.id} value={wl.id}>
                {wl.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void refresh()}
            disabled={loading || !watchlistId}
            className="rounded border border-border bg-bg-subtle px-3 py-1 text-xs text-ink hover:border-accent disabled:opacity-50"
          >
            {loading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </Card>

      {watchlistsError ? (
        <Card title="Could not load watchlists" hint={watchlistsError}>
          <button
            onClick={() => void loadWatchlists()}
            className="text-xs text-accent hover:underline"
          >
            Retry
          </button>
        </Card>
      ) : null}

      {!watchlistId ? (
        <Card title="Pick a watchlist">
          <p className="text-sm text-ink-dim">
            Create or select a watchlist to see recommendations. Manage
            watchlists on the Watchlist page.
          </p>
        </Card>
      ) : error ? (
        <Card title="Could not load recommendations" hint={error}>
          <button
            onClick={() => void refresh()}
            className="text-xs text-accent hover:underline"
          >
            Retry
          </button>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <div className="space-y-4 lg:col-span-2">
            <Card title={`${profileLabel} recommendations`}>
              <RecoTable results={validResults} onSelect={setSelected} />
            </Card>
            <RejectedRecsSection
              results={results}
              onSelect={setSelected}
            />
          </div>
          <div>
            <ExplainabilityPanel rec={selected} />
          </div>
        </div>
      )}
    </div>
  );
}

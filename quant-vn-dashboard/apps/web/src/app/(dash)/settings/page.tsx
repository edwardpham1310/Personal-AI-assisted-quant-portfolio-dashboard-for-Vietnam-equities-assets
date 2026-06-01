"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui/Card";
import { useApi } from "@/lib/api";

type Theme = "dark" | "light";
type RiskProfile = "conservative" | "moderate" | "aggressive";

type Settings = {
  id: string;
  user_id: string;
  default_broker: string;
  risk_profile: RiskProfile;
  default_watchlist_id: string | null;
  theme: Theme;
};

type SettingsPatch = Partial<Pick<Settings, "default_broker" | "risk_profile" | "theme">>;

const SAVE_DEBOUNCE_MS = 400;

/**
 * Apply ``settings.theme`` to the document root so the rest of the app's
 * dark/light Tailwind tokens follow. Idempotent — safe to call multiple times.
 */
function applyTheme(theme: Theme | null | undefined): void {
  if (typeof document === "undefined" || !theme) return;
  const root = document.documentElement;
  root.classList.toggle("dark", theme === "dark");
  root.classList.toggle("light", theme === "light");
}

export default function SettingsPage() {
  const api = useApi();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  // Coalesce rapid edits — a 400ms debounce avoids a save-storm if the user
  // toggles selects quickly.
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingPatchRef = useRef<SettingsPatch>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await api<Settings>("/settings");
      setSettings(s);
      applyTheme(s.theme);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings.");
    } finally {
      setLoading(false);
    }
  }, [api]);

  useEffect(() => {
    void load();
  }, [load]);

  // Clean up any pending debounce on unmount.
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const flushSave = useCallback(async () => {
    const patch = pendingPatchRef.current;
    if (Object.keys(patch).length === 0) return;
    pendingPatchRef.current = {};
    setSaving(true);
    setError(null);
    try {
      const next = await api<Settings>("/settings", {
        method: "PUT",
        body: JSON.stringify(patch),
      });
      setSettings(next);
      applyTheme(next.theme);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }, [api]);

  function queueSave(patch: SettingsPatch) {
    // Optimistically reflect the change in the form so the select stays
    // responsive — the server will reconcile on flush.
    setSettings((prev) => (prev ? { ...prev, ...patch } : prev));
    if (patch.theme) applyTheme(patch.theme);
    pendingPatchRef.current = { ...pendingPatchRef.current, ...patch };
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      void flushSave();
    }, SAVE_DEBOUNCE_MS);
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold text-ink">Settings</h1>
        <p className="text-sm text-ink-dim mt-1">
          Stored per user. Broker credentials never leave the API host.
        </p>
      </header>

      {loading ? (
        <Card title="Loading…">
          <p>Fetching your settings.</p>
        </Card>
      ) : error ? (
        <Card title="Could not load settings" hint={error}>
          <button onClick={load} className="text-xs text-accent hover:underline">
            Retry
          </button>
        </Card>
      ) : settings ? (
        <Card
          title="Profile"
          hint={saving ? "Saving…" : savedAt ? `Saved at ${savedAt}` : undefined}
        >
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <label className="block">
              <span className="text-xs text-ink-muted">Default broker</span>
              <select
                value={settings.default_broker}
                onChange={(e) => queueSave({ default_broker: e.target.value })}
                className="mt-1 w-full rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
              >
                <option value="SSI">SSI</option>
                <option value="VNDIRECT">VNDIRECT</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs text-ink-muted">Risk profile</span>
              <select
                value={settings.risk_profile}
                onChange={(e) => queueSave({ risk_profile: e.target.value as RiskProfile })}
                className="mt-1 w-full rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
              >
                <option value="conservative">Conservative</option>
                <option value="moderate">Moderate</option>
                <option value="aggressive">Aggressive</option>
              </select>
            </label>
            <label className="block">
              <span className="text-xs text-ink-muted">Theme</span>
              <select
                value={settings.theme}
                onChange={(e) => queueSave({ theme: e.target.value as Theme })}
                className="mt-1 w-full rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
              >
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </label>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

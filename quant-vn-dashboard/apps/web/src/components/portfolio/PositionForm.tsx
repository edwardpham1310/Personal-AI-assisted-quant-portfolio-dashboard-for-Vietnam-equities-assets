"use client";

import { useEffect, useState } from "react";
import { VN_EXCHANGES, type VnExchange } from "@quant-shared/constants/markets";
import type {
  EnrichedPosition,
  PositionCreate,
  PositionUpdate,
} from "@/hooks/portfolio-types";

export type PositionFormProps = {
  /** Existing position when editing; null/undefined when creating. */
  initial?: EnrichedPosition | null;
  /** Called with payload + ``mode`` so the parent can pick the right endpoint. */
  onSubmit: (
    payload: PositionCreate | PositionUpdate,
    mode: "create" | "update",
    positionId: string | null,
  ) => Promise<void> | void;
  onCancel?: () => void;
  busy?: boolean;
};

export function PositionForm({
  initial,
  onSubmit,
  onCancel,
  busy,
}: PositionFormProps) {
  const mode: "create" | "update" = initial ? "update" : "create";
  const [symbol, setSymbol] = useState(initial?.symbol ?? "");
  const [exchange, setExchange] = useState<VnExchange>(
    initial?.exchange ?? "HOSE",
  );
  const [quantity, setQuantity] = useState(
    initial ? String(initial.quantity) : "",
  );
  const [avgCost, setAvgCost] = useState(
    initial ? String(initial.avg_cost) : "",
  );
  const [tag, setTag] = useState(initial?.strategy_tag ?? "");
  const [note, setNote] = useState(initial?.note ?? "");
  const [error, setError] = useState<string | null>(null);

  // Keep the form synced when the parent swaps which position is being edited.
  useEffect(() => {
    setSymbol(initial?.symbol ?? "");
    setExchange(initial?.exchange ?? "HOSE");
    setQuantity(initial ? String(initial.quantity) : "");
    setAvgCost(initial ? String(initial.avg_cost) : "");
    setTag(initial?.strategy_tag ?? "");
    setNote(initial?.note ?? "");
    setError(null);
  }, [initial]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const qty = Number(quantity);
    const cost = Number(avgCost);
    const symClean = symbol.trim().toUpperCase();

    if (mode === "create" && !symClean) {
      setError("Symbol is required.");
      return;
    }
    if (Number.isNaN(qty) || qty <= 0) {
      setError("Quantity must be a positive number.");
      return;
    }
    if (Number.isNaN(cost) || cost < 0) {
      setError("Average cost must be zero or positive.");
      return;
    }

    const payload: PositionCreate | PositionUpdate =
      mode === "create"
        ? {
            symbol: symClean,
            exchange,
            quantity: qty,
            avg_cost: cost,
            strategy_tag: tag.trim() || null,
            note: note.trim() || null,
          }
        : {
            quantity: qty,
            avg_cost: cost,
            strategy_tag: tag.trim() || null,
            note: note.trim() || null,
          };

    try {
      await onSubmit(payload, mode, initial?.id ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Submit failed.");
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="space-y-3"
      aria-label={mode === "create" ? "Add position" : "Edit position"}
    >
      <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
        <input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder="Symbol"
          disabled={mode === "update"}
          required={mode === "create"}
          aria-label="Symbol"
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink uppercase disabled:opacity-60"
        />
        <select
          value={exchange}
          onChange={(e) => setExchange(e.target.value as VnExchange)}
          disabled={mode === "update"}
          aria-label="Exchange"
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink disabled:opacity-60"
        >
          {VN_EXCHANGES.map((x) => (
            <option key={x}>{x}</option>
          ))}
        </select>
        <input
          type="number"
          min={1}
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          placeholder="Qty"
          required
          aria-label="Quantity"
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
        />
        <input
          type="number"
          step="0.0001"
          min={0}
          value={avgCost}
          onChange={(e) => setAvgCost(e.target.value)}
          placeholder="Avg cost (VND)"
          required
          aria-label="Average cost"
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
        />
        <input
          value={tag}
          onChange={(e) => setTag(e.target.value)}
          placeholder="Strategy tag"
          aria-label="Strategy tag"
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
        />
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="Note"
          aria-label="Note"
          className="rounded border border-border bg-bg px-2 py-1 text-sm text-ink"
        />
      </div>

      {error ? (
        <p className="text-xs text-accent-down" role="alert">
          {error}
        </p>
      ) : null}

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {mode === "create" ? "Add position" : "Save changes"}
        </button>
        {onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="rounded border border-border bg-bg-subtle px-3 py-1.5 text-sm text-ink hover:border-accent disabled:opacity-50"
          >
            Cancel
          </button>
        ) : null}
      </div>
    </form>
  );
}

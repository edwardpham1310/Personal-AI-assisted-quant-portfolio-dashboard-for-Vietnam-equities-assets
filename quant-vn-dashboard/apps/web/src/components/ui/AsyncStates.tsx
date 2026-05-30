import type { ReactNode } from "react";

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded border border-accent-down/30 bg-accent-down/5 px-3 py-2 text-xs text-accent-down">
      <p>{message}</p>
      {onRetry ? (
        <button
          onClick={onRetry}
          className="mt-1 text-[11px] underline hover:no-underline"
        >
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="text-xs text-ink-dim italic">{children}</p>;
}

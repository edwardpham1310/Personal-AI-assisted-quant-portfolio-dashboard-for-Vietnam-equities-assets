import type { ReactNode } from "react";

export function Card({
  title,
  hint,
  action,
  children,
}: {
  title: ReactNode;
  hint?: string;
  /** Optional control rendered at the top-right of the header (e.g. a range dropdown). */
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border bg-bg-panel">
      <header className="px-4 py-3 border-b border-border flex items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-medium text-ink">{title}</h2>
          {hint ? <p className="text-xs text-ink-dim mt-0.5">{hint}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </header>
      <div className="px-4 py-4 text-sm text-ink-muted">{children}</div>
    </section>
  );
}

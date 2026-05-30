import type { ReactNode } from "react";

export function Card({
  title,
  hint,
  children,
}: {
  title: ReactNode;
  hint?: string;
  children?: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border bg-bg-panel">
      <header className="px-4 py-3 border-b border-border">
        <h2 className="text-sm font-medium text-ink">{title}</h2>
        {hint ? <p className="text-xs text-ink-dim mt-0.5">{hint}</p> : null}
      </header>
      <div className="px-4 py-4 text-sm text-ink-muted">{children}</div>
    </section>
  );
}

export function PlaceholderCard({ title, module }: { title: string; module: string }) {
  return (
    <Card title={title} hint={`Module: ${module} (scaffold)`}>
      <p className="text-ink-muted">
        This view is scaffolded. Real data wiring is planned in the {module} milestone — see
        <code className="ml-1 font-mono text-ink">docs/api.md</code>.
      </p>
    </Card>
  );
}

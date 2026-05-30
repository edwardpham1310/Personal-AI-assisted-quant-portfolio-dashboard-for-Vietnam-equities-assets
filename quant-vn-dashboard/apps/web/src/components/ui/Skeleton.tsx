export function Skeleton({
  className = "",
  width,
  height = 12,
}: {
  className?: string;
  width?: string | number;
  height?: number;
}) {
  return (
    <span
      aria-hidden
      className={`inline-block animate-pulse rounded bg-bg-subtle ${className}`}
      style={{ width: width ?? "100%", height }}
    />
  );
}

export function SkeletonRows({ rows = 3, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="grid gap-2" style={{ gridTemplateColumns: `repeat(${columns}, 1fr)` }}>
          {Array.from({ length: columns }, (_, j) => (
            <Skeleton key={j} />
          ))}
        </div>
      ))}
    </div>
  );
}

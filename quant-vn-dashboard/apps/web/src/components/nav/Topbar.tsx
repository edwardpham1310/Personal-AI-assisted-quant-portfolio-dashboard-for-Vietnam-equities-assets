import { UserMenu } from "@/components/auth/UserMenu";

export function Topbar() {
  return (
    <header className="flex h-12 items-center justify-between border-b border-border bg-bg-panel px-4 lg:px-6">
      <div className="text-sm text-ink-muted">Vietnam equities · HOSE / HNX / UPCoM</div>
      <UserMenu />
    </header>
  );
}

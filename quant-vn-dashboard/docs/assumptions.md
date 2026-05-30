# Assumptions & Limits

This document records the assumptions the dashboard depends on. They are
deliberate; verify them before trusting any recommendation.

## Scope

- Vietnam market: HOSE, HNX, UPCoM equities + indices first.
- Single primary user during MVP. Schema is multi-user-ready.
- Phase 1 is **recommend-only**. The dashboard never places real orders.

## Market mechanics

- T+2 cash settlement. Sell proceeds are not available for new buys until
  settlement unless cash advance is enabled.
- Lot size 100 shares for HOSE/HNX (standard board).
- Price limits: HOSE ±7%, HNX ±10%, UPCoM ±15%.
- No short selling.
- See `../../quant/config/market_vietnam.yaml` for the full cost/tax/fee model;
  every rate carries a "VERIFY" note and must be confirmed with the broker.

## Data providers

- SSI FastConnect is the primary market data and (later) trading provider.
- Polling cadence: 5–15s in MVP. Streaming will replace polling when
  entitlement is granted, without changes to the API contract.
- All SSI calls go through `apps/api`. The frontend has no direct path to SSI.

## Latency

- "Realtime" means within ~5–15s of SSI snapshot — good enough for decision
  support, not for execution.

## Security

- `.env` is gitignored. Never commit secrets.
- SSI credentials live only in the API process env.
- Per-user broker credentials (future) are stored encrypted at rest with
  Fernet using a service-side master key.
- All app tables in Supabase enable Row-Level Security.

## What is explicitly out of scope for MVP

- Auto order placement of any kind.
- Backtest UI (engine remains library-only via `quant-vn` CLI).
- ML training / inference UI.
- Paper trading ledger UI.
- Derivatives Greeks, options chains.
- Mobile / PWA install flow.
- Email / SMS / Telegram alerts (in-app SSE alerts only).

## Disclaimer

This is a research tool. Numbers and recommendations are informational only
and do not constitute financial, tax, or legal advice. The user is
responsible for verifying every assumption against their broker and current
regulations.

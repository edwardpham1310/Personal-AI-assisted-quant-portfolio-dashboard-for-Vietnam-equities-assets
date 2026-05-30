# Portfolio + Assets/PnL MVP — Decision Document

> **Audience**: Backend Architect, Frontend Developer.
> **Goal**: One source of truth so backend and frontend can build in parallel
> without drift. All decisions below are binding for Phase 1; deferrals are
> explicit so seams are left for Phase 2/3.
> **Status**: Approved for parallel build.
> **Phase**: 1 (recommend-only, manual portfolio, no order placement).

---

## 1. MVP scope (one screen of value)

### In scope
- Manual portfolio CRUD (account + positions) — already partially shipped at
  `/portfolio/manual/*`; this doc adds the recompute-on-read endpoints.
- **Market-value calculation** using the latest cached quote (`Redis hot cache`
  via `/market/quote/{symbol}`).
- **Asset/cash breakdown**: settled cash, pending cash, cash advance,
  stock market value, total equity, buying power.
- **Realized PnL** from `trade_transactions` (sells), using weighted-average
  cost basis at sell time.
- **Unrealized PnL** from `manual_positions` × latest quote.
- **Fee/tax fields stored on `trade_transactions`** (brokerage, VAT, sell tax,
  cash advance fee, slippage). Stored data; surfaced in aggregate; not
  recomputed by Phase 1.
- **SSI sync placeholder endpoint** that returns 501 — frontend renders a
  disabled button so the seam is visible.

### Deliberately out of scope (do not build, do not design for)
- Order placement (entire workspace principle, not just this MVP).
- Auto-sync with SSI (Phase 2).
- Multi-currency. VND only. `currency` column stays but no FX conversion.
- Tax filing exports.
- Tax-lot specific identification.
- FIFO / LIFO accounting.
- Dividend tracking.
- Corporate-action adjustments to `avg_cost`.
- Intraday PnL (mark-to-market within the trading day).
- Per-trade `avg_cost` recompute (we do NOT mutate position `avg_cost` from
  trades in Phase 1; the user owns that field).

### Phase boundaries (leave seams)
- **Phase 2** = read-only SSI sync. Will write to `cash_balances` and append
  `trade_transactions`. The `ssi_sync.py` interface (see §6) is the seam.
- **Phase 3** = paper-trading ledger. Will introduce a separate
  `paper_positions` table; do not overload `manual_positions`.
- **Phase 4** = order placement. Out of every architectural decision below.

---

## 2. Schema decisions

### `manual_portfolio_accounts` — keep as-is
Already in `0001_init.sql`. No changes. Owner-scoped by RLS via `user_id =
auth.uid()`.

### `manual_positions` — keep static, **compute via service layer**
**Decision**: do NOT add `sellable_quantity`, `pending_quantity`, or
`last_marked_at` columns to the table.

**Why**: those values are derived from `trade_transactions` + today's date
under T+2 rules. Persisting them creates two sources of truth and a stale-state
bug surface. The service layer computes them at read time in
`GET /portfolio/positions`. Cost: one extra query per position read; cheap
because reads are user-scoped (≤ ~30 rows for a personal dashboard).

A `0002_phase2_settlement.sql` migration may add `last_marked_at` later if a
streaming PnL feature requires it — not now.

### `cash_balances` — NEW
One row per account (mutable, `UPSERT` on sync or manual edit). Schema:

| Column                  | Type            | Notes                                                |
|-------------------------|-----------------|------------------------------------------------------|
| `id`                    | uuid PK         | `gen_random_uuid()`                                  |
| `account_id`            | uuid FK NOT NULL UNIQUE | references `manual_portfolio_accounts(id)`   |
| `settled_cash`          | numeric(20,4)   | T+2 settled; spendable today                         |
| `pending_cash`          | numeric(20,4)   | Proceeds awaiting T+2                                |
| `advanced_cash`         | numeric(20,4)   | Cash received via cash-advance service               |
| `cash_advance_liability`| numeric(20,4)   | Outstanding repayment owed                           |
| `withdrawable_cash`     | numeric(20,4)   | Subset of `settled_cash` allowed to leave the broker |
| `currency`              | text            | `'VND'` default, check constraint                    |
| `as_of`                 | timestamptz     | When user (or sync) last wrote this row              |
| `created_at`            | timestamptz     | default now()                                        |
| `updated_at`            | timestamptz     | trigger                                              |

RLS via parent: `exists (select 1 from manual_portfolio_accounts a where
a.id = cash_balances.account_id and a.user_id = auth.uid())`.

### `trade_transactions` — NEW (append-only)

| Column              | Type            | Notes                                       |
|---------------------|-----------------|---------------------------------------------|
| `id`                | uuid PK         |                                             |
| `account_id`        | uuid FK NOT NULL| `manual_portfolio_accounts(id)`             |
| `symbol`            | text NOT NULL   | upper-cased on insert                       |
| `exchange`          | text NOT NULL   | check `('HOSE','HNX','UPCOM')`              |
| `side`              | text NOT NULL   | check `('BUY','SELL')`                      |
| `quantity`          | integer NOT NULL| `> 0`                                       |
| `price`             | numeric(20,4)   | per-share fill price                        |
| `trade_date`        | date NOT NULL   | T                                           |
| `settlement_date`   | date NOT NULL   | T+2 (computed client-side or trigger)       |
| `brokerage_fee`     | numeric(20,4)   | stored, not computed Phase 1                |
| `vat`               | numeric(20,4)   | stored                                      |
| `sell_tax`          | numeric(20,4)   | stored (SELL only; nullable)                |
| `cash_advance_fee`  | numeric(20,4)   | stored                                      |
| `slippage_estimate` | numeric(20,4)   | optional, user-entered or null              |
| `note`              | text            |                                             |
| `created_at`        | timestamptz     | default now()                               |

No `updated_at` — append-only. Corrections happen via a compensating row + note.
RLS parent-owned.

### `fee_tax_summary` — **DEFER**
**Recommendation: do not create.** All fields already live on
`trade_transactions`. A summary is a `SELECT SUM(...) FROM trade_transactions
WHERE account_id = ? AND trade_date BETWEEN ? AND ?`. If Phase 2 needs
performance, promote it to a materialized view then. YAGNI now.

### T+2 settlement model (Vietnam)
- BUY at trade_date `T` → quantity is **pending** on T, T+1; **sellable** from
  T+2. (HOSE rule: T+2 ~14:30; we treat the entire day T+2 as sellable in
  Phase 1 — a sub-day refinement is Phase 2.)
- SELL at trade_date `T` → cash is **pending_cash** on T, T+1; **settled_cash**
  from T+2.

**Computation rule** (service layer, `GET /portfolio/positions`):
```
sellable_quantity[symbol] =
    sum(BUY.quantity WHERE settlement_date <= today)
  - sum(SELL.quantity for matched lots)
pending_quantity[symbol]  =
    sum(BUY.quantity  WHERE settlement_date >  today)
```
Where `manual_positions.quantity` is the snapshot truth and the
trade-derived view is a reconciliation overlay. **If the user has no
`trade_transactions` rows, `pending_quantity = 0` and `sellable_quantity =
manual_positions.quantity`** — keeps existing UX working before any trades are
logged.

**HNX/UPCOM caveat**: HOSE/HNX equity settlement is T+2 today; UPCoM follows.
For derivatives (out of MVP scope) the cycle differs. Documented in §10.

---

## 3. Identity / default account behaviour

The new spec uses paths like `GET /portfolio/positions` with **no
`account_id`**. The existing routes use `/portfolio/manual/*` with explicit
account IDs. We need a rule for the new endpoints.

**Decision**: introduce a **default account** concept.
- Rule: the default is whichever `manual_portfolio_accounts` row the user has
  flagged via `user_settings.default_account_id` (new nullable column,
  `0002_default_account.sql`); if NULL or invalid, fall back to the
  earliest-`created_at` account for that user.
- If the user has **zero accounts**, the new endpoints return HTTP 200 with an
  empty payload and `account_id: null` — the frontend renders the "Create an
  account" empty state, not an error.
- Multi-account power-users keep the existing `/portfolio/manual/*` surface for
  per-account control; `/portfolio/positions/*` always targets the default.
- A new `PATCH /portfolio/manual/accounts/{id}/default` endpoint flips the
  default (writes `user_settings.default_account_id`). Frontend exposes a
  radio button in the account list.

---

## 4. Endpoint contract decisions

All endpoints require `Authorization: Bearer <supabase_jwt>` unless noted.
All paths are mounted under `/portfolio` or `/assets` from `apps/api`.
Response shapes are Pydantic; only field names + types are fixed here.

### `GET /portfolio/summary`
- Query: none.
- Targets the default account (§3).
- Response `PortfolioSummary`:
  ```
  account_id:           UUID | None
  positions_count:      int
  total_cost:           Decimal
  total_market_value:   Decimal | None     # None if any quote missing
  total_unrealized_pnl: Decimal | None
  by_strategy_tag:      list[StrategyTagBreakdown]
      tag: str | None
      market_value: Decimal | None
      weight: float | None
  last_marked_at:       datetime | None    # max(quote.as_of) across positions
  warnings:             list[str]          # e.g. "VHM quote unavailable"
  ```

### `GET /portfolio/positions`
- Query: none.
- Response `list[PositionView]`:
  ```
  id: UUID
  symbol: str
  exchange: str
  quantity: int
  sellable_quantity: int
  pending_quantity:  int
  avg_cost:          Decimal
  market_price:      Decimal | None
  market_value:      Decimal | None
  unrealized_pnl:    Decimal | None
  unrealized_pnl_pct: float | None
  weight:            float | None
  strategy_tag:      str | None
  note:              str | None
  quote_as_of:       datetime | None
  ```

### `POST /portfolio/positions` / `PUT /portfolio/positions/{id}` / `DELETE /portfolio/positions/{id}`
- Thin shims over the existing `/portfolio/manual/positions` handlers; they
  resolve the default account server-side and forward.
- POST body `PositionCreate`: `symbol`, `exchange`, `quantity`, `avg_cost`,
  `strategy_tag?`, `note?`. Returns 201 + `PositionView`.
- PUT body `PositionUpdate`: any subset of the above. Returns 200 +
  `PositionView`. 400 if empty patch.
- DELETE returns 204.

### `GET /assets/summary`
- Response `AssetsSummary`:
  ```
  account_id:              UUID | None
  settled_cash:            Decimal
  pending_cash:            Decimal
  advanced_cash:           Decimal
  cash_advance_liability:  Decimal
  withdrawable_cash:       Decimal
  stock_market_value:      Decimal | None
  total_equity:            Decimal | None
  available_buying_power:  Decimal
  as_of:                   datetime | None
  warnings:                list[str]
  ```

### `GET /assets/pnl`
- Query: `period: 'MTD' | 'YTD' | 'ALL' = 'ALL'` (filters realized only;
  unrealized is point-in-time).
- Response `AssetsPnL`:
  ```
  realized_pnl_total:   Decimal
  unrealized_pnl_total: Decimal | None
  by_symbol: list[SymbolPnL]
      symbol: str
      realized: Decimal
      unrealized: Decimal | None
  period: str
  trades_considered: int
  ```

### `GET /assets/costs`
- Query: `period: 'MTD' | 'YTD' | 'ALL' = 'MTD'`.
- Response `AssetsCosts`:
  ```
  brokerage_total:        Decimal
  vat_total:              Decimal
  sell_tax_total:         Decimal
  cash_advance_fee_total: Decimal
  slippage_total:         Decimal
  grand_total:            Decimal
  trade_count:            int
  period:                 str
  ```

### `POST /portfolio/sync/ssi` — placeholder
- Returns `501 Not Implemented` with body
  `{"detail": "SSI sync coming in Phase 2", "status": "placeholder"}`.

---

## 5. Calculation rules (definitive)

These are binding. Backend tests assert them; frontend renders them.

```
cost_basis           = quantity * avg_cost
market_value         = quantity * market_price            # None if quote missing
unrealized_pnl       = market_value - cost_basis          # None if MV None
unrealized_pnl_pct   = unrealized_pnl / cost_basis        # None if cost_basis == 0
weight               = market_value / total_market_value  # None if either side None/0
available_buying_power = settled_cash                     # conservative
total_equity         = settled_cash + pending_cash + stock_market_value
                     + advanced_cash - cash_advance_liability   # None if MV None
realized_pnl(SELL)   = (price - weighted_avg_cost_at_sell) * qty
                     - brokerage_fee - vat - sell_tax
```

**Realized PnL rule (binding)**: use **weighted-average cost basis at time of
sell** computed from prior BUY rows in `trade_transactions` for that
`(account_id, symbol)`. **No FIFO, no LIFO, no lot identification.** This is
documented as a Phase 1 simplification — the AI narrative layer must surface
this caveat when presenting realized PnL.

**Empty-state guarantee**: when a query has no rows, totals are zero, not
NULL. NULL is reserved for "data exists but a dependent quote is missing".

---

## 6. SSI sync placeholder design

- New module: `apps/api/src/services/ssi_sync.py`.
- Interface (stub):
  ```python
  class SsiSyncService:
      async def sync_positions(self, user_id: str, account_id: str) -> None:
          raise NotImplementedError("Phase 2")
      async def sync_cash(self, user_id: str, account_id: str) -> None:
          raise NotImplementedError("Phase 2")
      async def sync_trades(self, user_id: str, account_id: str,
                            since: date | None = None) -> None:
          raise NotImplementedError("Phase 2")
  ```
- Route: `POST /portfolio/sync/ssi` in `apps/api/src/api/routes/portfolio.py`,
  wired to the stub. Returns HTTP 501 with the JSON in §4.

**Why placeholder, not nothing**: lets the frontend ship the "Sync from SSI"
button greyed-out with a tooltip "Available in Phase 2". Users see the roadmap
in the product, not just in a doc. The 501 contract also gives Phase 2 an
already-documented endpoint surface — no breaking change at GA.

---

## 7. UI scope per page

### Charting library decision
**Use `recharts`, NOT Plotly.** `recharts@^2.13.0` is already in
`apps/web/package.json`. `docs/architecture.md` still mentions Plotly — that's
stale; update it as part of this MVP. Reasons: smaller bundle, server-component
friendly via dynamic import, already used elsewhere in the app.

### `/portfolio`
- **Header**: page title + last-marked-at timestamp + Refresh button (refetches
  `/portfolio/summary` + `/portfolio/positions`).
- **Account selector**: visible only when `accounts.length > 1`. Setting the
  default writes via `PATCH /portfolio/manual/accounts/{id}/default`.
- **Position table** (columns):
  Symbol · Exch · Qty · Sellable · Pending · Avg cost · Last px ·
  Mkt value · Unrealized · Unrealized % · Weight · Strategy tag · Note ·
  Actions (Edit, Delete).
- **Add/Edit position**: drawer on the right; inline forms allowed if simpler.
- **Allocation donut by symbol** (recharts `PieChart`).
- **Allocation donut by strategy tag** (recharts `PieChart`).
- **PnL bar chart by symbol** (recharts `BarChart`, two series: realized,
  unrealized).
- **Portfolio vs VNINDEX card** — `PlaceholderCard` (Phase 2 fills with
  computed series).
- **SSI Sync button** — visible, disabled, tooltip "Phase 2".

### `/assets-pnl` (current `/pnl` route renamed)
- **Asset cards** (7 cards in a 3- or 4-column grid):
  Settled cash · Pending cash · Cash advance · Stock MV · Total equity ·
  Buying power · Withdrawable.
- **Realized vs Unrealized** (recharts `BarChart`).
- **Fee/tax drag chart** (recharts `BarChart`, stacked: brokerage, VAT,
  sell tax, cash advance fee, slippage). Period selector `MTD | YTD | ALL`.
- **Net worth curve** — `PlaceholderCard` (Phase 2).
- **Cash movement timeline** — `PlaceholderCard` (Phase 2).
- **Settlement alerts** — `PlaceholderCard` placeholder (Phase 2 will render
  "3 trades settling T+2 on 2026-06-02" pulled from `trade_transactions`).

---

## 8. Empty-state UX (binding)

| Panel                                | Trigger                                     | What the user sees                                                  |
|--------------------------------------|---------------------------------------------|---------------------------------------------------------------------|
| Portfolio page (any panel)           | No accounts                                 | Single "Create an account" card; all other panels hidden.           |
| Position table                       | Account exists, 0 positions                 | Empty table with "Add your first position" CTA pointing at the form.|
| Allocation donut (by symbol/tag)     | 0 positions OR all market_value null        | Centered "No allocation data yet" caption inside the chart frame.   |
| Last-px / Mkt value column           | `market_price == null`                      | Render `—` + tooltip "Quote unavailable. Last attempt {ts}".        |
| Summary KPI (total_market_value etc.)| Any position has null quote                 | Render value with a yellow dot + warning chip count.                |
| Asset cards (cash)                   | No `cash_balances` row                      | Render `VND 0` with subdued "Not yet recorded" hint.                |
| Realized vs Unrealized chart         | 0 trades AND 0 positions                    | Placeholder copy "Log trades to see realized PnL".                  |
| Fee/tax drag chart                   | 0 trades in period                          | Placeholder copy "No trades in {period}".                           |
| /assets/pnl page                     | No default account                          | Single CTA card linking to `/portfolio` to create one.              |

---

## 9. Tests required (acceptance criteria)

### Backend (pytest)
- `test_position_crud_roundtrip` — POST → GET → PUT → DELETE preserves field
  values; default account is resolved.
- `test_summary_math_three_positions` — 3 positions; one with `market_price =
  None`; assert `total_market_value`, per-position pnl, and the warning string.
- `test_summary_empty_returns_zero_not_null` — 0 positions: totals are `0`,
  `positions_count == 0`, `warnings == []`.
- `test_realized_pnl_no_trades` — `realized_pnl_total == 0`,
  `trades_considered == 0`.
- `test_realized_pnl_one_sell` — 1 BUY 100@10, 1 SELL 100@12 → realized = 200 -
  fees.
- `test_realized_pnl_two_sells_weighted_avg` — 2 BUYs at different prices, then
  2 SELLs; assert weighted-average cost basis (not FIFO).
- `test_settlement_pending_vs_sellable` — BUY today: pending == qty, sellable
  == 0; BUY 3 days ago: pending == 0, sellable == qty.
- `test_ssi_sync_returns_501` — endpoint returns 501 with documented body.
- `test_period_filter_mtd_ytd_all` — `/assets/costs` and `/assets/pnl`
  respect period boundaries.

### Frontend (vitest + @testing-library/react)
- `portfolio.page.test.tsx` — renders position table from a mocked
  `/portfolio/positions` response; no console errors.
- `allocation.chart.test.tsx` — recharts donut renders with `[]` data without
  throwing (regression guard for the recharts-on-empty bug).
- `assets-pnl.page.test.tsx` — 7 asset cards render with mock `/assets/summary`.
- `pnl.chart.test.tsx` — bar chart renders with 0, 1, and 2 data points.
- `empty-state.test.tsx` — when `accounts.length == 0`, only the create-account
  card is visible.

---

## 10. Risks / open questions

### Risks (mitigations in place)
- **Quote cache contention**: N positions = N `/market/quote/{symbol}` reads.
  Mitigation: backend batches into `GET /market/quotes?symbols=...` (revisit
  if p95 > 500ms).
- **`avg_cost` drift**: user re-buys → `manual_positions.avg_cost` stale vs
  trade history. **Out-of-scope Phase 1**: user owns the field. Phase 2 adds
  a reconcile-from-trades action.
- **T+2 semantics**: HOSE/HNX/UPCoM equities settle T+2. Derivatives/bonds
  differ but are out of MVP scope (§2).
- **Fee/tax stored but not computed**: a user-entered `brokerage_fee = 0` will
  understate cost drag. UI shows a "fees not validated" badge in Phase 1.
- **RLS on new tables**: must mirror `manual_positions` policy via parent
  account. Highest-severity review checkpoint on `0002_*.sql`.

### Open questions for the user
1. **Default account override**: are we OK letting the first-created account
   silently win when `user_settings.default_account_id` is NULL, or should we
   force the user to pick on first login (modal gate)? The doc assumes silent
   fallback; flag if you want a hard gate.
2. **Period definitions for `/assets/costs` and `/assets/pnl`**: MTD/YTD
   based on **Asia/Ho_Chi_Minh wall clock** or UTC? Doc assumes Asia/HCMC.
   Confirm.
3. **Cash balances entry surface**: where does the user edit `cash_balances`
   in Phase 1? The doc lists the table and endpoints implicitly; an explicit
   "Edit cash balances" form is not in §7. Confirm whether to add a modal on
   `/assets-pnl` or defer to Phase 2 SSI sync.

---

## See also
- `docs/architecture.md` — module map (Plotly mention is stale, update here).
- `docs/api.md` — endpoint surface (this MVP adds the new routes above).
- Workspace `../../docs/product-vision.md`, `../../docs/trading-rules.md`.

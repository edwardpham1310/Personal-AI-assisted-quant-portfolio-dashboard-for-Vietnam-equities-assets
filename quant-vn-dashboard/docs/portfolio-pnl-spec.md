# Portfolio + PnL Spec (Phase 1)

> Companion to `docs/portfolio-assets-mvp.md`. That doc states *what* the team
> agreed to build; this doc nails down the *math* the backend computes and the
> *semantics* the frontend renders. Binding for Phase 1; deferrals are flagged.

---

## 1. Purpose & disclaimer

Phase 1 is a **manual, recommend-only** portfolio surface for Vietnam equities
(HOSE / HNX / UPCoM). The user records accounts, positions, cash buckets and
trade transactions; the backend marks them to market using the latest cached
quote and produces valuation + PnL + cost roll-ups.

- **Research only**. No order placement, no broker writes, no automated
  rebalancing. Every API response carries
  `"disclaimer": "Research only — not financial advice. No orders placed."`
- **VND only**. The `currency` column is reserved for future use; no FX in
  Phase 1.
- **Personal scale**. Designed for a single user with O(10) positions and
  O(100) trades per account — we do not paginate the math.

---

## 2. Inputs

All math is pure: a small set of dicts in, Pydantic models out. The inputs
come from four sources, in this priority:

| Source                  | Shape                          | Trust   |
|-------------------------|--------------------------------|---------|
| `manual_positions`      | Owner-edited rows              | High (user truth) |
| `cash_balances`         | One row per account (UPSERT)   | High (user truth) |
| `trade_transactions`    | Append-only ledger             | High (user truth) |
| Market quote cache      | Redis hot cache via `market_cache.get_quotes()` | **Possibly stale or missing** |

If a quote is missing or expired we return `null` (never zero, never NaN) and
emit a structured warning. Missing quotes never block the rest of the response.

---

## 3. Per-position valuation

Computed in `services/portfolio_valuation.py::enrich_position`. Formulas:

```
cost_basis         = quantity * avg_cost
market_value       = quantity * market_price          # null when market_price is None
unrealized_pnl     = market_value - cost_basis        # null when market_value is None
unrealized_pnl_pct = unrealized_pnl / cost_basis      # null when cost_basis <= 0
weight             = market_value / total_market_value # null when mv is null or total <= 0
```

Null-handling rules:

- `market_price is None` ⇒ `market_value`, `unrealized_pnl`,
  `unrealized_pnl_pct` are all `null` and the warning `"quote_missing"` is
  attached to the position.
- `cost_basis == 0` (e.g. rights issue with `avg_cost = 0`) ⇒
  `unrealized_pnl_pct = null`, **not** `inf`.
- The position row is still returned even when its quote is missing — the UI
  renders `—` and a tooltip.

---

## 4. Portfolio summary

`compute_summary(positions, quotes)` returns a `PortfolioSummary`:

| Field                       | Definition                                                     |
|-----------------------------|----------------------------------------------------------------|
| `total_market_value`        | Sum of `market_value` over priced positions only               |
| `total_cost_basis`          | Sum of `quantity * avg_cost` over **all** positions            |
| `total_unrealized_pnl`      | `total_market_value - total_cost_basis`                        |
| `total_unrealized_pnl_pct`  | `total_unrealized_pnl / total_cost_basis` (null if cost ≤ 0)   |
| `by_strategy_tag`           | `{tag → sum(market_value)}`, only priced positions; null tag bucketed as `"untagged"` |
| `warnings`                  | One `"quote_missing:<SYMBOL>"` per unpriced position           |
| `last_marked_at`            | `max(quote.ts)` across priced positions (ISO-8601, UTC-aware)  |
| `position_count`            | Count of input positions (priced or not)                       |

**Cost-basis asymmetry**: cost is always known so we always include it. Market
value is only summed for priced positions — that produces a known
underestimate when quotes are missing, which is preferable to a misleading
"complete" total. The warning list lets the UI surface that gap.

---

## 5. Realized PnL — weighted-average cost method

Computed in `realized_pnl_from_trades(trades)`. Rules:

1. **Sort key** — chronological by `(trade_date, created_at)`. Both are
   stringified and tuple-compared, so deterministic for ISO-8601 dates and
   ISO-8601 timestamps. Inserts on the same day fall back to `created_at`.
2. **State** — running `(quantity, avg_cost)` per `(account_id, symbol)`. The
   same symbol in two accounts is tracked independently.
3. **BUY** —
   ```
   new_qty = cur_qty + qty
   avg_cost ← (cur_qty * cur_avg + qty * price) / new_qty   # if new_qty > 0
   ```
4. **SELL** —
   ```
   realized += sell_qty * (sell_price - avg_cost)
   cost_basis_at_sell += sell_qty * avg_cost
   cur_qty -= sell_qty
   # avg_cost is preserved on a partial sell; reset to 0 only when the lot is flat.
   ```
5. **Fees are NOT subtracted from realized PnL** in Phase 1. They are tracked
   independently via `/assets/costs`. The PM decision doc §5 lists the
   fee-netted formula as binding for the *narrative layer*; the implementation
   currently surfaces gross realized only. **This is a known Phase 1
   simplification** — see §10.
6. **Oversold clamp (defensive)** — if a SELL row references more shares than
   the running quantity, the model clamps the executed quantity to
   `min(sell_qty, cur_qty)` rather than going negative. This protects against
   user data-entry errors and missing prior BUY rows (e.g. positions migrated
   in via `manual_positions` only). The clamp is **silent in Phase 1** (no
   warning is emitted); Phase 2 should emit `"oversold_clamp:<SYMBOL>"`.
7. **Output** —
   ```
   {
     "total_realized": float,
     "by_symbol": {symbol: {"realized": float, "cost_basis_at_sell": float}}
   }
   ```

Trades with `quantity <= 0` are skipped (schema-enforced upstream, but the
service still guards).

---

## 6. Assets summary

`GET /assets/summary` returns an `AssetsSummary`:

```
stock_market_value     = sum(EnrichedPosition.market_value)
                         # null positions are excluded from the sum
                         # and emit a "quote_missing:<SYM>" warning
total_equity           = settled_cash
                       + pending_cash
                       + advanced_cash
                       + stock_market_value
                       - cash_advance_liability
available_buying_power = settled_cash      # Phase 1 conservative
withdrawable_cash      = cash_balances.withdrawable_cash   # stored field, not computed
```

`available_buying_power` deliberately excludes `advanced_cash`. The cash
advance product carries a per-day fee plus a liability bucket; treating it as
ordinary buying power would encourage overstating capacity. The UI may surface
"+ X VND advance available" as a separate line so the user sees the option
without losing the conservative anchor.

`total_equity` *includes* `advanced_cash` and *subtracts*
`cash_advance_liability` so the net effect of an open advance is zero on
equity — only the cost (fee) deducts equity, via `/assets/costs`.

---

## 7. T+2 settlement model (Vietnam)

HOSE / HNX / UPCoM equity settles on `T+2`. The PM doc §2 specifies:

```
sellable_quantity = sum(BUY.qty where settlement_date <= today) - sum(SELL.qty matched)
pending_quantity  = sum(BUY.qty where settlement_date >  today)
```

**Current state (Phase 1)**: `sellable_quantity`, `pending_quantity` and
`pending_cash` columns exist on `manual_positions` / `cash_balances` (see
migration `0002_portfolio_assets.sql`), but they are **stored, not
auto-computed**. The valuation service reads whatever the user (or a future
sync) wrote; it does not derive them from `trade_transactions + today's date`.

**Gap to close in Phase 2**: a settlement-derivation pass in
`portfolio_valuation` or a nightly job that recomputes settlement state from
`trade_transactions.settlement_date` and updates the snapshot tables. Until
then, a user logging BUY/SELL rows will see settlement fields stuck at zero
unless they edit them manually. **The UI should flag this** — see §10.

---

## 8. Costs

Phase 1 stores fee/tax fields on `trade_transactions` and aggregates them in
`/assets/costs`:

| Field               | Source column                       |
|---------------------|-------------------------------------|
| `brokerage_fee`     | `trade_transactions.brokerage_fee`  |
| `vat`               | `trade_transactions.vat`            |
| `sell_tax`          | `trade_transactions.sell_tax`       |
| `cash_advance_fee`  | `trade_transactions.cash_advance_fee` |
| `slippage_estimate` | `trade_transactions.slippage_estimate` |
| `total`             | Sum of the five above               |
| `trade_count`       | Number of trades counted            |

These values are **not** subtracted from realized PnL in Phase 1 (see §5). The
narrative layer must caveat realized PnL as gross-of-fees.

---

## 9. Period definitions (MTD / YTD / ALL)

Per the PM doc Q2 the agreed boundary is **Asia/Ho_Chi_Minh wall clock**.

**Current implementation**: `cost_breakdown(..., today=None)` defaults to
`datetime.now(timezone.utc).date()`. That is a UTC date, not Asia/HCMC. The
difference is up to 7 hours; for the first 7 hours of a HCMC local day the
UTC date is still the previous day, which would silently exclude trades from
their natural MTD/YTD bucket on month/year boundaries. **This is a bug** — see
findings report.

Boundary rule (target):

- `MTD` = trades where `trade_date >= first_of_month(today_local)`
- `YTD` = trades where `trade_date >= first_of_year(today_local)`
- `ALL` = no date filter

`today_local` must be derived via `ZoneInfo("Asia/Ho_Chi_Minh")`, not UTC.

---

## 10. Known limitations (Phase 1)

1. **No FIFO/LIFO tax-lot identification** — weighted average only. Tax export
   is out of scope.
2. **No corporate-action or dividend tracking** — splits, bonus shares, cash
   dividends are not reflected in `avg_cost` or realized PnL.
3. **Fees not netted from realized PnL** — gross realized only; net realized
   is the user's mental arithmetic until Phase 2.
4. **T+2 not auto-derived from `trade_date`** — `sellable_quantity` /
   `pending_quantity` / `pending_cash` are stored snapshots, not computed.
5. **`avg_cost` on `manual_positions` is not updated by BUY trades** — the
   user owns that field. Phase 2 adds a "reconcile from trades" action.
6. **No multi-currency** — VND only. `currency` column is stored but ignored.
7. **No regime adjustment / drawdown / risk metrics** — no Sharpe, no max
   drawdown, no VaR, no exposure-by-sector.
8. **Period boundary uses UTC, not Asia/HCMC** — see §9; boundary skew up to
   7h on month/year edges.
9. **Oversold clamp is silent** — no warning emitted when a SELL exceeds
   running quantity.
10. **`stock_market_value` understates when quotes are missing** — sum
    excludes unpriced positions; the warning list disclaims it but a single
    aggregate KPI can still mislead.

The UI must surface (1)–(4) explicitly on the relevant cards in Phase 1.

---

## 11. Tuning notes — Phase 2 candidates

- **FIFO option** alongside weighted-average, user-selectable per account.
- **Fee-netted realized PnL** — subtract `brokerage_fee + vat + sell_tax`
  from realized at SELL time; keep gross as a secondary display.
- **Auto T+2 derivation** — compute `sellable_quantity` / `pending_quantity`
  / `pending_cash` from `trade_transactions.settlement_date` on read.
- **Dividend stream** — new `cash_events` table; mark `avg_cost` adjustments
  for bonus shares.
- **Settlement alerts** — list trades whose `settlement_date <= today + N`.
- **Oversold-clamp warning** — emit `"oversold_clamp:<SYMBOL>"` for review.
- **Asia/HCMC period boundaries** — fix the timezone bug from §9.
- **Multi-account `/assets/*`** — currently default-account only.

---

## 12. References

- `docs/portfolio-assets-mvp.md` — PM decision doc (binding for Phase 1).
- `docs/architecture.md` — workspace module map.
- `../../docs/trading-rules.md` — no-lookahead rule (signal at T → execute at
  T+1 open) — applies to the strategy/backtest packages, not this surface,
  but informs the "research only" stance.
- `../../docs/product-vision.md` — personal AI-assisted quant portfolio for
  Vietnam equities, SSI-first, recommend-only.
- `apps/api/src/services/portfolio_valuation.py` — implementation.
- `apps/api/tests/test_portfolio_valuation.py` — unit coverage.
- `db/migrations/0002_portfolio_assets.sql` — schema.

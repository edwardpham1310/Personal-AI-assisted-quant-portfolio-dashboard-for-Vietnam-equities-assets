# Phase 2 — Vietnam Cost, Settlement, Cash Advance & Recommendation Validation

**Date:** 2026-05-28
**Author:** Claude Code (agent-driven implementation)
**Scope:** Implementation of Phase 1 architecture for Vietnam-specific cost,
tax, VAT, settlement (T+2), cash advance (ứng trước tiền bán), execution
rules, portfolio ledger, and recommendation validation.

---

## 1. What Changed

### New packages
- `quant_vn.costs` — VAT, taxes, brokerage, slippage, cash advance, transaction facade
- `quant_vn.execution` — pre-trade validation rules
- `quant_vn.portfolio` — settlement-aware portfolio ledger
- `quant_vn.recommendation` — BUY/SELL recommendation validator

### New modules
- `quant/src/quant_vn/costs/__init__.py`
- `quant/src/quant_vn/costs/vat.py` — VATModel (10% default, double-count prevention)
- `quant/src/quant_vn/costs/taxes.py` — SellTaxModel (0.1%), DividendTaxModel (5%), StockDividendTaxModel placeholder
- `quant/src/quant_vn/costs/brokerage.py` — FlatFeeModel, TieredFeeModel, BrokerFeeProfile (SSI, VNDIRECT factories)
- `quant/src/quant_vn/costs/slippage.py` — FixedBps, LiquidityBucket, ParticipationRate models
- `quant/src/quant_vn/costs/cash_advance.py` — CashAdvanceModel with daily/annualized/flat fee modes
- `quant/src/quant_vn/costs/transaction.py` — TransactionCostModel facade
- `quant/src/quant_vn/market/settlement.py` — SettlementLedger, SettlementRule, AssetType, PendingCashStatus
- `quant/src/quant_vn/execution/rules.py` — check_lot_size, check_price_limits, check_cash_sufficiency, check_sellable_shares, check_liquidity, run_all_checks
- `quant/src/quant_vn/portfolio/ledger.py` — PortfolioLedger with settled vs unsettled tracking
- `quant/src/quant_vn/recommendation/validator.py` — RecommendationValidator with full BUY/SELL guardrails

### Updated modules
- `quant/src/quant_vn/market/calendar.py`: extended `_TET_HOLIDAYS` to 2030,
  fixed `_HUNG_KINGS_DAY` (was hardcoded April 18 — now varies by year per
  lunar calendar)
- `quant/src/quant_vn/backtest/execution.py`: `allow_fractional_shares`
  default changed from `True` to `False`; `compute_quantity` now rounds down
  to 100-share lots
- `quant/src/quant_vn/market/costs.py`: docstring updated; remains the
  legacy flat-cost dataclass for backward compatibility

### New config
- `quant/config/market_vietnam.yaml` — full Vietnam market config:
  market rules, lot size, taxes, VAT, liquidity, slippage, price limits,
  cash advance, broker profiles (SSI, VNDIRECT, CUSTOM), broker cash advance
  profiles

### New documentation
- `quant/docs/vietnam-market-costs.md` — Vietnam market reference document
  with: T+2 settlement, cash advance, brokerage fees, VAT, taxes, slippage,
  liquidity filter, price limits, lot size, recommendation validation rules,
  output fields, manual verification checklist, known limitations, references

### New tests (164 added)
- `tests/test_costs_vat.py` (12)
- `tests/test_costs_taxes.py` (15)
- `tests/test_costs_brokerage.py` (19)
- `tests/test_costs_cash_advance.py` (14)
- `tests/test_costs_transaction.py` (15)
- `tests/test_market_settlement.py` (23)
- `tests/test_execution_rules.py` (34)
- `tests/test_portfolio_ledger.py` (9)
- `tests/test_recommendation_validator.py` (13)
- `tests/test_phase2_review_fixes.py` (15) — regression tests for review fixes

**Total: 239 tests passing (70 original + 169 new).**

---

## 2. Formulas Implemented

### Transaction value
```
transaction_value = matched_price × quantity
```

### Buy side
```
gross_buy_value      = price × quantity
brokerage_fee        = max(gross_buy_value × tier_rate, min_fee_vnd)
vat                  = brokerage_fee × vat_rate    (if not fee_includes_vat AND enabled)
slippage_cost        = gross_buy_value × slippage_rate
total_buy_cost       = brokerage_fee + vat + slippage_cost
total_cash_required  = gross_buy_value + total_buy_cost
```

### Sell side
```
gross_sell_value     = price × quantity
brokerage_fee        = max(gross_sell_value × tier_rate, min_fee_vnd)
vat                  = brokerage_fee × vat_rate    (if not fee_includes_vat AND enabled)
sell_tax             = gross_sell_value × 0.001    (0.1% of GROSS, NOT net)
slippage_cost        = gross_sell_value × slippage_rate
total_sell_cost      = brokerage_fee + vat + sell_tax + slippage_cost
net_sell_proceeds    = gross_sell_value - total_sell_cost
```

### Realized PnL (post C1 fix)
```
cost_basis_per_share = price + (brokerage_fee + vat) / quantity   # slippage EXCLUDED
allocated_cost_basis = cost_basis_per_share × quantity_sold
realized_pnl         = net_sell_proceeds - allocated_cost_basis
net_return_pct       = realized_pnl / allocated_cost_basis
```

### Cash advance
```
daily_rate           = annualized_rate / day_count_basis   (use 365, not 252)
fee_before_vat       = max(advanced_amount × daily_rate × advance_days, minimum_fee)
vat                  = fee_before_vat × vat_rate    (if not fee_includes_vat AND vat_enabled)
total_advance_fee    = fee_before_vat + vat
net_advanced_cash    = advanced_amount - total_advance_fee
```

### Buying power
```
buying_power = settled_cash
unless allow_use_unsettled_cash = true OR cash advance applied
```

### Sellable quantity
```
sellable = settled_shares
unless allow_sell_unsettled_shares = true
```

---

## 3. Settlement Behavior

- T+2 = 2 Vietnam trading days (weekends + holidays skipped)
- BUY on T: cash deducted immediately; bought shares enter pending until T+2
- SELL on T: shares removed immediately; net proceeds enter pending until T+2
- ADVANCED entries (via cash advance): credited immediately as settled, NOT
  re-credited at settlement date (double-count prevention)
- Default: `allow_use_unsettled_cash = false`, `allow_sell_unsettled_shares = false`

---

## 4. Cash Advance Behavior

- Disabled by default
- Three fee models: daily_interest, annualized_rate, flat_fee
- Optional minimum fee with `max()` override
- VAT optional, with `fee_includes_vat` flag for double-count prevention
- Pending sell entry marked ADVANCED when advance drawn
- ADVANCED entries do NOT re-credit cash at settlement (no duplicate cash)
- `max_advance_pct_of_pending_sell_proceeds` enforced

---

## 5. Review & Fixes

The implementation was reviewed by three independent agents
(Reality Checker, Quant Researcher, QA Engineer). Critical and high-priority
bugs were fixed before final sign-off.

### Critical bugs fixed
- **C1 — Cost basis included slippage** (portfolio/ledger.py):
  per Phase 1 spec, cost basis = entry_price × qty + brokerage + VAT only.
  Slippage is already embedded in the execution price. Fix removed slippage
  from cost_basis_per_share calculation. Without fix: realized PnL
  understated by ~10 bps per round trip.
- **C2 — `available_cash_on` / `available_shares_on` ignored as_of_date**
  (market/settlement.py): the methods returned the current settled cash
  without auto-advancing. Fix: both methods now call `advance_date(as_of_date)`
  internally so they are date-aware. Without fix: validator could reject
  trades that should have been valid post-settlement.
- **C3 — `PendingSharesEntry.settled` was a monkeypatch attribute**
  (market/settlement.py): replaced with proper dataclass field for
  serialization safety and idempotency.

### High-priority bugs fixed
- **H1 — Sell-side validator missing liquidity check** (recommendation/validator.py):
  large sell orders had no impact warning. Fix: `_validate_sell` now runs
  `check_liquidity`, mirroring `_validate_buy`.
- **H3 — `record_buy` / `record_sell` did not validate dates**
  (market/settlement.py): callers could pass `settlement_date < trade_date`
  causing silent corruption. Fix: both methods now raise `ValueError` if
  settlement_date precedes trade_date or quantity is non-positive.
- **H4 — `fee_includes_vat=None` silently defaulted to False**
  (costs/transaction.py): broker profile factories use `None` to mean
  "unverified". The transaction model silently treated `None` as `False`,
  potentially inflating cost estimates by 10% if reality was VAT-inclusive.
  Fix: emits explicit `UserWarning` when `None` is detected.
- **H5 — Validator hardcoded `advance_days=2`** (recommendation/validator.py):
  for a Friday sell, T+2 settlement is 4 calendar days away
  (Fri→Tue). Hardcoded 2 understated the advance fee by ~50% over weekends.
  Fix: validator now computes `(settlement_date - trade_date).days`.
- **H7 — `check_lot_size` truncated floats silently** (execution/rules.py):
  `int(100.5)` → 100, which was treated as a valid 100-lot. Fix: explicit
  detection of fractional floats with `LOT_SIZE_VIOLATION`.

### Confirmed correct (no fix needed)
- Sell tax on GROSS value, not net-of-brokerage
- VAT NOT applied to sell tax (it is a statutory tax, not a service fee)
- VAT NOT applied to slippage (it is market impact, not a service fee)
- VAT double-count prevention via `fee_includes_vat=True` flag
- Cash advance ADVANCED entries do not re-credit at settlement
- HOSE ±7%, HNX ±10%, UPCoM ±15% price limits
- T+2 uses trading days, not calendar days, skipping weekends and holidays
- Tet 2026 and Hung Kings Day 2026 properly in the calendar
- `from_legacy()` reproduces the exact old TransactionCosts arithmetic
- Backward compatibility: all 70 original tests continue to pass

---

## 6. Remaining Limitations

These are documented as known limitations and reserved for Phase 3 or later:

1. **No dividend modeling in backtest engine.** Dividend income is not
   credited, dividend tax is not deducted. Affects buy-and-hold of
   dividend-paying stocks. The DividendTaxModel exists and is testable;
   wiring it into the backtest engine is deferred.
2. **No T+2 enforcement in vectorized backtest engine.** SettlementLedger,
   PortfolioLedger, and RecommendationValidator enforce T+2. The vectorized
   BacktestEngine continues to treat cash as immediately available
   (documented limitation). Recommendation: use the validator for live
   recommendations.
3. **No multi-symbol portfolio backtest.** Single-symbol engine remains.
4. **Stock dividend tax model raises `NotImplementedError`** — rules require
   manual verification before implementation.
5. **No automatic loading of `market_vietnam.yaml`** — file is documentation
   and reference template; no YAML loader wired into Python modules in this
   phase. Configurations must be constructed programmatically via factory
   methods (e.g. `BrokerFeeProfile.ssi_active_online()`).
6. **Slippage models are approximate.** Fixed-bps and liquidity-bucket
   underestimate impact for very large orders or illiquid names.
7. **Walk-forward capital reset** between IS and OOS windows is not changed.
8. **Cash advance advance_days uses calendar days** — verify with your broker
   that this matches their fee calculation convention.

---

## 7. Manual Verification Required Before Use

Before using the new system for any real-money decision, complete the manual
verification checklist in `quant/docs/vietnam-market-costs.md` section 13.
At minimum verify:

- [ ] Your exact broker fee rate
- [ ] Whether your broker's published rate includes VAT
- [ ] Current VAT rate (10% as of 2024)
- [ ] Current sell-side tax rate (0.1% as of 2024)
- [ ] Current dividend tax rate (5% as of 2024)
- [ ] Whether cash advance is available at your broker and at what rate
- [ ] T+2 settlement cycle confirmed
- [ ] Lot size confirmed (100 shares on HOSE/HNX)

---

## 8. Test Results

```
$ python3 -m pytest tests/ -q
============================= 239 passed in 0.47s ==============================
```

**Breakdown:**
- 70 original tests (backtest engine, metrics, strategies, indicators, data, dashboard)
- 154 new Phase 2 tests
- 15 regression tests for post-review fixes (C1, C2, C3, H1, H3, H4, H5, H7)

All tests pass on commit.

---

## 9. Backward Compatibility

- `from quant_vn.market.costs import TransactionCosts, DEFAULT_COSTS` still works
- The `TransactionCosts` dataclass arithmetic is unchanged (verified by
  `test_from_legacy_matches_old_arithmetic`)
- BacktestEngine continues to use `TransactionCosts.buy_cost(notional)` /
  `sell_cost(notional)` returning floats — no engine changes required
- New code should use `quant_vn.costs.TransactionCostModel` and related
  components

---

## 10. Disclaimer

- For research only. NOT financial advice. NOT tax advice. NOT legal advice.
- Defaults are 2024 statutory rates and approximate broker rates.
- Verify all rates with your actual broker and Vietnamese authorities before
  any investment decision.
- Tax rules, market rules, and fee schedules change over time. Update the
  audit trail when rates change.

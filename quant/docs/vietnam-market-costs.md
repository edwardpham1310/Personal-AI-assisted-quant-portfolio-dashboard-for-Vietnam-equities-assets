# Vietnam Market Costs, Taxes, Settlement & Recommendation Validity

This is the authoritative reference for all Vietnam-market-specific cost,
tax, settlement, and trading rules used by the `quant_vn` system.

> **⚠️ DISCLAIMER — Read First**
>
> This document is for **research purposes only**. It is NOT financial advice,
> tax advice, legal advice, or investment recommendation.
>
> - All rates, formulas, and assumptions described here MUST be verified
>   manually against your actual broker, your account contract, and the
>   relevant Vietnamese tax/regulatory authorities before use.
> - Market rules, tax rates, fee schedules, and broker terms CHANGE OVER TIME.
> - The defaults shipped with this codebase represent rates as of 2024 and may
>   be out of date.
> - No recommendation produced by this system constitutes a recommendation to
>   trade in real markets.
>
> Complete the **Manual Verification Checklist** (section 13) before relying
> on any backtest result or recommendation.

---

## 1. T+2 Settlement

### What it means

Vietnam HOSE and HNX use a **T+2 trading-day settlement cycle** for ordinary
listed stocks and ETFs as of 2024. Settlement date is computed by adding 2
TRADING days (skipping weekends and exchange holidays) to the trade date.

### Concepts

| Term | Meaning |
|---|---|
| **Settled cash** | Cash available immediately for new buys |
| **Pending cash** | Sell proceeds not yet at T+2 — NOT available for new buys |
| **Advanced cash** | Pending cash drawn early via cash advance — already credited as settled |
| **Settled shares** | Shares delivered (T+2 passed) — available to sell |
| **Pending shares** | Shares from recent buys not yet at T+2 — NOT sellable |

### Default behavior

By default the system enforces:

```yaml
market:
  allow_sell_unsettled_shares: false
  allow_use_unsettled_cash: false
```

A BUY recommendation will be rejected if there is not enough **settled** cash
to cover the order. A SELL recommendation will be rejected if there are not
enough **settled** shares.

If pending cash exists but settled is insufficient, the validator issues a
warning explaining that cash advance (ứng trước tiền bán) is required.

### Examples

| Trade Date | Settlement Date | Notes |
|---|---|---|
| 2024-01-08 (Mon) | 2024-01-10 (Wed) | Standard T+2 |
| 2024-01-05 (Fri) | 2024-01-09 (Tue) | Skips Sat/Sun |
| 2026-02-13 (Fri) | 2026-02-23 (Mon) | Skips Tet 2026 block Feb 16–20 |
| 2024-04-17 | 2024-04-22 | Skips Hung Kings Day Apr 18 |

---

## 2. Cash Advance (Ứng Trước Tiền Bán Chứng Khoán)

### What it is

A broker service allowing investors to access pending sell proceeds BEFORE the
normal T+2 settlement date. The broker effectively lends the amount and
charges an interest fee.

### Why it reduces real performance

Every backtest that "rotates" capital between positions (sell A, buy B the
next day) implicitly uses cash advance in real life — the proceeds from
selling A are not available to buy B until T+2 unless the investor draws an
advance. The advance has a real cost:

- Daily interest: typically 0.03% to 0.05% per day at major brokers
- Or annualized: typically 14-18% per year
- Often with a minimum fee per advance request
- Plus 10% VAT on the fee unless already included

For a strategy with 4-5 rotations per month on a 100M VND portfolio, this
adds up to approximately **1-1.5% per year in missing fees** that vanilla
backtest results do not capture.

### Default behavior

Cash advance is **DISABLED by default**. Enable it explicitly only after:
1. Confirming with your broker that the service is available
2. Verifying the exact rate and minimum fee
3. Confirming whether VAT is included in the rate

### Fee formulas

**Daily interest model:**
```
fee_before_vat = max(advanced_amount × daily_rate × advance_days, minimum_fee)
```

**Annualized model:**
```
daily_rate = annualized_rate / 365   # NOT 252
fee_before_vat = max(advanced_amount × daily_rate × advance_days, minimum_fee)
```

**Flat fee model:**
```
fee_before_vat = max(advanced_amount × flat_fee_rate, minimum_fee)
```

**VAT on advance fee:**
```
if vat_enabled and not fee_includes_vat:
    vat = fee_before_vat × vat_rate
else:
    vat = 0

total_advance_fee = fee_before_vat + vat
net_advanced_cash = advanced_amount - total_advance_fee
```

### Double-counting prevention

When an advance is drawn on a pending sell entry:
1. The entry is marked **ADVANCED** in the settlement ledger
2. The net advance cash is credited to **settled_cash** immediately
3. At settlement date (T+2), **NO additional cash** is added — the advance
   already credited the cash

Failing to enforce step 3 causes silent double-counting of cash.

---

## 3. Brokerage Fee

### Vietnamese broker fee structures

Two common models:

**Flat rate** (e.g., SSI ACTIVE online retail): single percentage rate per
trade, e.g., 0.15% of transaction value, with a minimum fee.

**Tiered by daily traded value** (e.g., VNDIRECT DBA broker-assisted): the
rate depends on cumulative daily traded value across all orders. The tier
rate applies to the **FULL order notional** once a daily threshold is reached
— this is **NOT** a marginal/income-tax-bracket system.

### Default

```yaml
# config/market_vietnam.yaml
broker_profiles:
  CUSTOM:
    fee_model: flat
    brokerage_fee_rate: 0.0015  # 0.15%
    min_fee_vnd: 0
    brokerage_fee_includes_vat: false
```

### VERIFY

- Your exact rate for your account package
- Whether your published rate INCLUDES VAT (very important — setting this
  wrong causes systematic VAT mis-counting in either direction)
- Your minimum fee
- Whether your trading channel (online vs broker-assisted) affects the rate
- Whether negotiated rates apply

### Formula

```
gross_value     = matched_price × quantity
brokerage_fee   = max(gross_value × tier_rate, min_fee_vnd)
```

---

## 4. VAT

### What applies

Vietnam VAT (Thuế Giá Trị Gia Tăng) applies to **brokerage service fees** as
a service tax. As of 2024 the rate is **10%**.

### What does NOT apply

VAT does NOT apply to:
- The 0.1% sell-side securities transfer tax (it is a statutory tax, not a
  service fee)
- Slippage (slippage represents market impact, not a service charge)
- The matched transaction value itself

### Logic

```
if fee_includes_vat is True:
    vat = 0   # already embedded in the rate
elif vat_enabled is True:
    vat = brokerage_fee_before_vat × vat_rate
else:
    vat = 0
```

### Double-counting risk

If your broker quotes 0.165% as the all-in rate (0.15% + 10% VAT bundled),
set `fee_includes_vat: true`. If you set `fee_includes_vat: false` and quote
0.165%, the system will add another 10% on top → 0.1815% effective → wrong.

### VERIFY

The single most error-prone setting in this entire system. Look at one of
your actual trade confirmations from your broker. Compute:
`fee_charged / transaction_value`. Compare to your published rate.

- If `fee_charged / transaction_value ≈ rate`: fee includes VAT
- If `fee_charged / transaction_value ≈ rate × 1.10`: fee excludes VAT

---

## 5. Sell-Side Personal Income Tax

### What it is

The 0.1% securities transfer tax (Thuế thu nhập cá nhân từ chuyển nhượng
chứng khoán) is a statutory tax on every sale of listed securities,
regardless of profit or loss, withheld at the point of sale by the broker.

**Legal basis:** Law on Personal Income Tax No. 04/2007/QH12, Article 11;
amended by Law No. 26/2012/QH13.

### Formula

```
sell_tax = gross_sell_value × 0.001
```

Applied to GROSS sell value (before deducting brokerage fee). This is
important: the tax base is the matched transaction value, NOT the net cash
proceeds.

### NOT applicable

- Buy trades (sell tax is sell-side only)
- Annual declaration alternative (20% on actual profit) — used by some
  professional investors but NOT modeled in this system

---

## 6. Dividend Income Tax

### What it is

A 5% personal income tax on cash dividends paid by listed Vietnamese
companies, withheld at source before the dividend reaches the investor.

**Legal basis:** Law on Personal Income Tax, Article 10.

### Formula

```
dividend_tax = cash_dividend_gross × 0.05
net_dividend = cash_dividend_gross - dividend_tax
```

### Stock dividends and bonus shares

**Status:** Placeholder only. `StockDividendTaxModel` raises
`NotImplementedError`.

The accepted treatment (must be verified):
- Stock dividends and bonus shares are NOT taxed at receipt.
- The cost basis of those shares is ZERO.
- When eventually sold, the 0.1% securities transfer tax applies to the full
  gross sell value (same as normal sell tax).

The system does not yet model dividend income in the backtest engine. This
is a known limitation — see Section 14.

---

## 7. Slippage

Slippage represents the cost of market impact and bid-ask spread. It is
modeled separately from brokerage fees.

### Formulas

```
Buy execution price  = reference_price × (1 + slippage_rate)
Sell execution price = reference_price × (1 - slippage_rate)
slippage_cost        = |effective_price - reference_price| × quantity
                     = notional × slippage_rate
```

### Models

- **Fixed bps** (default): constant rate for all stocks. Underestimates
  impact for illiquid stocks and large orders.
- **Liquidity bucket**: different bps per ADV bucket (HIGH/MEDIUM/LOW).
- **Participation rate** (placeholder): not calibrated for Vietnam data.

### Default

```yaml
slippage:
  model: liquidity_bucket
  high_liquidity_bps: 10
  medium_liquidity_bps: 25
  low_liquidity_bps: 50
```

VAT does NOT apply to slippage — it is market impact, not a service fee.

---

## 8. Liquidity Filter

A research-time gate that rejects recommendations on illiquid stocks or
orders that are too large relative to average daily volume.

### Default thresholds

```yaml
liquidity:
  min_avg_value_20d: 5_000_000_000   # 5B VND
  min_price: 5_000                    # avoid penny stocks
  max_zero_volume_days_20d: 2
  max_order_adv_pct: 0.05            # 5% of ADV per order
```

### Logic

A recommendation is rejected (or warned) if:
- `avg_value_20d < min_avg_value_20d`, OR
- `order_value > avg_value_20d × max_order_adv_pct`

---

## 9. Price Limits (Ceiling/Floor)

Daily price band rules set by HOSE/HNX/UPCoM:

| Exchange | Daily Limit |
|---|---|
| HOSE | ±7% |
| HNX | ±10% |
| UPCoM | ±15% |

Computed from the previous session close (reference_price). A BUY at a price
above the ceiling, or a SELL below the floor, is rejected by the validator.

New listings have different first-day limits (±20% or wider on some
instruments). This system uses the standard limits — verify if you trade
newly listed stocks.

---

## 10. Lot Size

### Standard

HOSE and HNX board lot is **100 shares**. Orders must be in multiples of 100.

### Odd lots

A separate odd-lot board exists (1–99 shares) with different matching rules,
worse liquidity, and may require broker assistance. **Not modeled in MVP.**

### Default policy

```yaml
lot_size:
  default: 100
  odd_lot_supported: false
  invalid_lot_policy: round_down   # or "reject"
```

If quantity is not a valid lot multiple, the validator either rounds down
or rejects depending on config.

---

## 11. Recommendation Validation Rules

### BUY recommendation passes only if:

1. Symbol passes liquidity filter
2. Order value ≤ `avg_daily_value_20d × max_order_adv_pct`
3. Quantity is a valid lot multiple (no fractional shares)
4. Order price is within ceiling/floor (if reference available)
5. `total_cash_required` (notional + brokerage + VAT + slippage) ≤ settled_cash
6. If settled cash is insufficient AND pending cash exists:
   - If `allow_auto_advance_for_buying_power = false` → reject with warning
   - If `allow_auto_advance_for_buying_power = true` → compute advance cost
     and include in output

### SELL recommendation passes only if:

1. Settled shares ≥ requested quantity (pending shares do NOT count by
   default)
2. Quantity is a valid lot multiple
3. Order price within ceiling/floor
4. Output includes: net pending proceeds, settlement date, and cash advance
   option (if enabled)

---

## 12. Recommendation Output Fields

Every recommendation produces:

**Common:**
- action (BUY/SELL)
- symbol, quantity, price, exchange
- broker profile, tax profile, slippage model
- settlement date, settlement rule
- warnings list
- rejection reason if invalid

**BUY-specific:**
- settled_cash, pending_cash
- brokerage_fee, vat_amount, slippage_cost
- total_cash_required
- (if advance) estimated_advance_amount, fee, vat, net cash

**SELL-specific:**
- sellable_shares (settled only), pending_shares
- gross_sell_value, brokerage_fee, vat, sell_tax, slippage
- net_proceeds (pending until T+2)
- settlement_date
- (if advance enabled) estimated advance fee for immediate access

---

## 13. Manual Verification Checklist

Complete this before relying on any backtest or recommendation output.

### Broker & Commission

- [ ] My broker: ______ (SSI / VNDIRECT / TCBS / VPS / HSC / MBS / Other)
- [ ] My account package: ______ (Standard / Active / DTA / DBA / VIP / etc.)
- [ ] My trading channel: ______ (Online / Mobile / Broker-assisted)
- [ ] Fee schedule confirmed dated: ______
- [ ] Commission rate: ______% (or tier table documented)
- [ ] Minimum commission fee per transaction: ______ VND
- [ ] Commission applies identically to buy and sell: yes / no
- [ ] **Fee schedule is VAT-inclusive: yes / no** (CRITICAL — wrong setting causes double-counting)
- [ ] Negotiated rate different from published: yes / no

### VAT

- [ ] Current VAT rate on brokerage services: ______ % (10% as of 2024)
- [ ] VAT applies to cash advance fee at my broker: yes / no / unknown

### Securities Transfer Tax (Sell-side)

- [ ] Current rate: ______ % (0.1% as of 2024, statutory)
- [ ] Confirmed applied to gross sell value (not net): yes
- [ ] Confirmed broker withholds at point of sale: yes / no

### Dividend Tax

- [ ] Current dividend tax rate: ______ % (5% as of 2024)
- [ ] Confirmed: stock dividends NOT taxed at receipt, cost basis = 0
- [ ] Acknowledged: dividend income NOT yet modeled in backtest (Phase 3)

### Settlement

- [ ] Settlement cycle for stocks: T+ ______ (T+2 as of 2024)
- [ ] Settlement cycle for ETFs: T+ ______
- [ ] Settlement cycle for fund certificates: T+ ______
- [ ] Settled proceeds available: morning / afternoon T+2 (verify time)

### Cash Advance (Ứng Trước Tiền Bán)

- [ ] Service available at my broker: yes / no
- [ ] Service name: ______
- [ ] Fee model: daily rate / annualized rate / flat
- [ ] Rate: ______ % per ______ (day/year)
- [ ] Minimum fee: ______ VND
- [ ] Fee includes VAT: yes / no
- [ ] Maximum advance as % of pending: ______ %

### Lot Size & Market Rules

- [ ] HOSE lot size: ______ shares (100 as of 2024)
- [ ] HNX lot size: ______ shares
- [ ] Odd-lot trading available: yes / no
- [ ] Price limits HOSE: ±______ %
- [ ] Price limits HNX: ±______ %
- [ ] Price limits UPCoM: ±______ %

### Margin

- [ ] Margin enabled in my account: yes / no
- [ ] (If yes) Margin NOT modeled in MVP — Phase 1 uses cash-only

### Liquidity (Research Choice)

- [ ] My min avg_value_20d threshold: ______ VND
- [ ] My max order as % of ADV: ______
- [ ] My min stock price threshold: ______ VND

---

## 14. Known Limitations

- **No dividend modeling** in the backtest engine. Dividend income is not
  credited; dividend tax is not deducted. Affects buy-and-hold of
  dividend-paying stocks.
- **No partial position exits.** A signal change closes the entire position.
- **No multi-symbol portfolio backtesting.** Engine is single-symbol;
  portfolio research must run per-symbol and aggregate manually.
- **No T+2 enforcement in backtest engine.** SettlementLedger exists and is
  used by recommendation validator and portfolio ledger, but the vectorized
  backtest engine still treats cash as immediately available. Use the
  recommendation validator for production-style validation.
- **Slippage model is approximate.** Fixed-bps and liquidity-bucket models
  underestimate impact for very large orders or very illiquid names.
- **Calendar coverage: 2018–2030.** Years outside this range lack Tet and
  Hung Kings Day data.
- **Cash advance model assumes calendar days for fee calculation.** Real
  brokers may compute differently — verify.

---

## 15. References

- Law on Personal Income Tax No. 04/2007/QH12, Article 11 (sell tax)
- Law on Personal Income Tax No. 04/2007/QH12, Article 10 (dividend tax)
- Law No. 26/2012/QH13 (PIT amendment)
- Law on Value Added Tax No. 13/2008/QH12; Circular 219/2013/TT-BTC
- HOSE/HNX trading rules and circulars (verify current versions)
- SSI, VNDIRECT, TCBS, VPS, HSC, MBS — current published fee schedules
- Vietnam Securities Depository (VSD) settlement rules

---

## 16. Disclaimer (repeated)

- This system is for **research only**.
- This is **not financial advice**, **not tax advice**, and **not legal advice**.
- Vietnam market rules, broker fee schedules, and tax law change. The user
  must manually verify current rules with their broker and official sources.
- The user is solely responsible for verifying every input before making any
  investment decision based on this system.

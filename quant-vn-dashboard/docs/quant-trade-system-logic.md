# Quant Trade System Logic

Last reviewed: 2026-06-01

This document tracks the current stock-evaluation logic, formulas, thresholds,
and safety rules implemented in the quant trading/dashboard system.

Scope:

- Current deterministic scanner and recommendation logic.
- Vietnam-market fee/tax/slippage assumptions.
- Portfolio valuation and PnL formulas.
- Backtest metrics and strategy formulas.
- Trading preview, guardrails, paper trading, and auto-trade safety gates.

Important: all outputs are research signals only. They are not financial
advice and do not place orders unless a future live-trading phase explicitly
enables that path.

Primary source files:

- `quant-vn-dashboard/apps/api/src/services/scanner.py`
- `quant-vn-dashboard/apps/api/src/services/recommendation_engine.py`
- `quant-vn-dashboard/apps/api/src/services/risk_guardrails.py`
- `quant-vn-dashboard/apps/api/src/services/order_preview.py`
- `quant-vn-dashboard/apps/api/src/services/portfolio_valuation.py`
- `quant-vn-dashboard/apps/api/src/services/auto_trade_risk.py`
- `quant-vn-dashboard/apps/api/src/services/paper_performance.py`
- `quant/src/quant_vn/indicators/*`
- `quant/src/quant_vn/strategies/*`
- `quant/src/quant_vn/costs/*`
- `quant/src/quant_vn/backtest/metrics.py`
- `quant/src/quant_vn/execution/rules.py`
- `quant/src/quant_vn/market/settlement.py`

## 1. High-Level Flow

Current evaluation pipeline:

```text
Daily OHLCV bars + latest quote
  -> scanner indicators
  -> scanner signals
  -> scanner component scores
  -> scanner trend/status
  -> recommendation profile weights
  -> final_score + confidence
  -> action decision matrix
  -> entry / stop / take-profit / sizing
  -> risk guardrails
  -> dashboard output
```

The system deliberately separates:

- Signal math: pure, deterministic, testable.
- Guardrails: reject/warn/allow after scoring.
- Order preview: cost and validation only.
- Live order submission: protected and disabled unless explicitly gated.

## 2. Data Inputs

Per symbol, scanner/recommendation logic expects:

| Input | Meaning |
|---|---|
| `bars` | Daily OHLCV bars sorted ascending by timestamp. |
| `latest_quote` | Latest live quote, optional. If present, used for `last_price`. |
| `bar.value` | Trading value in VND. If missing, fallback is `close * volume`. |
| `vnindex_bars` | VNINDEX daily bars for market-regime score. |
| `portfolio_positions` | Current holdings for portfolio-fit and held-weight logic. |
| `total_equity` | Used for position-sizing cap. |

Minimum history:

| Indicator | Minimum bars |
|---|---:|
| `ma20` | 20 |
| `ma50` | 50 |
| `rsi14` | 15 |
| `atr14` | 15 |
| `volume_ratio_20d` | 21 |
| `high_20d` | 21 |
| `high_55d` | 56 |
| `avg_value_20d` | 20 |

Missing inputs produce `None` indicators and warnings such as
`insufficient_history`, `insufficient_liquidity_history`, `stale_data`,
`no_bars`, or `stale_quote`.

## 3. Scanner Indicators

### 3.1 Simple Moving Averages

```text
ma_n = mean(last n closes)
```

Current windows:

- `ma20`
- `ma50`

Returns `None` when there are fewer than `n` bars.

### 3.2 Wilder RSI 14

```text
delta[i] = close[i] - close[i-1]
gain[i]  = max(delta[i], 0)
loss[i]  = max(-delta[i], 0)

avg_gain_seed = mean(first 14 gains)
avg_loss_seed = mean(first 14 losses)

avg_gain = (avg_gain_prev * 13 + gain[i]) / 14
avg_loss = (avg_loss_prev * 13 + loss[i]) / 14

rs  = avg_gain / avg_loss
rsi = 100 - 100 / (1 + rs)
```

Edge cases in dashboard scanner:

- `avg_loss == 0` and `avg_gain > 0` -> `RSI = 100`
- `avg_loss == 0` and `avg_gain == 0` -> `RSI = 50`

### 3.3 Wilder ATR 14

```text
true_range[i] = max(
  high[i] - low[i],
  abs(high[i] - close[i-1]),
  abs(low[i] - close[i-1])
)

atr_seed = mean(first 14 true ranges)
atr = (atr_prev * 13 + true_range[i]) / 14
```

ATR is stored in price units/VND, not percent. Risk scoring converts it to
percent with `atr14 / last_close * 100`.

### 3.4 Volume Ratio 20D

```text
volume_ratio_20d = today_volume / mean(previous 20 volumes)
```

Today is excluded from the denominator.

### 3.5 Prior Highs

```text
high_20d = max(previous 20 closes)
high_55d = max(previous 55 closes)
```

The current bar is excluded.

### 3.6 Average Trading Value 20D

```text
bar_value = bar.value if available else close * volume
avg_value_20d = mean(last 20 bar_values)
```

Used for liquidity scoring, low-liquidity flags, and position sizing caps.

## 4. Scanner Signals

| Signal | Formula | Meaning |
|---|---|---|
| `MA20_ABOVE_MA50` | `ma20 > ma50` | Medium-term trend positive. |
| `PRICE_ABOVE_MA20` | `last_close > ma20` | Short-term price above trend. |
| `VOLUME_SPIKE` | `volume_ratio_20d >= 2.0` | Current volume at least 2x prior 20-day average. |
| `BREAKOUT_20D` | `last_close > high_20d` | Close breaks prior 20-day close high. |
| `BREAKOUT_55D` | `last_close > high_55d` | Close breaks prior 55-day close high. |
| `RSI_OVERBOUGHT` | `rsi14 >= 70` | Classical overbought zone. |
| `RSI_OVERSOLD` | `rsi14 <= 30` | Classical oversold zone. |
| `LOW_LIQUIDITY` | `avg_value_20d < 1,000,000,000` | Less than 1B VND/day average traded value. |

## 5. Scanner Trend Classification

```text
if ma20 is None or ma50 is None or last_close is None:
    trend = UNKNOWN
elif ma20 > ma50 and last_close > ma20:
    trend = UPTREND
elif ma20 < ma50 and last_close < ma20:
    trend = DOWNTREND
else:
    trend = SIDEWAYS
```

## 6. Scanner Component Scores

All scores are integers clamped to `[0, 100]`.

### 6.1 Trend Score

```text
trend_raw = 50
+25 if MA20_ABOVE_MA50
+25 if PRICE_ABOVE_MA20
-25 if neither bullish signal exists and both MAs are computable
trend = clamp(trend_raw)
```

Interpretation:

- `100`: MA20 > MA50 and close > MA20.
- `75`: one bullish trend condition.
- `50`: neutral or insufficient history.
- `25`: bearish trend setup.

### 6.2 Momentum Score

```text
if rsi14 is None:
    momentum_raw = 50
else:
    momentum_raw = (rsi14 - 30) * (100 / 40)

if BREAKOUT_20D:
    momentum_raw += 10

momentum = clamp(momentum_raw)
```

Anchor points:

- RSI 30 -> 0
- RSI 50 -> 50
- RSI 70 -> 100

### 6.3 Volume Score

```text
if volume_ratio_20d is None:
    volume = 0
else:
    volume = clamp(volume_ratio_20d * 40)
```

Examples:

- Ratio 1.0 -> 40
- Ratio 2.0 -> 80
- Ratio 2.5 or higher -> 100

### 6.4 Liquidity Score

```text
if avg_value_20d is None or avg_value_20d <= 0:
    liquidity = 0
else:
    liquidity = clamp((log10(avg_value_20d) - 7) * 25)
```

Anchor points:

- 100M VND/day -> 25
- 1B VND/day -> 50
- 10B VND/day -> 75
- 100B VND/day -> 100

### 6.5 Risk Score

Higher means more volatile/risky.

```text
vol_pct = atr14 / last_close * 100

if atr14 is missing or invalid:
    risk = 50
elif vol_pct <= 1:
    risk = vol_pct * 20
elif vol_pct <= 5:
    risk = 20 + (vol_pct - 1) * 15
else:
    risk = 80 + (vol_pct - 5) * 5

risk = clamp(risk)
```

Anchor points:

- ATR 1% of price -> 20
- ATR 3% of price -> 50
- ATR 5% of price -> 80
- ATR >= 9% of price -> 100

Recommendation logic also exposes:

```text
risk_inverse = 100 - risk
```

Higher `risk_inverse` means lower recent volatility.

## 7. Scanner Status Decision

Scanner status is a research label, not an order.

Decision order:

```text
if LOW_LIQUIDITY or risk >= 80 or trend == DOWNTREND:
    AVOID
elif trend == UPTREND
     and momentum >= 60
     and (BREAKOUT_20D or VOLUME_SPIKE)
     and risk < 70:
    BUY_CANDIDATE
elif trend in {UPTREND, SIDEWAYS} and momentum >= 40:
    WATCH
else:
    HOLD
```

## 8. Recommendation Profiles

Current profile weights in code:

| Component | `short_aggressive` | `long_conservative` |
|---|---:|---:|
| `trend` | 0.20 | 0.25 |
| `momentum` | 0.25 | 0.10 |
| `volume` | 0.15 | 0.05 |
| `liquidity` | 0.05 | 0.15 |
| `risk_inverse` | 0.10 | 0.15 |
| `market_regime` | 0.10 | 0.15 |
| `portfolio_fit` | 0.05 | 0.05 |
| `ml_probability` | 0.10 | 0.10 |

Note: `ml_probability` is currently `None`, so it contributes `0`; weights are
not redistributed. This means the current practical maximum score is lower
than 100 unless ML is populated.

## 9. Market Regime Score

Input: VNINDEX daily bars.

Current implementation:

```text
if vnindex_bars missing or len < 60:
    market_regime = 50

ma50 = mean(last 50 VNINDEX closes)
above_ma50 = last_close > ma50

ma50_series = last 10 values of rolling 50DMA
slope_positive = linear_regression_slope(ma50_series) > 0

if above_ma50 and slope_positive:
    market_regime = 80
elif above_ma50 or slope_positive:
    market_regime = 60
else:
    market_regime = 30
```

Interpretation:

- `80`: market is above 50DMA and 50DMA is rising.
- `60`: only one of the two bullish regime conditions is true.
- `50`: insufficient VNINDEX context.
- `30`: both regime checks are negative.

## 10. Portfolio Fit Score

Purpose: discourage adding more to a symbol that is already a meaningful
portfolio weight.

```text
if portfolio_positions is None:
    portfolio_fit = 100
elif symbol not held:
    portfolio_fit = 100
elif symbol held but weight unknown:
    portfolio_fit = 50
elif weight < 5%:
    portfolio_fit = 50
else:
    portfolio_fit = 0
```

Weights are fractions in code: `0.05` means 5%.

## 11. Final Score and Confidence

```text
final_score = clamp_int(sum(weight_i * score_i))
```

Rules:

- For normal 0..100 scores, use the score directly.
- For `ml_probability`, scale `[0, 1]` to `[0, 100]`.
- If a score is `None`, skip it.
- Do not redistribute the missing score's weight.

Confidence:

```text
confidence = clamp(final_score / 100, 0, 1)
```

Confidence is a normalized rule-strength score, not a win probability.

## 12. Recommendation Action Matrix

Current thresholds:

```text
ACTION_BUY_THRESHOLD = 70
ACTION_WATCH_THRESHOLD = 55
ACTION_REDUCE_THRESHOLD = 40
ACTION_SELL_THRESHOLD = 30
```

Decision order:

```text
if LOW_LIQUIDITY:
    AVOID
elif final_score < 20:
    AVOID
elif trend == UPTREND
     and final_score >= 70
     and momentum_score >= 55
     and supporting_signal:
    BUY_CANDIDATE
elif held and trend == DOWNTREND and final_score < 30:
    SELL_CANDIDATE
elif held and final_score < 40:
    REDUCE
elif trend in {UPTREND, SIDEWAYS} and final_score >= 55:
    WATCH
else:
    HOLD
```

Supporting signal means at least one of:

- `BREAKOUT_20D`
- `VOLUME_SPIKE`
- `PRICE_ABOVE_MA20`

## 13. Recommendation Trade Plan

### 13.1 Last Price

```text
last_price = latest_quote.price if latest_quote exists else last_close
```

### 13.2 Entry Zone

Entry zone is a symmetric band around `last_price`.

| Horizon | Band |
|---|---:|
| `INTRADAY_5M` | ±0.5% |
| `SHORT_T3`, `INTRADAY_15M` | ±1.0% |
| `SHORT_1W`, `EOD` | ±1.5% |
| `SHORT_2W` | ±2.0% |
| `SHORT_1M` | ±2.5% |
| `LONG_3M` | ±3.0% |
| `LONG_6M` | ±4.0% |
| `LONG_12M` | ±5.0% |

Formula:

```text
entry_low = last_price * (1 - band)
entry_high = last_price * (1 + band)
```

### 13.3 Stop Loss

Short horizons:

```text
stop_loss = last_price - 1.5 * atr14
```

Long horizons:

```text
stop_loss = last_price - 2.5 * atr14
```

Fallback when ATR is unavailable:

```text
short horizon: stop_loss = last_price * (1 - 0.05)
long horizon:  stop_loss = last_price * (1 - 0.10)
```

Stop is floored at zero.

### 13.4 Take Profit

Short horizons:

```text
take_profit_1 = last_price + 2.0 * atr14
take_profit_2 = last_price + 3.5 * atr14
```

Long horizons:

```text
take_profit_1 = last_price + 3.0 * atr14
take_profit_2 = last_price + 5.0 * atr14
```

Fallback when ATR is unavailable:

```text
short horizon:
  take_profit_1 = last_price * 1.07
  take_profit_2 = last_price * 1.12

long horizon:
  take_profit_1 = last_price * 1.15
  take_profit_2 = last_price * 1.25
```

### 13.5 Position Sizing

Constants:

```text
MAX_POSITION_VND = 50,000,000
EQUITY_PCT_PER_RECO = 0.05
MAX_ADV_PCT = 0.005
LOT_SIZE = 100
BROKERAGE_RATE = 0.0015
SLIPPAGE_RATE = 0.0010
```

Candidate position cap:

```text
caps = [50,000,000]
if total_equity available:
    caps.append(total_equity * 0.05)
if avg_value_20d available:
    caps.append(avg_value_20d * 0.005)

position_size_vnd = min(caps)
raw_qty = position_size_vnd / last_price
quantity = floor(raw_qty / 100) * 100
actual_notional = quantity * last_price
estimated_total_cost = actual_notional * (1 + 0.0015 + 0.0010)
```

## 14. Recommendation Reasons

The engine builds explainability codes:

1. Top two component scores, e.g. `TREND_SCORE_100`.
2. Trend confirmation, e.g. `TREND_UPTREND_CONFIRMED`.
3. First confirming signal among:
   - `BREAKOUT_20D`
   - `VOLUME_SPIKE`
   - `PRICE_ABOVE_MA20`
   - `MA20_ABOVE_MA50`
4. Action code, e.g. `ACTION_BUY_CANDIDATE`.

## 15. Recommendation Data Status

```text
if no bars:
    DATA_UNAVAILABLE
elif latest_quote is None:
    STALE
elif latest_quote.stale:
    STALE
else:
    FRESH
```

The recommendation also embeds `chart_context`:

- timeframe
- last candle time
- trend
- ma20
- ma50
- rsi
- volume ratio
- atr14

## 16. Risk Guardrails

Guardrails run after recommendation generation.

Severity model:

- `REJECT`: action becomes `REJECTED`, status becomes `REJECTED`.
- `WARN`: action is preserved, status becomes `WARNING`.
- `INFO`: informational only.

### 16.1 Liquidity Guardrail

```text
if avg_value_20d < 1B:
    REJECT low_liquidity
elif avg_value_20d < 5B:
    WARN avg_value_20d_below_threshold
```

### 16.2 ADV Participation Guardrail

```text
cap = avg_value_20d * 0.005
if position_size_vnd > cap:
    REJECT position_size_exceeds_max_adv_pct
```

This is stricter than order preview, which warns above 5% of ADV.

### 16.3 Cash Guardrail

```text
if position_size_vnd > settled_cash:
    WARN insufficient_settled_cash
```

### 16.4 Portfolio Weight Guardrail

```text
new_weight = current_position_weight + position_size_vnd / total_equity
if new_weight > 15%:
    REJECT portfolio_weight_too_high
```

### 16.5 Ceiling/Floor Guardrail

If ceiling/floor are unavailable:

```text
INFO ceiling_floor_unavailable
```

If available:

```text
if last_price >= ceiling_price * 0.99:
    WARN price_outside_ceiling_floor
if last_price <= floor_price * 1.01:
    WARN price_outside_ceiling_floor
```

### 16.6 Stale Data Guardrail

```text
if quote_stale:
    WARN data_stale
elif as_of_age_seconds > 300:
    WARN data_stale
```

### 16.7 Data Quality Guardrail

```text
if data_quality_critical:
    REJECT data_quality_critical
```

### 16.8 Fee/Tax Profile Guardrail

```text
if no cash_balance row:
    WARN missing_fee_tax_profile
```

### 16.9 Pending Cash Advance Guardrail

```text
if pending_cash > 0 and settled_cash < position_size_vnd:
    WARN pending_cash_requires_advance
```

## 17. Order Preview Logic

Order preview is a pure calculator. It does not submit orders.

Constants:

```text
BROKERAGE_RATE = 0.0015
VAT_RATE = 0.10
SELL_TAX_RATE = 0.001
SLIPPAGE_RATE = 0.0010
DEFAULT_LOT_SIZE = 100
MAX_ORDER_PCT_OF_ADV = 0.05
```

### 17.1 Validation

Checks:

- Quantity must be positive.
- Quantity must be a multiple of lot size.
- Security status must be `ACTIVE` if known.
- Limit price must be inside ceiling/floor if quote carries those fields.
- Order value above 5% of 20D ADV produces a warning.
- BUY requires enough buying power.
- SELL requires enough sellable shares.

### 17.2 BUY Cost Formula

```text
gross_value = price * quantity
brokerage = gross_value * 0.0015
vat = brokerage * 0.10
slippage = gross_value * 0.0010
total_cash_required = gross_value + brokerage + vat + slippage
```

If cash is insufficient but pending cash could cover the shortfall:

```text
WARN CASH_ADVANCE_REQUIRED
```

Otherwise:

```text
REJECT INSUFFICIENT_CASH
```

### 17.3 SELL Proceeds Formula

```text
gross_value = price * quantity
brokerage = gross_value * 0.0015
vat = brokerage * 0.10
sell_tax = gross_value * 0.001
slippage = gross_value * 0.0010
net_sell_proceeds = gross_value - brokerage - vat - sell_tax - slippage
```

SELL preview always includes:

```text
WARN T+2_SETTLEMENT
```

### 17.4 Settlement Date

Preview settlement date uses Vietnam business-day logic from
`services.vn_holidays.add_business_days`.

```text
settlement_date = trade_date + 2 business days
```

## 18. Vietnam Fee, Tax, VAT, Slippage Models

### 18.1 Brokerage Fee

Flat fee model:

```text
brokerage_fee = max(notional * rate, min_fee_vnd)
```

Default SSI-style assumption:

```text
rate = 0.0015  # 0.15%
min_fee_vnd = 0
```

Tiered fee model:

```text
rate = first tier where cumulative_daily_notional >= tier.min_daily_value
brokerage_fee = max(notional * rate, min_fee_vnd)
```

The selected tier applies to the full order notional, not marginal brackets.

### 18.2 VAT

```text
if fee_includes_vat or VAT disabled:
    vat = 0
else:
    vat = brokerage_fee * 0.10
```

VAT applies to brokerage/service fee, not to trade notional or sell tax.

### 18.3 Sell Tax

```text
sell_tax = gross_sell_value * 0.001
```

Applied on every sell trade, regardless of profit or loss.

### 18.4 Cash Dividend Tax

```text
dividend_tax = cash_dividend_gross * 0.05
net_dividend = cash_dividend_gross - dividend_tax
```

Stock dividend/bonus share tax model is intentionally not implemented until
rules are verified.

### 18.5 Slippage

Fixed bps model:

```text
slippage_rate = bps / 10,000

BUY effective_price = reference_price * (1 + slippage_rate)
SELL effective_price = reference_price * (1 - slippage_rate)

slippage_cost = reference_price * quantity * slippage_rate
```

Default:

```text
bps = 10
slippage_rate = 0.0010
```

Liquidity bucket model:

| ADV Bucket | Slippage |
|---|---:|
| `avg_value_20d >= 50B` | 10 bps |
| `5B <= avg_value_20d < 50B` | 25 bps |
| `< 5B` | 50 bps |
| missing ADV | 25 bps |

## 19. Transaction Cost Model

### 19.1 BUY

```text
notional = price * quantity
brokerage_fee = broker_profile.calculate_fee(notional)
vat = VATModel.calculate(brokerage_fee)
slippage = SlippageModel.calculate(price, quantity, BUY)
total_cost = brokerage_fee + vat + slippage
total_cash_required = notional + total_cost
```

### 19.2 SELL

```text
notional = price * quantity
brokerage_fee = broker_profile.calculate_fee(notional)
vat = VATModel.calculate(brokerage_fee)
sell_tax = notional * 0.001
slippage = SlippageModel.calculate(price, quantity, SELL)
total_cost = brokerage_fee + vat + sell_tax + slippage
net_sell_proceeds = notional - total_cost
```

### 19.3 Realized PnL on Round Trip

```text
cost_basis = buy_price * qty + buy_brokerage_fee + buy_vat
realized_pnl = net_sell_proceeds - cost_basis
net_return = realized_pnl / cost_basis
```

## 20. Settlement Logic

Vietnam listed stock/ETF settlement:

```text
settlement_days = 2 trading days
```

BUY:

```text
cash deducted immediately
shares enter pending_shares
at T+2: pending_shares -> settled_shares
```

SELL:

```text
shares removed from settled_shares immediately
net proceeds enter pending_cash
at T+2: pending_cash -> settled_cash
```

If cash advance is used:

```text
pending cash marked ADVANCED
net advanced cash added immediately
no additional settled cash is added at T+2
```

## 21. Cash Advance Model

Cash advance is disabled by default.

Daily/annualized fee:

```text
daily_rate = annualized_rate / 365
fee_before_vat = advanced_amount * daily_rate * advance_days
fee_before_vat = max(fee_before_vat, minimum_fee)
```

Flat fee:

```text
fee_before_vat = advanced_amount * flat_fee_rate
fee_before_vat = max(fee_before_vat, minimum_fee)
```

VAT:

```text
if fee_includes_vat or vat disabled:
    vat = 0
else:
    vat = fee_before_vat * vat_rate
```

Final:

```text
total_advance_fee = fee_before_vat + vat
net_advanced_cash = advanced_amount - total_advance_fee
max_advance_amount = pending_sell_proceeds * max_advance_pct
```

## 22. Portfolio Valuation

### 22.1 Position Valuation

```text
cost_basis = quantity * avg_cost
market_value = quantity * market_price
unrealized_pnl = market_value - cost_basis
unrealized_pnl_pct = unrealized_pnl / cost_basis
```

If market price is missing:

```text
market_value = None
unrealized_pnl = None
warning = quote_missing
```

### 22.2 Position Weight

```text
weight = position_market_value / total_market_value
```

If market value is unavailable or total market value is zero, weight is `None`.

### 22.3 Portfolio Summary

```text
total_market_value = sum(known position market values)
total_cost_basis = sum(quantity * avg_cost for all positions)
total_unrealized_pnl = total_market_value - total_cost_basis
total_unrealized_pnl_pct = total_unrealized_pnl / total_cost_basis
```

Strategy allocation:

```text
by_strategy_tag[tag] += market_value
```

### 22.4 Realized PnL from Trades

Uses weighted-average cost per `(account_id, symbol)`.

On BUY:

```text
new_qty = current_qty + buy_qty
new_avg_cost = (current_qty * current_avg + buy_qty * buy_price) / new_qty
```

On SELL:

```text
sell_qty = min(requested_sell_qty, current_qty) if current_qty > 0 else requested_sell_qty
realized = sell_qty * (sell_price - current_avg_cost)
cost_basis_at_sell = sell_qty * current_avg_cost
remaining_qty = max(current_qty - sell_qty, 0)
```

Partial sells keep the same average cost for remaining shares.

### 22.5 Cost Breakdown

For a selected period (`MTD`, `YTD`, or `ALL`):

```text
total_cost =
  brokerage_fee
  + vat
  + sell_tax
  + cash_advance_fee
  + slippage_estimate
```

`MTD` and `YTD` use Asia/Ho_Chi_Minh local date boundaries.

## 23. Paper Trading Performance

Paper equity snapshot:

```text
stock_value = sum(mark_price * quantity)
unrealized_pnl = sum((mark_price - avg_cost) * quantity)
total_equity = cash + pending_cash + stock_value
realized_pnl = total_equity - starting_cash - unrealized_pnl
```

If mark price is missing for a symbol:

```text
mark_price = avg_cost
```

This avoids overstating drawdown by marking missing prices to zero.

Drawdown:

```text
peak = max(saved total_equity curve, starting_cash)
drawdown = (peak - total_equity) / peak if total_equity < peak else 0
```

## 24. Backtest Metrics

Inputs:

- `equity_curve["equity"]`
- trade log
- initial capital
- annual trading days default: `252`
- risk-free rate default: `0.04`

### 24.1 Returns

```text
total_return = (final_equity - initial_capital) / initial_capital
n_years = len(equity_curve) / 252
cagr = (final_equity / initial_capital) ** (1 / n_years) - 1
```

### 24.2 Volatility

```text
returns = equity.pct_change().fillna(0)
annualized_volatility = std(returns) * sqrt(252)
```

### 24.3 Max Drawdown

```text
rolling_max = cumulative_max(equity)
drawdown = (equity - rolling_max) / rolling_max
max_drawdown = min(drawdown)
```

Drawdown duration is the longest consecutive period where `drawdown < 0`.

### 24.4 Sharpe

```text
daily_rf = annual_risk_free_rate / 252
excess_returns = returns - daily_rf
sharpe = mean(excess_returns) * 252 / annualized_volatility
```

### 24.5 Sortino

```text
downside = min(excess_returns, 0)
downside_variance = mean(downside ** 2)
downside_std_ann = sqrt(downside_variance * 252)
sortino = mean(excess_returns) * 252 / downside_std_ann
```

### 24.6 Calmar

```text
calmar = cagr / abs(max_drawdown)
```

If max drawdown is zero and CAGR is positive, Calmar is infinity.

### 24.7 Trade Statistics

```text
n_trades = len(trades)
win_rate = count(net_pnl > 0) / n_trades
avg_win = mean(net_pnl of winning trades)
avg_loss = mean(net_pnl of losing trades)
profit_factor = abs(sum(wins) / sum(losses))
expectancy = mean(net_pnl)
avg_holding_days = mean(holding_days)
avg_trade_return_pct = mean(return_pct) * 100
```

Turnover:

```text
total_notional = sum(entry_price * quantity) * 2
turnover = total_notional / average_equity / n_years
```

## 25. Strategy Logic

### 25.1 Buy and Hold

```text
signal = 1 after first bar
first bar signal = 0
```

The backtest engine shifts signals by one bar, so the first actual buy is at
the next bar open.

### 25.2 Moving Average Cross

Parameters:

```text
fast_window = 20
slow_window = 50
method = sma or ema
```

Signal:

```text
signal = 1 if fast_MA > slow_MA else 0
```

No shorting; flat when the condition is false.

### 25.3 RSI Mean Reversion

Parameters:

```text
rsi_window = 14
oversold_threshold = 30
exit_threshold = 70
```

State machine:

```text
if flat and rsi < oversold_threshold:
    enter long
elif in_trade and rsi > exit_threshold:
    exit to flat
signal = 1 while in_trade else 0
```

### 25.4 Breakout

Parameters:

```text
lookback_window = 20
volume_confirmation = True
volume_window = 20
volume_multiplier = 1.5
trailing_stop_pct = 0.05
```

No-lookahead breakout level:

```text
rolling_high_prev = max(close over previous lookback window)
breakout = close_today > rolling_high_prev
volume_ok = volume_ratio >= 1.5
```

Entry:

```text
if not in_trade and breakout and volume_ok:
    enter long
```

Exit:

```text
highest_since_entry = max(highest_since_entry, close)
stop_level = highest_since_entry * (1 - trailing_stop_pct)

if close < stop_level or close < rolling_high_prev:
    exit to flat
```

## 26. Execution Rule Checks

These are pre-trade validation helpers.

### 26.1 Lot Size

```text
LOT_SIZE_VN = 100
quantity must be positive
quantity must be a whole number
quantity % 100 == 0
```

If `auto_round_down=True`, the result includes:

```text
adjusted_quantity = floor(quantity / lot_size) * lot_size
```

The check still fails unless caller uses the adjusted value.

### 26.2 Price Limits

| Exchange | Daily band |
|---|---:|
| HOSE/HSX | ±7% |
| HNX | ±10% |
| UPCoM | ±15% |

Formula:

```text
ceiling = reference_price * (1 + limit_pct)
floor = reference_price * (1 - limit_pct)
```

### 26.3 Cash Sufficiency

```text
settled_cash >= required_cash
```

Pending sell proceeds do not count unless cash advance is explicitly used.

### 26.4 Sellable Shares

```text
settled_shares >= requested_quantity
```

Pending buy shares do not count until settlement.

### 26.5 Liquidity

```text
avg_daily_value_20d >= min_avg_daily_value_vnd
order_value <= avg_daily_value_20d * max_order_adv_pct
```

Defaults:

```text
min_avg_daily_value_vnd = 5B
max_order_adv_pct = 5%
```

## 27. Auto-Trade Risk Gates

Auto-trade engine risk validation is conservative. When unsure, reject.

Checks:

1. Run status must be `STARTED` or `RUNNING`.
2. Kill switch must not be active.
3. User mode must match run mode.
4. Candidate action must be `BUY` or `SELL`.
5. Symbol must be in allow-list if allow-list exists.
6. Strategy must be in allow-list if allow-list exists.
7. Cooldown must not be active for `(symbol, action)`.
8. Daily order count must be below `max_orders_per_day`.
9. Single order value must be under `max_order_value_vnd`.
10. Daily gross order value must stay under `max_capital_vnd`.
11. Market must be open if configured.
12. Quote must exist and not be stale.
13. Order preview validation must pass for lot, price band, cash/shares, fees,
    and liquidity.

If any rejection reason exists:

```text
status = REJECTED
```

If no rejection but warnings exist:

```text
status = WARN
```

Valid/warn decisions then dispatch by mode:

- `PAPER_ONLY`: simulate paper order.
- `LIVE_MANUAL_CONFIRM`: create draft live-order intent; no submit.
- `LIVE_AUTO` dry-run: synthetic live dry-run record; no SSI call.
- `LIVE_AUTO` live: only through the protected Phase 2.8 submit gauntlet.

## 28. Interpretation Guide

### 28.1 What a High Score Means

A high `final_score` means the stock currently matches the deterministic
technical/liquidity/portfolio heuristics for the selected profile.

It does not mean:

- guaranteed profit
- high probability of winning
- automatic buy
- suitable position size for every account

### 28.2 How to Read Actions

| Action | Meaning |
|---|---|
| `BUY_CANDIDATE` | Research candidate worth manual review. |
| `WATCH` | Interesting but not enough confirmation. |
| `HOLD` | No strong new action from the current rules. |
| `REDUCE` | Held symbol has weak score; consider trimming manually. |
| `SELL_CANDIDATE` | Held symbol is in downtrend with low score. |
| `AVOID` | Scanner/recommendation logic sees unacceptable risk/liquidity/score. |
| `REJECTED` | Guardrail veto; do not proceed under current data/rules. |

### 28.3 What to Tune Carefully

Most impactful knobs:

- Profile weights in `recommendation_engine.PROFILE_WEIGHTS`.
- Action thresholds: 70/55/40/30.
- Liquidity thresholds: 1B reject, 5B warning.
- ADV caps: 0.5% recommendation sizing/guardrail, 5% preview warning.
- Risk score mapping from ATR percent.
- Stop/target ATR multipliers.
- Broker fee/VAT/slippage assumptions.
- Portfolio weight hard cap: 15%.

Any change to these should be tracked with:

```text
Changed value:
Reason:
Expected effect:
Backtest/test evidence:
Date:
```

## 29. Known Gaps / Future Improvements

- Fundamental valuation ratios are not currently part of the score.
- Corporate action adjustment is handled in data tooling, not directly in the
  scanner formula.
- `ml_probability` is wired into the score shape but currently disabled/null.
- Intraday 5m/15m horizons exist in schema, but the current scanner math is
  daily-bar based.
- Fixed-bps slippage is simplistic for illiquid names.
- Tax/fee rules should be periodically re-verified against broker statements
  and current Vietnamese regulations.
- Market-regime logic is simple VNINDEX 50DMA heuristic, not a full breadth or
  macro model.


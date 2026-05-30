# Signal Scanner — Spec

Reference doc for the Phase 1 Signal Scanner MVP shipped in
`apps/api/src/services/scanner.py`. This is the canonical description of the
math, the signal taxonomy, the score mapping, and the status decision tree.

If you change the scanner code, update this file and add an audit note under
`quant-vn-dashboard/docs/audit/`.

---

## 1. Purpose & disclaimer

The Signal Scanner produces **research signals only** for Vietnam equities
listed on HOSE / HNX / UPCoM. It exists to help a single quant researcher
(the project owner) triage a watchlist faster.

- It does **not** place orders.
- It does **not** constitute financial advice or a personal investment
  recommendation under Vietnamese securities law.
- Every output field — `trend`, `signals`, `status`, `scores` — is a
  research label. `BUY_CANDIDATE` is shorthand for *"worth a closer manual
  look"*, not *"buy this stock"*.
- Phase 1 is **recommend-only**. Any future integration with a broker
  (SSI FastConnect, etc.) must go through read-only sync → paper trading →
  manual-approval trading, per `docs/trading-rules.md`.

The dashboard MUST surface this disclaimer next to scanner output.

---

## 2. Inputs

Per-symbol, the scanner needs:

| Input | Shape | Notes |
|-------|-------|-------|
| `bars` | `list[OHLCVBar]`, daily, sorted ascending by `ts` | ~80 bars is the comfortable target; the long-horizon indicators need ≥ 56 bars (BREAKOUT_55D). |
| `latest_quote` | `Quote \| None` | Optional. If present and not stale, `last_price` and `as_of` come from the quote; otherwise from the last bar close. |
| `bar.value` | turnover in VND per bar | Optional. If null, the scanner falls back to `close * volume` for that bar in the `avg_value_20d` computation. |

Minimum bars per indicator:

| Indicator | Minimum bars |
|-----------|--------------|
| `ma20` | 20 |
| `ma50` | 50 |
| `rsi14` | 15 (= 14 + 1 seed bar) |
| `atr14` | 15 (= 14 + 1 prior-close bar) |
| `volume_ratio_20d` | 21 (= 20 prior bars + today) |
| `high_20d` | 21 (= 20 prior bars + today) |
| `high_55d` | 56 (= 55 prior bars + today) |
| `avg_value_20d` | 20 |

Insufficient history is signaled by `null` indicator values and the route
layer attaches a `insufficient_history` or `insufficient_liquidity_history`
warning. Stale quotes attach `stale_data`.

Assumptions on the bar feed:

- Bars are daily, raw (not split/dividend adjusted). The scanner does **not**
  correct for corporate actions — see Limitations.
- VN trading day has three sessions (ATO, continuous, ATC). The scanner does
  not look inside the day; ATC dynamics are absorbed into the closing print.
- Lot size on HOSE is 100 shares; the scanner has no awareness of lots.
- VN price tick rules and daily price band (±7% HOSE, ±10% HNX, ±15% UPCoM)
  are not modeled — see Limitations.

---

## 3. Indicators

All formulas operate on the supplied bar series. `closes[i]` is the close of
bar i; the latest bar is `closes[-1]` ("today"). Listings below match
`services/scanner.py`.

### 3.1 `ma20`, `ma50` — simple moving averages

```
ma_n = mean(closes[-n:])           # n ∈ {20, 50}
```

- Returns `None` when fewer than `n` bars.
- Uses simple arithmetic mean — no Wilder/EMA smoothing on MAs.

### 3.2 `rsi14` — Wilder RSI (14)

Implemented in `_rsi_wilder`:

```
deltas      = closes.diff()
gains[i]    = max(delta[i], 0)
losses[i]   = max(-delta[i], 0)

# Seed: simple mean of the first 14 deltas
avg_gain    = mean(gains[:14])
avg_loss    = mean(losses[:14])

# Wilder recursion for each subsequent delta
avg_gain    = (avg_gain * 13 + gains[i]) / 14
avg_loss    = (avg_loss * 13 + losses[i]) / 14

rs  = avg_gain / avg_loss
rsi = 100 - 100 / (1 + rs)
```

Edge cases:

- `avg_loss == 0` and `avg_gain > 0` → RSI = 100.
- `avg_loss == 0` and `avg_gain == 0` (flat series) → RSI = 50 (treated as
  neutral). Note this diverges from `quant/indicators/momentum.py` which
  returns NaN on flat series; the scanner deliberately chooses a neutral
  value to keep the score map well-defined.
- Needs ≥ 15 closes to emit a value.

The recursion is mathematically equivalent to an EMA with `alpha = 1/14`
after seeding (the canonical Wilder smoothing).

### 3.3 `atr14` — Wilder ATR (14)

```
TR[i] = max(high[i] - low[i],
            |high[i] - close[i-1]|,
            |low[i]  - close[i-1]|)

ATR_seed = mean(TR[1..14])
ATR[i]   = (ATR[i-1] * 13 + TR[i]) / 14   # for i > 14
```

- ATR is reported in **VND**, not as a percentage. The risk score later
  converts it to `ATR / last_close * 100` for a relative volatility view.
- Needs ≥ 15 bars (TR needs a previous close).

### 3.4 `volume_ratio_20d`

```
prior_avg = mean(volumes[-21:-1])   # last 20 bars BEFORE today
ratio     = volumes[-1] / prior_avg
```

- Today is **excluded** from the denominator, which is the correct
  no-lookahead form for an intraday-evaluated EOD ratio.
- Returns `None` when fewer than 21 bars or when the prior average is ≤ 0.

### 3.5 `high_20d`, `high_55d` — Donchian-style breakout highs

```
high_n = max(closes[-(n+1):-1])     # max close over the n bars BEFORE today
```

- The current bar is excluded, so the breakout test
  `last_close > high_n` is a true *prior-n excluding today* condition (no
  intraday lookahead).
- Uses **close** rather than session high. This is intentional: VN intraday
  highs can be noisy and the scanner runs EOD.

### 3.6 `avg_value_20d` — turnover proxy in VND

```
for each of the last 20 bars:
    if bar.value is not None: use bar.value
    else:                     use bar.close * bar.volume
avg_value_20d = mean(those 20 values)
```

- Used both for the liquidity score and the `LOW_LIQUIDITY` signal flag.
- Falling back to `close * volume` per bar is correct for HOSE/HNX where
  most providers expose turnover in VND directly. UPCoM coverage of `value`
  is patchy so the fallback path matters.

---

## 4. Signal rules

Boolean flags emitted by `derive_signals`. Order is stable.

| `signal_code` | Condition | Interpretation | Caveats |
|---------------|-----------|----------------|---------|
| `MA20_ABOVE_MA50` | `ma20 > ma50` | Medium-term trend bias positive | Lags fast reversals; both MAs use closes only. |
| `PRICE_ABOVE_MA20` | `last_close > ma20` | Short-term trend bias positive | A single-bar gap above MA20 will flip this flag. |
| `VOLUME_SPIKE` | `volume_ratio_20d ≥ 2.0` | Today's volume ≥ 2× prior-20 average | 2.0 is a global heuristic; small caps can fire on news with no real liquidity. |
| `BREAKOUT_20D` | `last_close > high_20d` | Close above prior 20-day high (close basis) | Close basis only — does not catch intraday wicks. |
| `BREAKOUT_55D` | `last_close > high_55d` | Close above prior 55-day high (close basis) | Same caveat. Slower, more durable. |
| `RSI_OVERBOUGHT` | `rsi14 ≥ 70` | Wilder-RSI in classical OB zone | OB ≠ bearish; can stay OB through a strong trend. |
| `RSI_OVERSOLD` | `rsi14 ≤ 30` | Wilder-RSI in classical OS zone | OS ≠ bullish; trending downs stay OS. |
| `LOW_LIQUIDITY` | `avg_value_20d < 1e9 VND` | Average turnover under 1 billion VND/day | Threshold is a single global constant; see Limitations. |

---

## 5. Scores

Five 0..100 integer sub-scores, all clamped to `[0, 100]` by `_clamp` in
`compute_scores`. Each one is a heuristic projection, not a probability.

### 5.1 `trend`

Base = 50.

- `+25` if `MA20_ABOVE_MA50` is set.
- `+25` if `PRICE_ABOVE_MA20` is set.
- `-25` if **neither** is set **and** both `ma20` and `ma50` are
  computable (i.e. enough history exists).

Expected values:

- `0..25`  : full downtrend (MA20 < MA50 AND price < MA20).
- `50`     : neutral / insufficient history.
- `75`     : one of the two bullish conditions holds.
- `100`    : both bullish conditions hold (canonical uptrend).

### 5.2 `momentum`

```
momentum = 50               # default when RSI is null
        OR (rsi14 - 30) * (100 / 40)
momentum += 10              # if BREAKOUT_20D
momentum = clamp(momentum)
```

- Linear map: RSI 30 → 0, RSI 50 → 50, RSI 70 → 100. Outside that band
  the value clamps.
- `BREAKOUT_20D` adds a +10 bump on top, also clamped at 100.
- `50` means *no information* (RSI not computable).

### 5.3 `volume`

```
volume_score = clamp(volume_ratio_20d * 40)
```

- `volume_ratio_20d` of 1.0 → score 40.
- 2.5 → 100 (clamped).
- `0` when the ratio is null (insufficient history).

### 5.4 `liquidity`

```
liquidity_raw = (log10(avg_value_20d) - 7) * 25
```

Anchor points: 1e8 VND → 25; 1e9 → 50; 1e10 → 75; 1e11 → 100. Returns `0`
when `avg_value_20d` is null or ≤ 0. The route layer attaches the
appropriate warning so `0` is not silently treated as *truly illiquid*.

### 5.5 `risk` — semantic: higher = more volatile, NOT automatically worse

`risk` is *not* a "bad" score. It is the magnitude of recent realized
volatility, computed from ATR as a percentage of price:

```
vol_pct = atr14 / last_close * 100

vol_pct ≤ 1   → vol_pct * 20                 # 0..20
1 < vol_pct ≤ 5 → 20 + (vol_pct - 1) * 15    # 20..80
vol_pct > 5   → 80 + (vol_pct - 5) * 5       # 80+
clamp to 0..100
```

Anchors: 1% daily ATR → 20, 3% → 50, 5% → 80, ≥9% → 100. Default = 50 when
ATR or close is null/zero.

The status logic interprets *high* risk as a reason to be more cautious
(see § 6), but the score itself is informational — a high-conviction
breakout strategy may welcome a high risk score.

---

## 6. Status decision tree

`decide_status(scores, signals, trend)` evaluates rules in this order. The
first match wins.

| Order | Status | Condition |
|-------|--------|-----------|
| 1 | `AVOID` | `LOW_LIQUIDITY` in signals **OR** `risk ≥ 80` **OR** `trend == "DOWNTREND"` |
| 2 | `BUY_CANDIDATE` | `trend == "UPTREND"` **AND** `momentum ≥ 60` **AND** (`BREAKOUT_20D` in signals **OR** `VOLUME_SPIKE` in signals) **AND** `LOW_LIQUIDITY` not in signals **AND** `risk < 70` |
| 3 | `WATCH` | `trend ∈ {"UPTREND", "SIDEWAYS"}` **AND** `momentum ≥ 40` |
| 4 | `HOLD` | default |

Precedence intent:

- `AVOID` always wins. Anything illiquid, in a confirmed downtrend, or with
  extreme realized vol is removed from the BUY pool unconditionally.
- `BUY_CANDIDATE` requires a confirmed uptrend, real momentum, AND a
  catalyst (breakout or volume spike). The two redundant guards
  (`LOW_LIQUIDITY` and `risk < 70`) are intentional belts-and-braces.
- `WATCH` is the soft pool: trend not negative, momentum at least neutral.
- `HOLD` is the residual.

Note: `trend == "UNKNOWN"` (insufficient history) cannot reach
`BUY_CANDIDATE` or `WATCH`; it lands on `HOLD` by default.

---

## 7. Known limitations

1. **No corporate action adjustments.** Splits/bonus issues will create
   spurious breakouts/drops the day they take effect. The data layer keeps
   corporate actions in a separate table; the scanner does not consume them.
2. **No regime detection.** The same thresholds apply in low-vol and
   high-vol regimes. A 2× volume day means different things in 2022 vs 2024.
3. **Volume spike threshold is heuristic.** `2.0` is a single global
   constant. There is no per-symbol baseline and no regime adjustment.
4. **VN tick rule and lot size are not factored.** HOSE tick steps
   (10/50/100 VND) and the 100-share lot are not used anywhere in scoring.
   A "breakout" by one tick is treated the same as a 5% breakout.
5. **Price band (ceiling/floor) not modeled.** A close at the ceiling price
   is a different event from a free-trading close, but the scanner sees
   only the number.
6. **Liquidity threshold is one global constant.** `1e9 VND` filters out
   most genuine micro-caps but also unfairly flags legitimate small-cap
   names on UPCoM. No sector/cap-size adjustment.
7. **No multi-day persistence look-back.** Signals are evaluated on a
   single day. A breakout that already failed yesterday is treated as fresh
   if it re-fires today.
8. **Single-source data.** Whatever provider the route layer hands in is
   what gets scored. No reconciliation between SSI/VND/TCBS inside the
   scanner.
9. **Close-basis breakouts only.** Intraday wick breakouts are not
   detected. This is by design for an EOD scanner but worth flagging.
10. **RSI flat-series convention diverges from `quant/`.** The scanner
    returns 50 on a perfectly flat series; `quant/indicators/momentum.py`
    returns NaN. Acceptable, but document both behaviors.
11. **Risk score saturates above ATR%=9%.** Anything more volatile than
    that maps to 100 — fine for ranking, but loses information at the tail.

---

## 8. Tuning notes for the next iteration

- **Multi-timeframe confirmation.** Require alignment between the daily
  scan and a 5m / 15m intraday confirmation before promoting to
  `BUY_CANDIDATE`. Consistent with the product vision in
  `docs/product-vision.md`.
- **Per-symbol volume baselines.** Replace the single `VOLUME_SPIKE_RATIO`
  with a z-score against the symbol's own 90-day volume distribution.
- **Regime overlay.** Tag each scan with VN-Index regime (uptrend / range /
  downtrend) and adjust thresholds accordingly.
- **Sector context.** Lift `LOW_LIQUIDITY` for legitimately liquid sectors
  and tighten it for micro-cap penny names.
- **ML overlay.** A small classifier on top of the heuristic scores
  (features = scores + signal flags + indicator deltas) could learn which
  combinations have historically been productive on VN names. Output stays
  a probability, used as a tie-breaker only — heuristic remains primary.
- **Persistence filter.** Require N consecutive days of confirming signals
  before promoting to `BUY_CANDIDATE`, to cut whip-saw noise.
- **Corporate action gate.** Suppress signals on the ex-date of a known
  split / bonus / cash dividend.
- **Tick-aware breakouts.** Require the breakout to exceed prior high by
  ≥ k ticks (or ≥ x% of ATR) to filter marginal cases.
- **Wider RSI map.** Consider mapping RSI 40 → 0 and RSI 60 → 100 to make
  the momentum score less RSI-extreme-dependent; combine with rate-of-change.

---

## 9. References

- Wilder, J. W. (1978). *New Concepts in Technical Trading Systems.*
  Trend Research. Source of the RSI and ATR Wilder smoothing recursion.
- Donchian, R. — channel-breakout concept underlying `high_20d` and
  `high_55d` (a la the Turtle 20/55 system).
- General volume-based momentum: standard practitioner literature on
  volume-confirmed breakouts (no single canonical citation).
- Internal: `docs/trading-rules.md` (no-lookahead and recommend-only
  rules), `docs/product-vision.md` (Phase 1 scope), `quant/docs/agent-memory/coding-rules.md`.

# Recommendation Engine — Methodology Spec (Phase 1)

Reference doc for the Phase 1 rule-based Recommendation Engine to be shipped at
`apps/api/src/services/recommendation.py` (companion route + Pydantic schemas
under `apps/api/src/api/routes/recommendation.py` and
`apps/api/src/schemas/recommendation.py`).

This is the canonical description of the math, the profile/horizon taxonomy,
the score-weighting formula, the action decision matrix, the risk guardrails,
the position-sizing rules, and the output schema.

If the engine code is changed, update this file and add an audit note under
`quant-vn-dashboard/docs/audit/`.

Companion docs: `docs/scanner-signals.md` (sub-scores re-used here),
`docs/portfolio-pnl-spec.md` (portfolio fit + cash inputs),
`docs/portfolio-assets-mvp.md` (Phase boundaries).

---

## 1. Purpose & disclaimer

The Recommendation Engine produces **research signals only** for Vietnam
equities listed on HOSE / HNX / UPCoM. It exists to help a single quant
researcher (the project owner) decide which symbols deserve closer manual
attention, sized for an explicit profile and horizon.

- It does **not** place orders.
- It does **not** constitute financial advice or a personal investment
  recommendation under Vietnamese securities law.
- Every output field — `action`, `confidence`, `entry_zone`, `stop_loss`,
  `take_profit`, `scores`, `reasons`, `warnings` — is a research label.
  `BUY_CANDIDATE` is shorthand for *"worth a closer manual look"*, not
  *"buy this stock"*.
- Phase 1 is **recommend-only**. Any future integration with a broker
  (SSI FastConnect, etc.) must go through read-only sync → paper trading →
  manual-approval trading, per `docs/trading-rules.md`.
- Every recommendation MUST carry `reasons`, `warnings`, and a validation
  `status` field; the dashboard MUST surface all three next to the
  recommendation.

`confidence` is a normalized rule-strength proxy in `[0, 1]`, not a
probability of a winning trade. See §4.

---

## 2. Profile definitions

A recommendation is always evaluated against an explicit **profile**. Two
profiles are supported in Phase 1; both weight the eight sub-scores
(§3) into the final score (§4) and constrain which horizons may be emitted.

| Profile | Intent | Horizons supported |
|---------|--------|--------------------|
| `short_aggressive` | Trade ideas built on momentum, volume, and breakouts. Hold window: days to one month. | `short_term_t3`, `short_term_1w`, `short_term_2w`, `short_term_1m` |
| `long_conservative` | Trade ideas built on trend stability, liquidity, and lower realized risk. Hold window: months to a year. | `long_term_3m`, `long_term_6m`, `long_term_12m` |

The horizon codes are mnemonic, not normative: the math does not change
horizon-by-horizon inside a profile. The horizon code selects different
thresholds in §5 (action decision matrix) and §6 (entry/SL/TP).

### Weights (must sum to 1.0)

Each profile defines explicit weights for every sub-score. Weights are
binding for Phase 1; changes require an audit note.

| Sub-score        | `short_aggressive` | `long_conservative` |
|------------------|:------------------:|:-------------------:|
| `trend`          | 0.20 | 0.30 |
| `momentum`       | 0.25 | 0.10 |
| `volume`         | 0.15 | 0.05 |
| `liquidity`      | 0.10 | 0.20 |
| `risk_inverse`   | 0.10 | 0.15 |
| `market_regime`  | 0.10 | 0.10 |
| `portfolio_fit`  | 0.10 | 0.10 |
| `ml_probability` | 0.00 | 0.00 |
| **Sum**          | **1.00** | **1.00** |

The `ml_probability` weight is held at `0.0` in Phase 1 (no model). The slot
remains in the formula so that Phase 2 can introduce a non-zero weight
without breaking persistence or the API shape. See §4 for the rule on how
the engine handles a `null` ml score (we keep weight = 0, not pro-rata
redistribution — explicitness over arithmetic convenience).

---

## 3. Score inputs

All component sub-scores are integers in `[0, 100]`, clamped. `null` is
reserved for "data not available" and is documented per slot.

| Sub-score        | Source | Phase 1 behaviour |
|------------------|--------|-------------------|
| `trend`          | Reused from `services/scanner.py::compute_scores().trend` | See `scanner-signals.md` §5.1 |
| `momentum`       | Reused from `services/scanner.py::compute_scores().momentum` | See `scanner-signals.md` §5.2 |
| `volume`         | Reused from `services/scanner.py::compute_scores().volume` | See `scanner-signals.md` §5.3 |
| `liquidity`      | Reused from `services/scanner.py::compute_scores().liquidity` | See `scanner-signals.md` §5.4 |
| `risk_inverse`   | `100 - scanner.risk_score` | Higher = less volatile. Never null (scanner default is 50). |
| `market_regime`  | VNINDEX heuristic (this doc) | See §3.1 below. |
| `portfolio_fit`  | Position-weight heuristic (this doc) | See §3.2 below. |
| `ml_probability` | Phase 2 XGBoost output | Phase 1: always `null`. |

### 3.1 `market_regime` (Phase 1 heuristic)

Inputs: the VNINDEX daily close series, evaluated as of the same `as_of`
timestamp as the symbol scan.

Compute on the VNINDEX series:

- `ma50_index` — simple 50-day MA on closes.
- `slope_pct` — `(ma50_index_today - ma50_index_20d_ago) / ma50_index_20d_ago * 100`.
- `rsi14_index` — Wilder RSI(14) on VNINDEX closes (same recursion as the
  scanner, §3.2 of `scanner-signals.md`).

Map to a 0..100 regime score:

```
base = 50
+15 if slope_pct >  0
-15 if slope_pct <  0
+15 if rsi14_index in [50, 70]      # constructive momentum, not euphoric
+10 if rsi14_index in [40, 50)      # neutral-to-recovering
-15 if rsi14_index <  40            # weakness
-10 if rsi14_index >  70            # overbought regime (caution)
market_regime = clamp(base + bonuses, 0, 100)
```

Anchor values:

- ~`80` — slope up + RSI in the constructive band → bullish regime.
- ~`50` — flat slope or insufficient data → neutral default.
- ~`20` — slope down + weak RSI → bearish regime.

Default `50` when VNINDEX history is insufficient (`<50` bars) or the data
fetch fails. The engine MUST attach a `market_regime_unknown` warning when
defaulting.

### 3.2 `portfolio_fit` (Phase 1 heuristic)

Inputs: the user's current portfolio weight in the candidate symbol,
computed as `position.market_value / portfolio.total_market_value`
(`portfolio-pnl-spec.md` §4). If the user has no positions or the symbol is
absent, `portfolio_weight = 0`.

```
portfolio_weight is None (no portfolio data)    → 100
0   ≤ portfolio_weight <  0.005  (effectively absent)  → 100
0.005 ≤ portfolio_weight <  0.05                       → 50
portfolio_weight ≥ 0.05                                → 0
```

Rationale: new exposure adds diversification value when the symbol is
absent; once it is a meaningful slice (≥5%), further additions are
discouraged at the recommendation level. Reduction signals are handled by
the action matrix (§5), not by this score.

### 3.3 `ml_probability` (Phase 2 hook)

`null` in Phase 1. When Phase 2 ships, the value will be the XGBoost
probability of positive forward return over the horizon, scaled to
`[0, 100]`. Weight stays at 0 in Phase 1 (§4).

---

## 4. Final score & confidence

```
final_score = Σ (weight_i × score_i)   over sub-scores where score_i is not null
```

**Null handling (binding)**: if a sub-score is `null`, its term is omitted
**and the weight is NOT redistributed**. The engine reports `final_score` as
the raw sum. This makes "missing data" visibly degrade the score rather
than silently inflating the remaining components. The `reasons` field MUST
include a `MISSING_SCORE:<name>` code whenever this happens.

(In Phase 1 the only routinely-null score is `ml_probability`, whose
weight is already `0.0`, so the practical effect is nil. The rule still
matters as an explicit contract for Phase 2.)

```
confidence = clamp(final_score / 100, 0.0, 1.0)
```

**Confidence is NOT a probability of profit.** It is a normalized
rule-strength proxy — the share of the maximum possible weighted score
the symbol achieved given the profile. A symbol can have high confidence
and still lose money; a symbol can have low confidence and still rise.
The dashboard MUST display this caveat next to the confidence chip.

---

## 5. Action decision matrix

Actions are decided after `final_score`, `scores`, and signals are
known. Decisions are evaluated in the order below; the first match wins,
except that REJECTED (§7) always overrides.

The thresholds differ slightly between profiles. `long_conservative`
relaxes the momentum bar (long-horizon trades do not need a near-term
momentum kick) and tightens the trend bar (trend persistence matters
more).

| Action | `short_aggressive` triggers | `long_conservative` triggers |
|--------|-----------------------------|------------------------------|
| `BUY_CANDIDATE` | `final_score ≥ 70` **AND** `scores.trend ≥ 60` **AND** `LOW_LIQUIDITY ∉ signals` **AND** `scores.market_regime ≥ 50` **AND** `scores.momentum ≥ 55` | `final_score ≥ 70` **AND** `scores.trend ≥ 70` **AND** `LOW_LIQUIDITY ∉ signals` **AND** `scores.market_regime ≥ 50` **AND** `scores.momentum ≥ 45` |
| `WATCH` | `final_score ≥ 55` **AND** `scores.trend ≥ 50` | `final_score ≥ 55` **AND** `scores.trend ≥ 55` |
| `HOLD` | `40 ≤ final_score < 55` | `40 ≤ final_score < 55` |
| `REDUCE` | `final_score < 40` **AND** `portfolio_weight > 0` | `final_score < 40` **AND** `portfolio_weight > 0` |
| `SELL_CANDIDATE` | `trend == "DOWNTREND"` **AND** `scores.momentum ≤ 30` **AND** `portfolio_weight > 0` | `trend == "DOWNTREND"` **AND** `scores.momentum ≤ 35` **AND** `portfolio_weight > 0` |
| `AVOID` | `LOW_LIQUIDITY ∈ signals` **OR** `scores.risk ≥ 80` **OR** data quality critical | `LOW_LIQUIDITY ∈ signals` **OR** `scores.risk ≥ 75` **OR** data quality critical |
| `REJECTED` | Any REJECT guardrail fires (§7) — overrides every other action. | Same. |

Precedence rule on ties:

1. `REJECTED` (any §7 REJECT) — always overrides.
2. `AVOID` — informational hard-block, no order sizing.
3. `SELL_CANDIDATE` — only meaningful if `portfolio_weight > 0`.
4. `REDUCE` — only meaningful if `portfolio_weight > 0`.
5. `BUY_CANDIDATE`.
6. `WATCH`.
7. `HOLD` — residual default.

When the symbol is not in the portfolio, `REDUCE` and `SELL_CANDIDATE`
are skipped. `AVOID` and `BUY_CANDIDATE` / `WATCH` / `HOLD` still apply.

`final_score` and threshold values are integers; comparisons are
inclusive on `≥` and exclusive on `<`.

---

## 6. Entry zone, stop loss, take profit

Phase 1 uses simple ATR-based rules. The engine produces an entry zone, a
single stop-loss level, and a two-tier take-profit list. All values are in
VND. All are computed from `last_price` (latest quote price, falling back
to last close, exactly as the scanner does).

### Short-horizon profile (`short_aggressive`)

```
entry_zone   = [last_price * 0.99, last_price * 1.01]
stop_loss    = last_price - 1.5 * atr14
take_profit  = [last_price + 2.0 * atr14,
                last_price + 3.0 * atr14]
```

### Long-horizon profile (`long_conservative`)

```
entry_zone   = [last_price * 0.97, last_price * 1.03]
stop_loss    = last_price - 2.5 * atr14
take_profit  = [last_price + 4.0 * atr14,
                last_price + 6.0 * atr14]
```

### ATR-unavailable fallback

When `atr14` is `null` (insufficient history; see scanner §2 minimums) the
engine falls back to fixed percentage levels:

| Profile             | `stop_loss`         | `take_profit`                     |
|---------------------|---------------------|-----------------------------------|
| `short_aggressive`  | `last_price * 0.95` | `[last_price * 1.10, last_price * 1.15]` |
| `long_conservative` | `last_price * 0.90` | `[last_price * 1.20, last_price * 1.35]` |

The engine MUST attach an `atr_fallback_pct` warning when this branch
is taken.

### last_price-unavailable fallback

When `last_price` is `null` (no quote and no bars) every price-level field
(`entry_zone`, `stop_loss`, `take_profit`, `estimated_quantity`,
`estimated_total_cost`) is returned as `null`. The action MUST be downgraded
to `REJECTED` with code `no_last_price`.

### Rounding

All price levels are rounded to the nearest 10 VND for HOSE and 100 VND
for HNX/UPCoM as a display convenience. The raw float is also stored.
*(Phase 2 will introduce true VN tick-rule rounding; Phase 1 approximation
is acceptable since these are research zones, not orders.)*

---

## 7. Risk guardrails

Binary checks evaluated before publication. WARNs attach a warning code
and a human-readable suffix to `warnings`; REJECTs override the action
to `REJECTED` and set `status = "REJECTED"`. A recommendation can carry
both warnings and a REJECT (e.g. low-liquidity REJECT + stale-data WARN).

| Code | Trigger | Severity | Inspects | Notes |
|------|---------|----------|----------|-------|
| `low_liquidity` | `LOW_LIQUIDITY` flag in scanner signals (i.e. `avg_value_20d < 1e9 VND`) | REJECT | `scores`, `signals` | Hard block. Action → `REJECTED`. |
| `avg_value_20d_below_threshold` | `1e9 ≤ avg_value_20d < 5e9 VND` | WARN | `indicators.avg_value_20d` | Marginal liquidity. |
| `position_size_exceeds_max_adv_pct` | `position_size_vnd > 0.005 * avg_value_20d` | REJECT | `position_size_vnd`, `indicators.avg_value_20d` | Caps single-day market impact. Action → `REJECTED`. |
| `insufficient_settled_cash` | `cash_balances.settled_cash` known **AND** `position_size_vnd > settled_cash` | WARN | `assets.settled_cash`, `position_size_vnd` | Does not block; user may wire funds. |
| `portfolio_weight_too_high` | `existing_weight + projected_new_weight > 0.15` | REJECT | `portfolio_fit` input + `position_size_vnd / total_equity` | Concentration cap. Action → `REJECTED`. |
| `price_outside_ceiling_floor` | `last_price` within 1% of daily ceiling or floor band | WARN | `last_price`, `daily_ceiling`, `daily_floor` | **Phase 1: ceiling/floor not available from provider. Skip silently — do not emit warning and do not block.** Documented seam for Phase 2. |
| `data_stale` | `latest_quote.stale == True` **OR** `now - as_of > 5 min` (intraday) **OR** `> 1 day` (EOD) | WARN | `latest_quote.stale`, `as_of` | Reuses scanner `stale_data` semantics. |
| `data_quality_critical` | Upstream provider flagged the symbol's recent data as critical (`market_cache` quality flag, when present) | REJECT | Quote/bar quality flag | Action → `REJECTED`. |
| `missing_fee_tax_profile` | User has no `cash_balances` row for the default account yet | WARN | `cash_balances` lookup | Cost estimate uses defaults (§8). |
| `pending_cash_requires_advance` | `position_size_vnd > settled_cash` **AND** `position_size_vnd ≤ settled_cash + pending_cash` | WARN | `cash_balances` | Funding the trade would require a cash advance; surfaces the implicit fee. |

REJECT behaviour: if any REJECT triggers, the engine sets
`action = "REJECTED"` and `status = "REJECTED"` but still returns the
record (with the originally-computed sub-scores, reasons, warnings, and
price levels) so the UI can show it under a "Rejected" section for
auditability.

---

## 8. Position sizing

```
position_size_vnd = min(
    50_000_000,                                  # personal-account cap
    0.05 * total_equity_if_known,                # 5% of equity cap
    0.005 * avg_value_20d                        # 0.5% of 20-day ADV cap
)
```

When `total_equity_if_known` is `null` (no `cash_balances` row), the second
term is dropped from the `min` and a `missing_fee_tax_profile` WARN is
attached (§7). When `avg_value_20d` is `null`, the third term is dropped
and an `insufficient_liquidity_history` WARN is attached.

Lot rounding (HOSE/HNX/UPCoM equity lot = 100 shares):

```
estimated_quantity = floor( position_size_vnd / (last_price * 100) ) * 100
```

If `estimated_quantity == 0` after rounding (position too small to round
to a full lot), the engine attaches a `position_too_small_for_lot` WARN
and returns `0`. The action is **not** downgraded — the user may still
want the WATCH signal.

Estimated total cost (gross of slippage and brokerage; not subtracted
from confidence):

```
estimated_total_cost =
    round( estimated_quantity * last_price
           * (1 + brokerage_pct + slippage_pct) )
```

Defaults (configurable via an engine-level config dict):

| Param            | Default | Notes |
|------------------|---------|-------|
| `brokerage_pct`  | 0.0015  | 0.15% — typical SSI retail rate. |
| `slippage_pct`   | 0.0010  | 0.10% — single-side estimate for personal sizes. |

These are gross-of-VAT and gross-of-sell-tax — the engine intentionally
under-states all-in cost on the BUY side; sell-side taxes are handled by
the portfolio/cost surface (`portfolio-pnl-spec.md` §8) so we don't
double-count.

---

## 9. Output schema (definitive)

Pydantic models live at `apps/api/src/schemas/recommendation.py`.
Field names, types, and semantics below are binding.

```python
Profile = Literal["short_aggressive", "long_conservative"]

Horizon = Literal[
    "short_term_t3",
    "short_term_1w",
    "short_term_2w",
    "short_term_1m",
    "long_term_3m",
    "long_term_6m",
    "long_term_12m",
]

Action = Literal[
    "BUY_CANDIDATE",
    "WATCH",
    "HOLD",
    "REDUCE",
    "SELL_CANDIDATE",
    "AVOID",
    "REJECTED",
]

ValidationStatus = Literal["VALID", "WARNING", "REJECTED"]
```

`RecommendationScores`:

| Field            | Type           | Notes |
|------------------|----------------|-------|
| `trend`          | `int 0..100`   | From scanner. |
| `momentum`       | `int 0..100`   | From scanner. |
| `volume`         | `int 0..100`   | From scanner. |
| `liquidity`      | `int 0..100`   | From scanner. |
| `risk_inverse`   | `int 0..100`   | `100 - scanner.risk`. |
| `market_regime`  | `int 0..100`   | §3.1. |
| `portfolio_fit`  | `int 0..100`   | §3.2. |
| `ml_probability` | `int 0..100 \| None` | `None` in Phase 1. |

`Recommendation`:

| Field                  | Type                              | Notes |
|------------------------|-----------------------------------|-------|
| `symbol`               | `str`                             | Upper-cased. |
| `horizon`              | `Horizon`                         | See literal above. |
| `horizon_label`        | `str`                             | Human-readable, e.g. `"Swing 1–2 weeks"`. |
| `profile`              | `Profile`                         | The profile used. |
| `action`               | `Action`                          | After §5 + §7 override. |
| `confidence`           | `float 0..1`                      | §4. |
| `last_price`           | `float \| None`                   | Quote-or-close, same as scanner. |
| `entry_zone`           | `tuple[float, float] \| None`     | `null` when `last_price` is null. |
| `stop_loss`            | `float \| None`                   | `null` when `last_price` is null. |
| `take_profit`          | `tuple[float, float] \| None`     | Two levels; `null` when `last_price` is null. |
| `position_size_vnd`    | `int`                             | Rounded VND. `0` if sizing fails. |
| `estimated_quantity`   | `int`                             | Lot-rounded share count. |
| `estimated_total_cost` | `int`                             | Rounded VND. `0` if quantity is 0. |
| `scores`               | `RecommendationScores`            | Always present; null only inside `ml_probability`. |
| `final_score`          | `int 0..100`                      | §4. |
| `reasons`              | `list[str]`                       | Short codes + suffix. ≥ 3 entries when not `REJECTED`. |
| `warnings`             | `list[str]`                       | Empty list, never null, when no WARN. |
| `status`               | `ValidationStatus`                | §11. |
| `as_of`                | `str` (ISO-8601, UTC)             | Same convention as scanner. |

The route layer returns either a single `Recommendation` for the
`GET /recommendations/{symbol}` endpoint or a `list[Recommendation]` for
the batch endpoint. Both shapes carry the global disclaimer envelope
already in use by `/portfolio/*` (`portfolio-pnl-spec.md` §1).

---

## 10. Explainability

For every recommendation:

- `reasons` MUST contain at least **3 entries** when `action` is one of
  `BUY_CANDIDATE`, `WATCH`, `HOLD`, `REDUCE`, `SELL_CANDIDATE`, `AVOID`.
  Each entry is a short code plus a human-readable suffix separated by
  `" | "`. Examples:
    - `"TREND_UPTREND_CONFIRMED | MA20>MA50 and price>MA20"`
    - `"MOMENTUM_BREAKOUT_20D | Closed above 20-day high"`
    - `"REGIME_BULLISH | VNINDEX 50DMA slope +2.1%, RSI 58"`
    - `"PORTFOLIO_FIT_NEW_EXPOSURE | Symbol not currently held"`
- When `action == "REJECTED"`, `reasons` MUST include at least the REJECT
  codes (one per triggered REJECT guardrail) — there is no minimum-three
  rule for rejections.
- `warnings` MUST include every triggered WARN guardrail (§7) plus any
  scanner-level warning passed through (`insufficient_history`,
  `stale_data`, …). Order is stable.
- Both fields MUST be returned as empty lists (`[]`) — not `null`, not
  omitted — when no entries apply. The frontend depends on the empty-list
  invariant for layout.

Reason codes are append-only: do not rename existing codes once shipped.
New codes require a doc update and an audit note.

---

## 11. Validation status semantics

```
status = "REJECTED"  iff  any REJECT guardrail fired
status = "WARNING"   iff  status != REJECTED AND warnings is non-empty
status = "VALID"     iff  status != REJECTED AND warnings is empty
```

Notes:

- A `REJECTED` record is **still returned** by the API (action overridden;
  sub-scores preserved; price levels preserved). The UI groups these under
  a "Rejected" section with the triggered REJECT codes visible.
- A `WARNING` record is functionally identical to `VALID` except for the
  presence of warnings; the action is unchanged. The UI shows a yellow
  chip with the warning count.
- `VALID` is the "no notes" path. Most recommendations on a clean
  large-cap symbol with fresh data should land here.

---

## 12. Persistence

Recommendations are returned by the API live (no caching beyond the
quote/bar caches the scanner already uses), but ALSO appended to
`recommendation_snapshots` as one row per `(user_id, symbol, horizon,
created_at)`.

**Schema gap (must be addressed in a new migration before this engine
ships)**: the existing table in `0001_init.sql` allows only
`horizon in ('INTRADAY_5M','INTRADAY_15M','EOD')` and
`action in ('BUY','SELL','HOLD','REDUCE')`. Phase 1 of this engine emits
seven horizons (§9) and seven actions (§9). Backend MUST add a migration
(suggested `0003_recommendation_taxonomy.sql`) that:

1. Drops the existing `horizon` and `action` check constraints.
2. Re-adds check constraints matching the literals in §9 exactly.
3. Adds a `profile text not null check (profile in ('short_aggressive','long_conservative'))` column.
4. Adds a `final_score smallint check (final_score between 0 and 100)` column.
5. Adds a `validation_status text not null check (validation_status in ('VALID','WARNING','REJECTED'))` column, default `'VALID'`.

The existing `reasons`, `warnings`, `scores` JSONB columns are reused
verbatim. The `confidence numeric(5,4)` column is reused verbatim.

Mapping `Recommendation` → table row:

| Table column     | Recommendation field             |
|------------------|----------------------------------|
| `user_id`        | (auth context, not in the model) |
| `symbol`         | `symbol`                         |
| `horizon`        | `horizon`                        |
| `action`         | `action`                         |
| `confidence`     | `confidence`                     |
| `status`         | Lifecycle: `'OPEN'` on insert, mutated later by UI actions (ack/dismiss). NOT the same field as `validation_status`. |
| `validation_status` | `status` (from the model — VALID/WARNING/REJECTED) |
| `profile`        | `profile`                        |
| `final_score`    | `final_score`                    |
| `reasons`        | `reasons` (JSONB array of strings) |
| `warnings`       | `warnings` (JSONB array of strings) |
| `scores`         | `scores` (JSONB object, including `ml_probability`) |
| `created_at`     | server `now()`; also informs `as_of` |

The existing table's `status` column is a **lifecycle** flag
(`OPEN`/`ACKED`/`DISMISSED`/`EXPIRED`) and is distinct from the
**validation** status defined in §11. The migration adds
`validation_status` so both can be persisted without overloading either
column.

---

## 13. Limitations (Phase 1)

1. **No ML probability.** `ml_probability` is always `null`; its weight is
   `0.0`. Phase 2 introduces an XGBoost head with proper temporal CV.
2. **Regime detection is shallow.** `market_regime` uses only VNINDEX
   50DMA slope + RSI. No breadth, no macro, no sector overlay.
3. **No sector / group fit.** `portfolio_fit` is a position-weight rule
   only — it does not penalize over-concentration in a sector.
4. **Ceiling/floor pricing not modeled.** Daily price-band proximity
   cannot be checked because the current provider does not expose
   ceiling/floor; the relevant guardrail (§7) is a documented seam.
5. **Portfolio fit is naive.** Thresholds (0.5%, 5%) are heuristics, not
   derived from a risk model.
6. **All thresholds are heuristics, not optimized.** No walk-forward
   validation, no statistical significance testing.
7. **Confidence is NOT a probability.** Documented (§4); the UI MUST also
   surface this caveat next to the confidence chip.
8. **VN tick rounding is approximated.** Prices are rounded to the
   nearest 10 VND (HOSE) or 100 VND (HNX/UPCoM) for display; true tick
   rules are deferred.
9. **No corporate-action awareness.** Inherited from the scanner — a
   symbol on ex-day may produce misleading scores.
10. **Single source data.** Whatever the route layer hands in is what
    gets scored; no cross-provider reconciliation inside the engine.
11. **Cost estimate excludes VAT and sell tax.** `estimated_total_cost` is
    BUY-side only; sell-side taxes are tracked by the cost surface
    (`portfolio-pnl-spec.md` §8) to avoid double-counting.

---

## 14. Phase 2 / Phase 3 roadmap

### Phase 2

- **XGBoost `ml_probability`** trained on scanner sub-scores + indicator
  deltas + forward-return labels (one model per horizon). Output a
  calibrated probability; map to 0..100 for the sub-score slot. Weight
  starts at 0.10 and is taken from `momentum` / `trend` pro-rata after
  walk-forward validation.
- **Regime detection v2** — index breadth (% above MA50 across HOSE),
  sector rotation, and macro flags (VND rates, oil) feed `market_regime`.
- **Walk-forward backtest validation** of every threshold in §5 and §7.
  Thresholds become parameters, not constants, in the engine config.
- **Sector / group fit** — `portfolio_fit` factors in sector-weight caps
  pulled from the position table.
- **VN tick-rule pricing** — replace the §6 rounding with the official
  tick ladder per exchange.

### Phase 3

- **Paper-trading ledger.** Recommendations flow into a `paper_orders`
  table; outcome (fill, slippage, realized PnL) is tracked and fed back
  to the threshold-tuning loop.
- **Broker-API integration**, gated behind a feature flag. No
  auto-execute. Confirmation step + kill switch + max order size + daily
  loss guard (per `docs/product-vision.md` §Phase 4).

---

## 15. References

- Wilder, J. W. (1978). *New Concepts in Technical Trading Systems.*
  Trend Research. Source of the RSI and ATR recursion reused via the
  scanner.
- Donchian, R. — channel-breakout concept underlying `high_20d` and
  `high_55d` used by `momentum` and the `BREAKOUT_20D` flag.
- Internal: `docs/scanner-signals.md` (sub-score math), 
  `docs/portfolio-pnl-spec.md` (portfolio + cash inputs),
  `docs/portfolio-assets-mvp.md` (phase boundaries),
  `docs/architecture.md` (module map),
  `../../docs/trading-rules.md` (no-lookahead + recommend-only rules),
  `../../docs/product-vision.md` (phase plan).

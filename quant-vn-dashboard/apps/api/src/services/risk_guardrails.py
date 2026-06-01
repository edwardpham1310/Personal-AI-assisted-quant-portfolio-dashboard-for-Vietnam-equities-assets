"""Risk guardrails for the Phase 1 recommendation engine.

Pure functions. No I/O. Given a candidate ``RecommendationResult`` and a
small evidence bundle (cash, ADV, weight, staleness flags), return the
list of guardrail hits, the final action, and the final status.

Severity model:
    * ``REJECT`` — downgrades action to ``REJECTED`` and status to ``REJECTED``.
    * ``WARN``   — preserves action, sets status to ``WARNING``.
    * ``INFO``   — informational only; does not change status.

Every label here is a **research signal · not financial advice · no orders
placed** — guardrails exist to make that disclaimer load-bearing.
"""

from __future__ import annotations

from dataclasses import dataclass

from schemas.recommendation import (
    GuardrailHit,
    GuardrailSeverity,
    RecommendationAction,
    RecommendationResult,
    RecommendationStatus,
)

# ── Thresholds (VND-scaled where applicable) ────────────────────────────────


LOW_LIQUIDITY_THRESHOLD = 1_000_000_000           # < 1B VND avg 20d value → REJECT
LIGHT_LIQUIDITY_THRESHOLD = 5_000_000_000         # 1B–5B → WARN
MAX_ADV_PCT_HARD = 0.005                          # 0.5% of avg_value_20d → REJECT above
PORTFOLIO_WEIGHT_HARD_CAP = 0.15                  # 15% post-trade weight → REJECT
STALE_AS_OF_SECONDS = 300                         # > 5 min → stale data


@dataclass(frozen=True)
class GuardrailEvidence:
    """Evidence bundle fed to ``apply_guardrails`` from the route layer."""

    avg_value_20d: float | None = None
    position_size_vnd: int | None = None
    total_equity: float | None = None
    settled_cash: float | None = None
    pending_cash: float | None = None
    has_cash_balance_row: bool = True
    quote_stale: bool = False
    as_of_age_seconds: float | None = None
    data_quality_critical: bool = False
    current_position_weight_pct: float | None = None  # 0..1 fraction; None when unknown
    last_price: float | None = None
    ceiling_price: float | None = None  # Phase 1: usually None — provider doesn't expose it
    floor_price: float | None = None


# ── Individual checks ───────────────────────────────────────────────────────


def _hit(code: str, severity: GuardrailSeverity, message: str) -> GuardrailHit:
    return GuardrailHit(code=code, severity=severity, message=message)


def check_liquidity(ev: GuardrailEvidence) -> list[GuardrailHit]:
    if ev.avg_value_20d is None:
        return []
    hits: list[GuardrailHit] = []
    if ev.avg_value_20d < LOW_LIQUIDITY_THRESHOLD:
        hits.append(
            _hit(
                "low_liquidity",
                "REJECT",
                f"avg_value_20d={ev.avg_value_20d:,.0f} VND below 1B floor",
            )
        )
    elif ev.avg_value_20d < LIGHT_LIQUIDITY_THRESHOLD:
        hits.append(
            _hit(
                "avg_value_20d_below_threshold",
                "WARN",
                f"avg_value_20d={ev.avg_value_20d:,.0f} VND below 5B comfort line",
            )
        )
    return hits


def check_adv(ev: GuardrailEvidence) -> list[GuardrailHit]:
    if ev.avg_value_20d is None or ev.position_size_vnd is None:
        return []
    cap = ev.avg_value_20d * MAX_ADV_PCT_HARD
    if ev.position_size_vnd > cap and cap > 0:
        return [
            _hit(
                "position_size_exceeds_max_adv_pct",
                "REJECT",
                f"position_size_vnd={ev.position_size_vnd:,} > 0.5% ADV cap ({cap:,.0f})",
            )
        ]
    return []


def check_settled_cash(ev: GuardrailEvidence) -> list[GuardrailHit]:
    """WARN when the user clearly doesn't have settled cash to fund the position."""
    if ev.total_equity is None or ev.settled_cash is None or ev.position_size_vnd is None:
        return []
    if ev.position_size_vnd > ev.settled_cash:
        return [
            _hit(
                "insufficient_settled_cash",
                "WARN",
                f"position_size_vnd={ev.position_size_vnd:,} > settled_cash={ev.settled_cash:,.0f}",
            )
        ]
    return []


def check_portfolio_weight(ev: GuardrailEvidence) -> list[GuardrailHit]:
    if (
        ev.current_position_weight_pct is None
        or ev.total_equity is None
        or ev.position_size_vnd is None
        or ev.total_equity <= 0
    ):
        return []
    new_weight = ev.current_position_weight_pct + (
        ev.position_size_vnd / ev.total_equity
    )
    if new_weight > PORTFOLIO_WEIGHT_HARD_CAP:
        return [
            _hit(
                "portfolio_weight_too_high",
                "REJECT",
                f"post-trade weight {new_weight*100:.1f}% exceeds 15% cap",
            )
        ]
    return []


def check_ceiling_floor(ev: GuardrailEvidence) -> list[GuardrailHit]:
    """Phase 1: ceiling/floor not reliably exposed by the provider."""
    if ev.ceiling_price is None and ev.floor_price is None:
        return [
            _hit(
                "ceiling_floor_unavailable",
                "INFO",
                "ceiling/floor prices not provided in Phase 1",
            )
        ]
    if ev.last_price is None:
        return []
    hits: list[GuardrailHit] = []
    if ev.ceiling_price is not None and ev.last_price >= ev.ceiling_price * 0.99:
        hits.append(
            _hit(
                "price_outside_ceiling_floor",
                "WARN",
                "last_price within 1% of daily ceiling",
            )
        )
    if ev.floor_price is not None and ev.last_price <= ev.floor_price * 1.01:
        hits.append(
            _hit(
                "price_outside_ceiling_floor",
                "WARN",
                "last_price within 1% of daily floor",
            )
        )
    return hits


def check_data_stale(ev: GuardrailEvidence) -> list[GuardrailHit]:
    if ev.quote_stale:
        return [_hit("data_stale", "WARN", "quote marked stale by provider")]
    if ev.as_of_age_seconds is not None and ev.as_of_age_seconds > STALE_AS_OF_SECONDS:
        return [
            _hit(
                "data_stale",
                "WARN",
                f"as_of older than {STALE_AS_OF_SECONDS}s ({ev.as_of_age_seconds:.0f}s)",
            )
        ]
    return []


def check_data_quality(ev: GuardrailEvidence) -> list[GuardrailHit]:
    if ev.data_quality_critical:
        return [
            _hit(
                "data_quality_critical",
                "REJECT",
                "upstream data quality flagged critical",
            )
        ]
    return []


def check_fee_tax_profile(ev: GuardrailEvidence) -> list[GuardrailHit]:
    if not ev.has_cash_balance_row:
        return [
            _hit(
                "missing_fee_tax_profile",
                "WARN",
                "no cash_balances row — fee/tax assumptions are defaults",
            )
        ]
    return []


def check_pending_cash_advance(ev: GuardrailEvidence) -> list[GuardrailHit]:
    if (
        ev.pending_cash is None
        or ev.settled_cash is None
        or ev.position_size_vnd is None
    ):
        return []
    if ev.pending_cash > 0 and ev.settled_cash < ev.position_size_vnd:
        return [
            _hit(
                "pending_cash_requires_advance",
                "WARN",
                "funding the position would require a cash advance from pending settlement",
            )
        ]
    return []


# Ordered for stable evaluation; REJECTs surface first in the final list.
_CHECKS = (
    check_data_quality,
    check_liquidity,
    check_adv,
    check_portfolio_weight,
    check_data_stale,
    check_settled_cash,
    check_pending_cash_advance,
    check_fee_tax_profile,
    check_ceiling_floor,
)


# ── Orchestration ───────────────────────────────────────────────────────────


def evaluate(ev: GuardrailEvidence) -> list[GuardrailHit]:
    """Run every check and return the union of hits, REJECTs first."""
    rejects: list[GuardrailHit] = []
    warns: list[GuardrailHit] = []
    infos: list[GuardrailHit] = []
    for check in _CHECKS:
        for hit in check(ev):
            if hit.severity == "REJECT":
                rejects.append(hit)
            elif hit.severity == "WARN":
                warns.append(hit)
            else:
                infos.append(hit)
    return rejects + warns + infos


def apply_guardrails(
    rec: RecommendationResult, ev: GuardrailEvidence
) -> tuple[RecommendationAction, RecommendationStatus, list[str], list[str]]:
    """Return ``(action, status, warnings, reasons_extra)`` after running checks.

    Warnings preserve the original ``rec.warnings`` and append new codes.
    Reasons get one extra code per REJECT so the UI can explain the veto.
    """
    hits = evaluate(ev)
    warnings: list[str] = list(rec.warnings)
    reasons_extra: list[str] = []

    has_reject = False
    has_warn = False
    for hit in hits:
        if hit.severity == "REJECT":
            has_reject = True
            reasons_extra.append(f"GUARDRAIL_REJECT_{hit.code.upper()}")
            warnings.append(hit.code)
        elif hit.severity == "WARN":
            has_warn = True
            warnings.append(hit.code)
        else:
            # INFO does not pollute warnings — surfaced via /preview hits instead.
            continue

    if has_reject:
        return "REJECTED", "REJECTED", warnings, reasons_extra
    if has_warn:
        return rec.action, "WARNING", warnings, reasons_extra
    return rec.action, "VALID", warnings, reasons_extra

"""Shared strength/signal mapping for recommendations.

The numeric scoring lives in ``recommendation_engine`` (the 7-component
``final_score`` already used by /recommendations/symbol and /watchlist). This
module is the SINGLE place that maps that output to the dashboard's display
vocabulary, so Top Picks, watchlist recs, and the explain view stay consistent.

Trading safety: the signal vocabulary is deliberately non-advice — there is no
"buy", "must", "guaranteed", or "sure profit" wording. These are research
labels for decision support only.
"""

from __future__ import annotations

from schemas.recommendation import (
    RecommendationExplanation,
    RecommendationResult,
    ScoreContribution,
)
from services.recommendation_engine import PROFILE_WEIGHTS

# Score → strength band (per the Feature 2 spec).
STRONG_MIN = 80
NEUTRAL_MIN = 60


def strength_from_score(score: int) -> str:
    """Map a 0..100 quant score to Weak | Neutral | Strong."""
    if score >= STRONG_MIN:
        return "Strong"
    if score >= NEUTRAL_MIN:
        return "Neutral"
    return "Weak"


def signal_from(action: str, score: int) -> str:
    """Map the engine action (+ score) to a safer display signal.

    Engine actions: BUY_CANDIDATE / WATCH / HOLD / REDUCE / SELL_CANDIDATE /
    AVOID / REJECTED. We never surface "buy"; a strong candidate is
    "Actionable", a moderate one "Accumulate", a weak one "Watch".
    """
    a = (action or "").upper()
    if a == "BUY_CANDIDATE":
        if score >= 75:
            return "Actionable"
        if score >= NEUTRAL_MIN:
            return "Accumulate"
        return "Watch"
    if a == "WATCH":
        return "Watch"
    if a == "HOLD":
        return "Wait"
    if a == "REDUCE":
        return "Take Profit"
    if a in ("SELL_CANDIDATE", "AVOID"):
        return "Avoid"
    if a == "REJECTED":
        return "Risky"
    return "Watch"


# ── Explainability (Feature 4) ────────────────────────────────────────────────

# Engine score key → display label. Order is the canonical display order; the
# explain view re-sorts by contribution but this fixes labels + completeness.
COMPONENT_LABELS: dict[str, str] = {
    "trend": "Trend",
    "momentum": "Momentum",
    "volume": "Volume",
    "liquidity": "Liquidity",
    "risk_inverse": "Risk control",
    "market_regime": "Market regime",
    "portfolio_fit": "Portfolio fit",
    "ml_probability": "ML probability",
}


def _component_value(scores: object, key: str) -> float | None:
    """Read a 0..100 component value off a RecommendationScores.

    ``ml_probability`` is stored in [0,1] and weighted as 0..100 by the engine,
    so we scale it the same way here. Missing/None → None (N/A, weight unused).
    """
    if key == "ml_probability":
        raw = getattr(scores, "ml_probability", None)
        return None if raw is None else float(raw) * 100.0
    raw = getattr(scores, key, None)
    return None if raw is None else float(raw)


def build_contributions(scores: object, profile: str) -> list[ScoreContribution]:
    """Per-component weighted contributions for a profile, sorted high→low.

    Mirrors ``recommendation_engine.compute_final_score``: each contribution is
    ``weight * value`` (value in 0..100). A None component contributes 0 and its
    weight is *not* redistributed — same rule the engine applies.
    """
    weights = PROFILE_WEIGHTS.get(profile, {})
    rows: list[ScoreContribution] = []
    for key, label in COMPONENT_LABELS.items():
        weight = float(weights.get(key, 0.0))
        value = _component_value(scores, key)
        contribution = 0.0 if value is None else round(weight * value, 1)
        rows.append(
            ScoreContribution(
                component=key,
                label=label,
                score=None if value is None else int(round(value)),
                weight=round(weight, 4),
                contribution=contribution,
            )
        )
    rows.sort(key=lambda c: c.contribution, reverse=True)
    return rows


def _summarize(
    rec: RecommendationResult,
    contributions: list[ScoreContribution],
    strength: str,
) -> str:
    """One plain sentence — research-signal language only, no advice wording."""
    drivers = [c.label for c in contributions if c.contribution > 0][:2]
    lead = (
        f"{strength} composite ({rec.final_score}/100)"
        if drivers
        else f"{strength} composite ({rec.final_score}/100), no positive drivers"
    )
    if drivers:
        lead += " led by " + " and ".join(drivers)
    risk = (list(rec.warnings) + list(rec.rejection_reasons))[:1]
    if risk:
        lead += f". Main risk: {risk[0]}"
    return lead + "."


def build_explanation(rec: RecommendationResult) -> RecommendationExplanation:
    """Derive a structured, non-advice explanation from an engine result."""
    contributions = build_contributions(rec.scores, rec.profile)
    strength = strength_from_score(rec.final_score)
    return RecommendationExplanation(
        symbol=rec.symbol,
        profile=rec.profile,
        horizon=rec.horizon,
        action=rec.action,
        strength=strength,  # type: ignore[arg-type]
        signal=signal_from(rec.action, rec.final_score),  # type: ignore[arg-type]
        final_score=rec.final_score,
        confidence=rec.confidence,
        action_threshold_used=rec.action_threshold_used,
        contributions=contributions,
        summary=_summarize(rec, contributions, strength),
        reasons=list(rec.reasons),
        risks=list(rec.warnings) + list(rec.rejection_reasons),
        data_status=rec.data_status,
        as_of=rec.as_of,
    )

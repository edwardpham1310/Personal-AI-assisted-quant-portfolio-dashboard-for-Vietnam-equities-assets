"""Feature 4 — /recommendations/explain + pure explanation builders."""

from __future__ import annotations

from fastapi.testclient import TestClient

from schemas.recommendation import RecommendationResult, RecommendationScores
from services import recommendation_scoring as scoring
from services.recommendation_engine import PROFILE_WEIGHTS

_FORBIDDEN = ["guaranteed", "sure profit", "sure win", "must buy", "must sell"]


def _scores(**over: int) -> RecommendationScores:
    base = dict(
        trend=80, momentum=70, volume=60, liquidity=50,
        risk=40, risk_inverse=60, market_regime=55, portfolio_fit=100,
        ml_probability=None,
    )
    base.update(over)
    return RecommendationScores(**base)  # type: ignore[arg-type]


def _result(scores: RecommendationScores, *, profile="short_aggressive") -> RecommendationResult:
    return RecommendationResult(
        symbol="FPT", profile=profile, horizon="SHORT_2W",
        action="WATCH", status="VALID", confidence=0.6, final_score=72,
        scores=scores, as_of="2026-01-01T00:00:00+00:00",
        reasons=["Uptrend with volume confirmation", "RSI healthy"],
        warnings=["liquidity thinner than peers"],
    )


# ── pure builders ─────────────────────────────────────────────────────────────


def test_build_contributions_covers_all_components_sorted_desc() -> None:
    rows = scoring.build_contributions(_scores(), "short_aggressive")
    assert {r.component for r in rows} == set(scoring.COMPONENT_LABELS)
    contribs = [r.contribution for r in rows]
    assert contribs == sorted(contribs, reverse=True)


def test_contribution_equals_weight_times_score() -> None:
    profile = "short_aggressive"
    rows = scoring.build_contributions(_scores(), profile)
    weights = PROFILE_WEIGHTS[profile]
    for r in rows:
        if r.score is None:
            assert r.contribution == 0.0
        else:
            assert r.contribution == round(weights[r.component] * r.score, 1)


def test_ml_probability_none_contributes_zero() -> None:
    rows = scoring.build_contributions(_scores(ml_probability=None), "short_aggressive")
    ml = next(r for r in rows if r.component == "ml_probability")
    assert ml.score is None
    assert ml.contribution == 0.0
    assert ml.weight > 0  # weight present but unused — not redistributed


def test_weights_match_profile_and_sum_to_one() -> None:
    for profile in ("short_aggressive", "long_conservative"):
        rows = scoring.build_contributions(_scores(), profile)
        assert round(sum(r.weight for r in rows), 4) == 1.0


def test_build_explanation_summary_has_no_advice_wording() -> None:
    exp = scoring.build_explanation(_result(_scores()))
    low = exp.summary.lower()
    for w in _FORBIDDEN:
        assert w not in low
    assert exp.strength in {"Weak", "Neutral", "Strong"}
    assert exp.signal in {
        "Watch", "Actionable", "Accumulate", "Wait", "Avoid", "Risky", "Take Profit"
    }
    assert exp.risks == ["liquidity thinner than peers"]


# ── route ─────────────────────────────────────────────────────────────────────


def test_explain_requires_auth(client: TestClient) -> None:
    assert client.get("/recommendations/explain/FPT").status_code == 401


def test_explain_returns_breakdown(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get(
        "/recommendations/explain/FPT?profile=short_aggressive&horizon=SHORT_2W",
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol"] == "FPT"
    assert body["disclaimer"].startswith("research signal")
    assert len(body["contributions"]) == len(scoring.COMPONENT_LABELS)
    assert body["summary"]
    low = body["summary"].lower()
    for w in _FORBIDDEN:
        assert w not in low
    # contributions sorted high→low
    cs = [c["contribution"] for c in body["contributions"]]
    assert cs == sorted(cs, reverse=True)


def test_explain_does_not_persist_snapshot(client: TestClient, auth_headers, fake_db) -> None:
    headers, _ = auth_headers()
    before = len(fake_db._tables.get("recommendation_snapshots", []))
    r = client.get("/recommendations/explain/FPT", headers=headers)
    assert r.status_code == 200
    after = len(fake_db._tables.get("recommendation_snapshots", []))
    assert after == before


def test_explain_400_on_invalid_symbol(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    assert client.get("/recommendations/explain/!@#", headers=headers).status_code == 400


def test_explain_unknown_symbol_is_research_only(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/recommendations/explain/NOSUCH", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "REJECTED"
    assert body["final_score"] == 0
    assert body["signal"] == "Risky"

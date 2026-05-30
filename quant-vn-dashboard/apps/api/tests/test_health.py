"""Health + system status smoke tests.

The original tests in this file pre-dated the Phase 1 system-status rewrite
that moved ``/system/status`` behind auth and expanded its response shape.
They have been rewritten to match the current contract.

The previous SSE heartbeat test is now SKIPPED in ``test_stream_routes.py``
because TestClient deadlocks on infinite event streams (see TODO there).
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["env"] == "development"
    assert body["version"] == "0.1.0"


def test_system_health_is_public(client: TestClient) -> None:
    """``/system/health`` is the only ``/system/*`` endpoint that does not
    require auth — it must return 200 with a status in {ok, degraded, down}."""
    response = client.get("/system/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded", "down"}
    assert body["env"] == "development"
    # Must not leak any secret material.
    leakage_substrings = [
        "service_role",
        "jwt_secret",
        "consumer_secret",
        "db_password",
    ]
    serialized = str(body).lower()
    for needle in leakage_substrings:
        assert needle not in serialized, f"/system/health leaked '{needle}'"


def test_system_status_requires_auth(client: TestClient) -> None:
    assert client.get("/system/status").status_code == 401


def test_system_status_returns_expected_shape(client: TestClient, auth_headers) -> None:
    """``/system/status`` is auth-gated and returns the aggregated shape
    introduced by the Phase 1 review (provider/cache/supabase/duckdb/poller/
    data_quality)."""
    headers, _ = auth_headers()
    response = client.get("/system/status", headers=headers)
    assert response.status_code == 200
    body = response.json()
    # Top-level legacy fields preserved for back-compat.
    assert body["app_env"] == "development"
    # conftest sets every required secret to a test value.
    assert body["missing_secrets"] == []
    assert isinstance(body["ssi_base_url"], str)
    # New nested sections.
    for key in ("provider", "cache", "supabase", "duckdb", "poller", "data_quality"):
        assert key in body, f"missing section: {key}"
    assert body["provider"]["name"] in {"mock", "ssi"}
    assert "stale_quote_count" in body["data_quality"]

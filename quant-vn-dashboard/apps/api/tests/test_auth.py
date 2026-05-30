"""JWT verification + /auth/me behaviour."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.conftest import make_jwt


def test_missing_bearer_returns_401(client: TestClient) -> None:
    r = client.get("/auth/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Missing bearer token."


def test_invalid_token_returns_401(client: TestClient) -> None:
    r = client.get("/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
    assert "Invalid token" in r.json()["detail"]


def test_expired_token_returns_401(client: TestClient) -> None:
    token = make_jwt(str(uuid.uuid4()), expired=True)
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_wrong_signature_returns_401(client: TestClient) -> None:
    # Sign with a different secret so verification fails.
    from jose import jwt as jose_jwt

    bad = jose_jwt.encode(
        {"sub": str(uuid.uuid4()), "aud": "authenticated"},
        "wrong-secret",
        algorithm="HS256",
    )
    r = client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


def test_valid_token_returns_user_claims(client: TestClient, auth_headers) -> None:
    headers, uid = auth_headers(email="alice@example.com")
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == uid
    assert body["email"] == "alice@example.com"
    assert body["role"] == "authenticated"

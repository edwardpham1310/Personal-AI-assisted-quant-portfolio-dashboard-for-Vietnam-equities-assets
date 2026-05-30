"""User settings CRUD."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_settings_requires_auth(client: TestClient) -> None:
    assert client.get("/settings").status_code == 401
    assert client.put("/settings", json={}).status_code == 401


def test_get_settings_creates_defaults_on_first_read(
    client: TestClient, auth_headers
) -> None:
    headers, uid = auth_headers()
    r = client.get("/settings", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == uid
    assert body["default_broker"] == "SSI"
    assert body["risk_profile"] == "moderate"
    assert body["theme"] == "dark"


def test_update_settings_round_trip(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    client.get("/settings", headers=headers)  # ensure row exists

    r = client.put(
        "/settings",
        headers=headers,
        json={"risk_profile": "aggressive", "theme": "light"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["risk_profile"] == "aggressive"
    assert body["theme"] == "light"
    # Unchanged fields preserved
    assert body["default_broker"] == "SSI"


def test_invalid_enum_rejected(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.put("/settings", headers=headers, json={"theme": "neon"})
    assert r.status_code == 422

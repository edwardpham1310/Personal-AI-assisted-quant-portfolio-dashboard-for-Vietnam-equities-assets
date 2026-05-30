"""Cross-user isolation tests.

The fake ``SupabaseDB`` enforces ownership the same way RLS does in
production: a user can only see / modify rows linked to their ``auth.uid()``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_user_b_cannot_see_user_a_watchlists(client: TestClient, auth_headers) -> None:
    h_a, _ = auth_headers(email="alice@example.com")
    h_b, _ = auth_headers(email="bob@example.com")

    client.post("/watchlists", headers=h_a, json={"name": "Alice list"})

    r = client.get("/watchlists", headers=h_b)
    assert r.status_code == 200
    assert r.json() == []


def test_user_b_cannot_add_to_user_a_watchlist(client: TestClient, auth_headers) -> None:
    h_a, _ = auth_headers()
    h_b, _ = auth_headers()

    wl = client.post("/watchlists", headers=h_a, json={"name": "Alpha"}).json()

    r = client.post(
        f"/watchlists/{wl['id']}/items", headers=h_b, json={"symbol": "FPT"}
    )
    # Either 404 ("not found" from this user's perspective) or 403 (RLS).
    assert r.status_code in (403, 404)


def test_user_b_cannot_see_user_a_portfolio(client: TestClient, auth_headers) -> None:
    h_a, _ = auth_headers()
    h_b, _ = auth_headers()

    acc = client.post(
        "/portfolio/manual/accounts", headers=h_a, json={"name": "Alice acc"}
    ).json()
    client.post(
        "/portfolio/manual/positions",
        headers=h_a,
        json={
            "account_id": acc["id"],
            "symbol": "FPT",
            "quantity": 100,
            "avg_cost": 80000.0,
        },
    )

    snap = client.get("/portfolio/manual", headers=h_b)
    assert snap.status_code == 200
    assert snap.json() == {"accounts": []}


def test_user_b_cannot_update_user_a_position(client: TestClient, auth_headers) -> None:
    h_a, _ = auth_headers()
    h_b, _ = auth_headers()

    acc = client.post(
        "/portfolio/manual/accounts", headers=h_a, json={"name": "A"}
    ).json()
    pos = client.post(
        "/portfolio/manual/positions",
        headers=h_a,
        json={
            "account_id": acc["id"],
            "symbol": "FPT",
            "quantity": 100,
            "avg_cost": 80000.0,
        },
    ).json()

    r = client.put(
        f"/portfolio/manual/positions/{pos['id']}",
        headers=h_b,
        json={"quantity": 9999},
    )
    assert r.status_code == 404  # invisible to user B

    # Confirm A's data is unchanged.
    snap = client.get("/portfolio/manual", headers=h_a).json()
    assert snap["accounts"][0]["positions"][0]["quantity"] == 100


def test_each_user_gets_own_settings_row(client: TestClient, auth_headers) -> None:
    h_a, uid_a = auth_headers()
    h_b, uid_b = auth_headers()

    a = client.get("/settings", headers=h_a).json()
    b = client.get("/settings", headers=h_b).json()
    assert a["user_id"] == uid_a
    assert b["user_id"] == uid_b
    assert a["id"] != b["id"]

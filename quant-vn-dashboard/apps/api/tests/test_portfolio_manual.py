"""Manual portfolio CRUD."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_manual_portfolio_requires_auth(client: TestClient) -> None:
    assert client.get("/portfolio/manual").status_code == 401


def test_create_account_and_position(client: TestClient, auth_headers) -> None:
    headers, uid = auth_headers()

    acc = client.post(
        "/portfolio/manual/accounts",
        headers=headers,
        json={"name": "Main"},
    )
    assert acc.status_code == 201
    account = acc.json()
    assert account["user_id"] == uid
    assert account["broker"] == "SSI"
    assert account["currency"] == "VND"

    pos = client.post(
        "/portfolio/manual/positions",
        headers=headers,
        json={
            "account_id": account["id"],
            "symbol": "vcb",
            "quantity": 1000,
            "avg_cost": 87500.0,
            "strategy_tag": "long-banking",
        },
    )
    assert pos.status_code == 201
    position = pos.json()
    assert position["symbol"] == "VCB"
    assert position["quantity"] == 1000

    snap = client.get("/portfolio/manual", headers=headers)
    assert snap.status_code == 200
    body = snap.json()
    assert len(body["accounts"]) == 1
    assert len(body["accounts"][0]["positions"]) == 1


def test_update_position(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account = client.post(
        "/portfolio/manual/accounts", headers=headers, json={"name": "A"}
    ).json()
    pos = client.post(
        "/portfolio/manual/positions",
        headers=headers,
        json={
            "account_id": account["id"],
            "symbol": "HPG",
            "quantity": 100,
            "avg_cost": 25000.0,
        },
    ).json()

    r = client.put(
        f"/portfolio/manual/positions/{pos['id']}",
        headers=headers,
        json={"quantity": 200, "avg_cost": 26500.0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["quantity"] == 200
    assert body["avg_cost"] == 26500.0


def test_delete_position(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account = client.post(
        "/portfolio/manual/accounts", headers=headers, json={"name": "A"}
    ).json()
    pos = client.post(
        "/portfolio/manual/positions",
        headers=headers,
        json={
            "account_id": account["id"],
            "symbol": "HPG",
            "quantity": 100,
            "avg_cost": 25000.0,
        },
    ).json()

    r = client.delete(f"/portfolio/manual/positions/{pos['id']}", headers=headers)
    assert r.status_code == 204

    snap = client.get("/portfolio/manual", headers=headers).json()
    assert snap["accounts"][0]["positions"] == []


def test_invalid_position_payload_rejected(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    account = client.post(
        "/portfolio/manual/accounts", headers=headers, json={"name": "A"}
    ).json()
    r = client.post(
        "/portfolio/manual/positions",
        headers=headers,
        json={
            "account_id": account["id"],
            "symbol": "HPG",
            "quantity": 0,  # invalid: must be > 0
            "avg_cost": 25000.0,
        },
    )
    assert r.status_code == 422


def test_manual_portfolio_scoped_per_account(client: TestClient, auth_headers) -> None:
    """User A's snapshot must contain only User A's positions (explicit
    account_id scoping in addition to RLS)."""
    headers_a, _ = auth_headers()
    headers_b, _ = auth_headers()  # second distinct user

    acc_a = client.post(
        "/portfolio/manual/accounts", headers=headers_a, json={"name": "A"}
    ).json()
    acc_b = client.post(
        "/portfolio/manual/accounts", headers=headers_b, json={"name": "B"}
    ).json()
    client.post(
        "/portfolio/manual/positions",
        headers=headers_a,
        json={"account_id": acc_a["id"], "symbol": "VCB", "quantity": 100, "avg_cost": 80000.0},
    )
    client.post(
        "/portfolio/manual/positions",
        headers=headers_b,
        json={"account_id": acc_b["id"], "symbol": "HPG", "quantity": 200, "avg_cost": 25000.0},
    )

    snap = client.get("/portfolio/manual", headers=headers_a).json()
    assert len(snap["accounts"]) == 1
    assert snap["accounts"][0]["id"] == acc_a["id"]
    symbols = [p["symbol"] for p in snap["accounts"][0]["positions"]]
    assert symbols == ["VCB"]  # User B's HPG must NOT leak in

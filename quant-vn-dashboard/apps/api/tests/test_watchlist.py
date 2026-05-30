"""Watchlist CRUD."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_watchlists_require_auth(client: TestClient) -> None:
    assert client.get("/watchlists").status_code == 401
    assert client.post("/watchlists", json={"name": "x"}).status_code == 401


def test_create_and_list_watchlist(client: TestClient, auth_headers) -> None:
    headers, uid = auth_headers()

    create = client.post("/watchlists", headers=headers, json={"name": "Tech"})
    assert create.status_code == 201
    created = create.json()
    assert created["name"] == "Tech"
    assert created["user_id"] == uid

    listed = client.get("/watchlists", headers=headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]
    assert rows[0]["items"] == []


def test_add_and_remove_items(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "VN30"}).json()

    add = client.post(
        f"/watchlists/{wl['id']}/items",
        headers=headers,
        json={"symbol": "fpt", "exchange": "HOSE"},
    )
    assert add.status_code == 201
    item = add.json()
    assert item["symbol"] == "FPT"  # backend uppercases

    listed = client.get("/watchlists", headers=headers).json()
    assert len(listed[0]["items"]) == 1

    rm = client.delete(
        f"/watchlists/{wl['id']}/items/{item['id']}", headers=headers
    )
    assert rm.status_code == 204

    listed = client.get("/watchlists", headers=headers).json()
    assert listed[0]["items"] == []


def test_remove_unknown_item_returns_404(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "X"}).json()
    r = client.delete(
        f"/watchlists/{wl['id']}/items/00000000-0000-0000-0000-000000000000",
        headers=headers,
    )
    assert r.status_code == 404

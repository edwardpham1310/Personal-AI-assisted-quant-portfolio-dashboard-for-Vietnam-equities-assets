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


# ── Feature 3: get-one / patch / delete / symbol-based add+remove ────────────


def test_get_one_watchlist_with_items(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "Banks"}).json()
    client.post(f"/watchlists/{wl['id']}/symbols", headers=headers, json={"symbol": "VCB"})
    r = client.get(f"/watchlists/{wl['id']}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == wl["id"]
    assert [i["symbol"] for i in body["items"]] == ["VCB"]


def test_get_one_watchlist_not_owned_404(client: TestClient, auth_headers) -> None:
    headers_a, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers_a, json={"name": "A"}).json()
    headers_b, _ = auth_headers()
    assert client.get(f"/watchlists/{wl['id']}", headers=headers_b).status_code == 404


def test_patch_watchlist_renames(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "Old"}).json()
    r = client.patch(f"/watchlists/{wl['id']}", headers=headers, json={"name": "New"})
    assert r.status_code == 200
    assert r.json()["name"] == "New"


def test_patch_not_owned_404(client: TestClient, auth_headers) -> None:
    headers_a, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers_a, json={"name": "A"}).json()
    headers_b, _ = auth_headers()
    r = client.patch(f"/watchlists/{wl['id']}", headers=headers_b, json={"name": "Hax"})
    assert r.status_code == 404


def test_delete_watchlist_removes_it_and_items(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "Temp"}).json()
    client.post(f"/watchlists/{wl['id']}/symbols", headers=headers, json={"symbol": "FPT"})
    r = client.delete(f"/watchlists/{wl['id']}", headers=headers)
    assert r.status_code == 204
    assert client.get("/watchlists", headers=headers).json() == []


def test_add_symbol_uppercases_and_rejects_duplicate(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "W"}).json()
    a = client.post(f"/watchlists/{wl['id']}/symbols", headers=headers, json={"symbol": "fpt"})
    assert a.status_code == 201 and a.json()["symbol"] == "FPT"
    dup = client.post(f"/watchlists/{wl['id']}/symbols", headers=headers, json={"symbol": "FPT"})
    assert dup.status_code == 409


def test_add_symbol_to_not_owned_404(client: TestClient, auth_headers) -> None:
    headers_a, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers_a, json={"name": "A"}).json()
    headers_b, _ = auth_headers()
    r = client.post(f"/watchlists/{wl['id']}/symbols", headers=headers_b, json={"symbol": "FPT"})
    assert r.status_code == 404


def test_remove_symbol_by_symbol(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "W"}).json()
    client.post(f"/watchlists/{wl['id']}/symbols", headers=headers, json={"symbol": "FPT"})
    rm = client.delete(f"/watchlists/{wl['id']}/symbols/fpt", headers=headers)
    assert rm.status_code == 204
    assert client.get(f"/watchlists/{wl['id']}", headers=headers).json()["items"] == []
    assert client.delete(f"/watchlists/{wl['id']}/symbols/FPT", headers=headers).status_code == 404


def test_watchlist_picks_shape_and_auth(client: TestClient, auth_headers) -> None:
    assert client.get("/recommendations/watchlist/x/picks").status_code == 401
    headers, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers, json={"name": "W"}).json()
    client.post(f"/watchlists/{wl['id']}/symbols", headers=headers, json={"symbol": "FPT"})
    r = client.get(f"/recommendations/watchlist/{wl['id']}/picks", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["coverage"] == "watchlist"
    for p in body["picks"]:
        assert p["strength"] in {"Weak", "Neutral", "Strong"}
        assert p["signal"] in {
            "Watch", "Actionable", "Accumulate", "Wait", "Avoid", "Risky", "Take Profit"
        }


def test_watchlist_picks_not_owned_404(client: TestClient, auth_headers) -> None:
    headers_a, _ = auth_headers()
    wl = client.post("/watchlists", headers=headers_a, json={"name": "A"}).json()
    headers_b, _ = auth_headers()
    assert (
        client.get(f"/recommendations/watchlist/{wl['id']}/picks", headers=headers_b).status_code
        == 404
    )

"""Tests for the System Status + Data Quality routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from schemas.market import Quote
from services import market_cache
from services.data_quality import _redact

# ── /system/health ──────────────────────────────────────────────────────────


def test_system_health_is_public(client: TestClient) -> None:
    r = client.get("/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"ok", "degraded", "down"}
    assert body["env"] == "development"
    assert body["version"] == "0.1.0"
    assert body["cache_reachable"] is True
    assert body["settings_loaded"] is True
    assert "checked_at" in body


def test_system_health_never_leaks_secrets(client: TestClient) -> None:
    r = client.get("/system/health")
    body = r.text
    # Conftest seeds these placeholder secret values — none should appear
    # in the public liveness payload.
    assert "test-jwt-secret-do-not-use-in-prod" not in body
    assert "test-consumer-secret" not in body
    assert "test-anon-key" not in body


# ── /system/status ──────────────────────────────────────────────────────────


def test_system_status_requires_auth(client: TestClient) -> None:
    assert client.get("/system/status").status_code == 401


def test_system_status_returns_full_snapshot(
    client: TestClient, auth_headers
) -> None:
    headers, _ = auth_headers()
    r = client.get("/system/status", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()

    # Backwards-compatible fields.
    assert body["app_env"] == "development"
    # missing_secrets is a list; not all are configured under test env
    # (e.g. database_url) — that's fine, we just want the field to exist.
    assert isinstance(body["missing_secrets"], list)
    assert isinstance(body["ssi_base_url"], str)
    assert body["redis_configured"] is False

    # New structured fields.
    for key in ("provider", "cache", "supabase", "duckdb", "poller", "data_quality"):
        assert key in body, f"missing top-level key: {key}"

    assert body["provider"]["mock"] is True
    assert body["provider"]["name"] == "mock"
    assert body["cache"]["name"] == "memory"
    assert body["cache"]["healthy"] is True
    assert body["supabase"]["configured"] is True
    # url_host parsed from "http://localhost:54321"
    assert body["supabase"]["url_host"] == "localhost"
    # Full URL must not leak.
    assert "http://localhost:54321" not in r.text
    assert body["poller"]["enabled"] is False
    assert body["poller"]["running"] is False


# ── /system/providers ──────────────────────────────────────────────────────


def test_system_providers_requires_auth(client: TestClient) -> None:
    assert client.get("/system/providers").status_code == 401


def test_system_providers_returns_list(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/system/providers", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1
    assert rows[0]["name"] == "mock"
    assert rows[0]["ready"] is True


# ── /system/cache ──────────────────────────────────────────────────────────


def test_system_cache_requires_auth(client: TestClient) -> None:
    assert client.get("/system/cache").status_code == 401


def test_system_cache_returns_health(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/system/cache", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "memory"
    assert body["healthy"] is True
    assert body["configured"] is False


# ── /system/data-quality ───────────────────────────────────────────────────


def test_system_data_quality_requires_auth(client: TestClient) -> None:
    assert client.get("/system/data-quality").status_code == 401


def test_system_data_quality_empty_cache(client: TestClient, auth_headers) -> None:
    headers, _ = auth_headers()
    r = client.get("/system/data-quality", headers=headers)
    assert r.status_code == 200
    body = r.json()
    expected_keys = {
        "timestamp",
        "stale_quote_count",
        "total_tracked_symbols",
        "symbols_without_quote",
        "cache_misses",
        "provider_errors",
        "last_successful_sync",
        "notes",
    }
    assert expected_keys.issubset(body.keys())
    # Core symbols are tracked even when no quotes are cached.
    assert body["total_tracked_symbols"] >= 1
    assert isinstance(body["symbols_without_quote"], list)


def test_system_data_quality_flags_stale_quote(
    client: TestClient, auth_headers, fake_cache
) -> None:
    # Seed a stale quote on a core symbol.
    old_ts = datetime.now(UTC) - timedelta(minutes=10)
    asyncio.run(
        market_cache.set_quote(
            fake_cache,
            Quote(
                symbol="FPT",
                exchange="HOSE",
                price=86_500.0,
                ts=old_ts,
                stale=False,
                source="mock",
            ),
            ttl_seconds=3600,
        )
    )

    headers, _ = auth_headers()
    r = client.get("/system/data-quality", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["stale_quote_count"] >= 1
    # Other core symbols still have no cached quote.
    assert "MWG" in body["symbols_without_quote"]
    assert any("stale" in note for note in body["notes"])


# ── Redaction unit test ───────────────────────────────────────────────────


def test_redact_strips_bearer_token() -> None:
    out = _redact("Authorization: Bearer xxx-secret-token-abc.def-ghi")
    assert "xxx-secret-token" not in out
    assert "[redacted]" in out


def test_redact_strips_jwt_blob() -> None:
    out = _redact("token expired: eyJhbGciOiJIUzI1NiJ9.payload.signature")
    assert "eyJhbGciOiJIUzI1NiJ9" not in out
    assert "[redacted]" in out


def test_redact_strips_kv_secret() -> None:
    out = _redact("connect failed api_key=sk-deadbeef-123456 host=db.local")
    assert "sk-deadbeef" not in out
    assert "[redacted]" in out
    # Non-secret parts of the message survive.
    assert "host=db.local" in out


def test_redact_handles_empty() -> None:
    assert _redact(None) == ""
    assert _redact("") == ""


def test_no_hardcoded_secrets_in_production_source() -> None:
    """Repo-wide regression: production source (apps/api/src + apps/web/src)
    must contain no real-looking secret material.

    The system module owns the redaction story for runtime errors. This
    test owns the static guarantee that secrets never get *committed* to
    source in the first place.

    What is checked:
      * Bearer tokens like ``Bearer eyJ...`` or ``Bearer sk-...``
      * JWT-shape blobs longer than 20 chars (``eyJ`` prefix)
      * Supabase new-format keys (``sb_secret_`` / ``sb_publishable_``)
      * OpenAI-shape keys (``sk-…`` >= 20 chars)
      * The specific token fragments pasted into this session's chat
        (these became the operator's known-leaked credentials that must
        not appear in any tracked file)

    Test files and ``no-direct-ssi.test.ts`` (whose entire purpose is to
    REGEX against forbidden patterns) are excluded — they reference
    forbidden literals on purpose.
    """
    import pathlib
    import re

    api_src = pathlib.Path(__file__).resolve().parents[1] / "src"
    web_src = (
        pathlib.Path(__file__).resolve().parents[3]
        / "apps"
        / "web"
        / "src"
    )

    # Patterns. Each is matched case-sensitive (these are secret shapes).
    forbidden = [
        # New Supabase key prefixes (Phase 2 of this dashboard's auth).
        r"sb_secret_[A-Za-z0-9_]{20,}",
        r"sb_publishable_[A-Za-z0-9_]{20,}",
        # JWT-shaped tokens past 50 chars are essentially certainly real.
        r"eyJ[A-Za-z0-9._\-]{50,}",
        # Bearer literals with a real-looking token body.
        r"Bearer\s+[A-Za-z0-9._\-]{20,}",
        # OpenAI-style keys.
        r"\bsk-[A-Za-z0-9]{20,}",
        # Redacted examples of fragments pasted during setup. Keep this list
        # synthetic; never commit real secret values here.
        r"ad4d10b7653d45998bd2d24dfbacfd32",
        r"80c97869b84840919c5fd9237812529e",
        r"REDACTED_SUPABASE_DB_PASSWORD",
        r"NWWn36ZGMohELG",
    ]
    pattern = re.compile("|".join(forbidden))

    # Files to skip (legitimate references).
    skip_basenames = {
        "no-direct-ssi.test.ts",          # guard test — must reference patterns
    }

    def _walk(root: pathlib.Path) -> list[pathlib.Path]:
        out: list[pathlib.Path] = []
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            # Skip test files — fixtures may contain mock JWTs etc.
            if "/tests/" in str(p) or p.name.endswith((".test.ts", ".test.tsx")):
                continue
            if p.name in skip_basenames:
                continue
            # Only source extensions.
            if p.suffix not in {".py", ".ts", ".tsx", ".js", ".sql", ".md"}:
                continue
            out.append(p)
        return out

    offenders: list[str] = []
    for path in _walk(api_src) + _walk(web_src):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        match = pattern.search(text)
        if match:
            short = match.group(0)[:20] + "…"
            offenders.append(f"{path.name}: {short!r}")

    assert offenders == [], (
        f"Hardcoded secret pattern in tracked source: {offenders}. "
        "Move the value to .env (gitignored) and use Settings to read it."
    )

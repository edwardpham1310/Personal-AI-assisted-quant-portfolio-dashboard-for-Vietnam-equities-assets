"""Data-quality + system-status aggregation service.

This module is the single place that knows how to assemble the operator
snapshot used by ``/system/*``. It never raises out to the route layer for
non-fatal upstream errors — instead it returns a structured payload with
``healthy=False`` and a redacted error string.

Redaction is paramount: every error message goes through ``_redact`` before
being attached to a response. We err on the side of dropping useful detail
rather than leaking a secret into the dashboard.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from core.config import Settings
from providers.market_data.base import MarketDataProvider
from services import market_cache
from services.cache import Cache
from workers.market_poller import MarketPoller

logger = logging.getLogger(__name__)


# ── Redaction ───────────────────────────────────────────────────────────────

# Patterns that frequently encode secrets in upstream error messages.
_REDACT_TOKENS = re.compile(
    r"(?ix)"
    r"(?:bearer\s+[A-Za-z0-9._\-]+)"  # Authorization: Bearer xxxxx
    r"|(?:eyJ[A-Za-z0-9._\-]{10,})"  # JWT-shaped blobs
    r"|(?:sk-[A-Za-z0-9._\-]{6,})"  # API-key-shaped blobs
)

# Key=value pairs where the key hints at a secret. We replace the value only.
_REDACT_KV = re.compile(
    r"(?i)\b(api[_-]?key|secret|password|token|authorization|jwt|consumer[_-]?secret)\b\s*[:=]\s*\S+"
)


def _redact(msg: str | None) -> str:
    """Strip secret-shaped substrings from a string before surfacing it."""
    if not msg:
        return ""
    redacted = _REDACT_TOKENS.sub("[redacted]", msg)
    redacted = _REDACT_KV.sub(
        lambda m: f"{m.group(1)}=[redacted]", redacted
    )
    return redacted


# ── Cache-derived metrics ───────────────────────────────────────────────────


async def count_stale_quotes(
    cache: Cache, symbols: list[str], stale_threshold_s: int
) -> int:
    """Number of cached quotes whose ts is older than the threshold."""
    if not symbols:
        return 0
    quotes = await market_cache.get_quotes(cache, symbols)
    now = datetime.now(UTC)
    threshold = timedelta(seconds=max(1, stale_threshold_s))
    stale = 0
    for q in quotes:
        if q is None:
            continue
        if (now - q.ts) > threshold:
            stale += 1
    return stale


async def find_symbols_without_quote(cache: Cache, symbols: list[str]) -> list[str]:
    """Return symbols that have no cached quote at all (cache miss)."""
    if not symbols:
        return []
    quotes = await market_cache.get_quotes(cache, symbols)
    missing: list[str] = []
    for sym, q in zip(symbols, quotes, strict=False):
        if q is None:
            missing.append(sym.upper())
    return sorted(set(missing))


async def list_stale_quote_details(
    cache: Cache, symbols: list[str], stale_threshold_s: int
) -> list[dict[str, Any]]:
    """Detailed per-symbol stale-quote rows for the UI table."""
    if not symbols:
        return []
    quotes = await market_cache.get_quotes(cache, symbols)
    now = datetime.now(UTC)
    threshold = timedelta(seconds=max(1, stale_threshold_s))
    rows: list[dict[str, Any]] = []
    for sym, q in zip(symbols, quotes, strict=False):
        if q is None:
            continue
        age_s = (now - q.ts).total_seconds()
        rows.append(
            {
                "symbol": sym.upper(),
                "ts": q.ts.isoformat(),
                "age_seconds": int(age_s),
                "stale": age_s > threshold.total_seconds(),
                "source": q.source,
            }
        )
    return rows


# ── Per-component summaries ─────────────────────────────────────────────────


async def summarize_provider(provider: MarketDataProvider) -> dict[str, Any]:
    """Wrap ``provider.status()`` so a provider error never reaches the route."""
    try:
        status = await provider.status()
        return {
            "name": status.name,
            "ready": status.ready,
            "mock": status.mock,
            "token_cached": status.token_cached,
            "last_call_ts": status.last_call_ts,
            "note": status.note,
            "error": None,
        }
    except Exception as exc:
        # Only the exception type name leaves this process.
        logger.warning("data_quality.provider_status_failed err=%s", type(exc).__name__)
        return {
            "name": getattr(provider, "name", "unknown"),
            "ready": False,
            "mock": False,
            "token_cached": False,
            "last_call_ts": None,
            "note": "status_unavailable",
            "error": _redact(type(exc).__name__),
        }


async def summarize_cache(cache: Cache, settings: Settings) -> dict[str, Any]:
    """Cache name + reachability + last-poll heartbeat."""
    name = getattr(cache, "name", "unknown")
    configured = bool(settings.redis_url or settings.upstash_redis_rest_url)
    healthy = False
    err: str | None = None

    # Prefer a real ping if the backend supports it.
    try:
        if hasattr(cache, "ping"):
            healthy = bool(await cache.ping())
        else:
            probe = f"system:probe:{uuid.uuid4().hex}"
            await cache.set(probe, "1", ttl_seconds=5)
            got = await cache.get(probe)
            healthy = got == "1"
            await cache.delete(probe)
    except Exception as exc:
        healthy = False
        err = _redact(type(exc).__name__)

    last_poll: dict[str, Any] | None = None
    try:
        last_poll = await market_cache.get_last_poll(cache)
    except Exception as exc:
        err = err or _redact(type(exc).__name__)

    last_poll_ts: datetime | None = None
    last_poll_ok: bool | None = None
    last_poll_err: str | None = None
    if isinstance(last_poll, dict):
        ts = last_poll.get("ts")
        if isinstance(ts, str):
            try:
                last_poll_ts = datetime.fromisoformat(ts)
            except ValueError:
                last_poll_ts = None
        last_poll_ok = last_poll.get("ok")
        last_poll_err = _redact(last_poll.get("error")) or None

    return {
        "name": name,
        "configured": configured,
        "healthy": healthy,
        "last_poll_ts": last_poll_ts,
        "last_poll_ok": last_poll_ok,
        "last_poll_error": last_poll_err,
        "error": err,
    }


def summarize_supabase(settings: Settings) -> dict[str, Any]:
    """Configured-flag + URL host, never the full URL.

    We do NOT call out to Supabase here — that would couple every status
    request to the upstream service's availability and add latency.
    """
    has_url = bool(settings.supabase_url)
    has_anon = bool(settings.supabase_anon_key)
    has_jwt = bool(settings.supabase_jwt_secret)

    url_host: str | None = None
    if has_url:
        try:
            parsed = urlparse(settings.supabase_url)
            url_host = parsed.hostname
        except Exception:
            url_host = None

    return {
        "configured": has_url and has_anon and has_jwt,
        "url_host": url_host,
    }


def summarize_duckdb(settings: Settings) -> dict[str, Any]:
    """DuckDB warehouse health. Crash-free even when the path is missing."""
    path = getattr(settings, "duckdb_path", None)
    if not path:
        return {"configured": False, "path": None, "exists": False, "size_bytes": None}

    exists = False
    size_bytes: int | None = None
    try:
        exists = os.path.exists(path)
        if exists:
            size_bytes = os.path.getsize(path)
    except OSError:
        exists = False
        size_bytes = None

    return {
        "configured": True,
        "path": path,
        "exists": exists,
        "size_bytes": size_bytes,
    }


async def summarize_poller(poller: MarketPoller | None) -> dict[str, Any]:
    """Poller health snapshot."""
    if poller is None:
        return {"enabled": False, "running": False, "active_symbols_count": 0}
    try:
        active = await poller.active_symbols()
    except Exception:
        active = []
    return {
        "enabled": True,
        "running": bool(getattr(poller, "is_running", False)),
        "active_symbols_count": len(active),
    }


# ── Top-level snapshot builder ──────────────────────────────────────────────


async def build_data_quality_snapshot(
    cache: Cache, poller: MarketPoller | None, settings: Settings
) -> dict[str, Any]:
    """Assemble the ``DataQualitySnapshot`` payload."""
    tracked_set = set(settings.market_core_symbols or [])
    if poller is not None:
        try:
            tracked_set.update(await poller.active_symbols())
        except Exception:
            pass
    tracked = sorted(tracked_set)

    stale_count = await count_stale_quotes(
        cache, tracked, settings.ssi_quote_stale_seconds
    )
    missing = await find_symbols_without_quote(cache, tracked)
    stale_rows = await list_stale_quote_details(
        cache, tracked, settings.ssi_quote_stale_seconds
    )

    last_successful_sync: datetime | None = None
    notes: list[str] = []
    last_poll = None
    try:
        last_poll = await market_cache.get_last_poll(cache)
    except Exception as exc:
        notes.append(f"last_poll_unavailable: {_redact(type(exc).__name__)}")

    if isinstance(last_poll, dict):
        ts = last_poll.get("ts")
        if isinstance(ts, str):
            try:
                ts_parsed = datetime.fromisoformat(ts)
                if last_poll.get("ok"):
                    last_successful_sync = ts_parsed
            except ValueError:
                pass
        if last_poll.get("error"):
            notes.append(f"poller_error: {_redact(last_poll.get('error'))}")

    if not tracked:
        notes.append("no_tracked_symbols")
    if missing:
        notes.append(f"{len(missing)} symbol(s) without a cached quote")
    if stale_count:
        notes.append(f"{stale_count} stale quote(s) past {settings.ssi_quote_stale_seconds}s")

    return {
        "timestamp": datetime.now(UTC),
        "stale_quote_count": stale_count,
        "total_tracked_symbols": len(tracked),
        "symbols_without_quote": missing,
        "stale_quote_rows": stale_rows,
        "cache_misses": len(missing) if tracked else None,
        "provider_errors": 1 if (isinstance(last_poll, dict) and last_poll.get("error")) else 0,
        "last_successful_sync": last_successful_sync,
        "notes": notes,
    }

"""Thin Supabase PostgREST client.

All calls go through the user's JWT so Row-Level Security policies do the
real authorization work in Postgres. The API merely forwards intent.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class SupabaseDB(Protocol):
    """Interface every implementation (real + fake) honours."""

    async def select(
        self,
        table: str,
        *,
        where: dict[str, Any] | None = None,
        user_jwt: str,
    ) -> list[dict[str, Any]]: ...

    async def insert(
        self,
        table: str,
        row: dict[str, Any],
        *,
        user_jwt: str,
    ) -> dict[str, Any]: ...

    async def update(
        self,
        table: str,
        patch: dict[str, Any],
        *,
        where: dict[str, Any],
        user_jwt: str,
    ) -> list[dict[str, Any]]: ...

    async def delete(
        self,
        table: str,
        *,
        where: dict[str, Any],
        user_jwt: str,
    ) -> int: ...


class PostgrestError(Exception):
    """Raised when PostgREST returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"PostgREST {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


# ── Shared HTTP client ───────────────────────────────────────────────────────
#
# One process-wide httpx.AsyncClient reused across every PostgREST call so we
# pool connections / reuse TLS instead of paying a fresh handshake per DB call
# (a single recommendation scan makes 3-4 selects + one insert per symbol).
# The client is transport-only — all auth/headers are per-call — so a single
# instance safely serves all users. Created lazily on first use (inside a
# running event loop) and closed by the FastAPI lifespan on shutdown.

_shared_client: httpx.AsyncClient | None = None
_DEFAULT_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=100)


def _get_shared_client(timeout: float) -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=timeout, limits=_DEFAULT_LIMITS)
    return _shared_client


async def aclose_shared_client() -> None:
    """Close the shared PostgREST client. Call from the app lifespan shutdown."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
    _shared_client = None


class PostgrestDB:
    """httpx-based implementation that talks to Supabase PostgREST.

    The anon key goes in the ``apikey`` header (required by PostgREST); the
    user's JWT goes in ``Authorization``. RLS evaluates against ``auth.uid()``
    derived from the JWT.
    """

    def __init__(self, *, base_url: str, anon_key: str, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/") + "/rest/v1"
        self._anon = anon_key
        self._timeout = timeout

    def _headers(self, jwt: str, *, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self._anon,
            "Authorization": f"Bearer {jwt}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    @staticmethod
    def _where_params(where: dict[str, Any] | None) -> dict[str, str]:
        if not where:
            return {}
        # PostgREST filter syntax: ?col=eq.value
        return {key: f"eq.{value}" for key, value in where.items()}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        params: dict[str, str] | None = None,
        json: Any = None,
    ) -> Any:
        client = _get_shared_client(self._timeout)
        response = await client.request(
            method, f"{self._base}/{path}", headers=headers, params=params, json=json
        )
        if response.status_code >= 400:
            raise PostgrestError(response.status_code, response.text)
        if not response.content:
            return None
        return response.json()

    async def select(self, table, *, where=None, user_jwt):
        data = await self._request(
            "GET", table, headers=self._headers(user_jwt), params=self._where_params(where)
        )
        return data or []

    async def insert(self, table, row, *, user_jwt):
        data = await self._request(
            "POST",
            table,
            headers=self._headers(user_jwt, prefer="return=representation"),
            json=row,
        )
        if isinstance(data, list):
            if not data:
                raise PostgrestError(500, "PostgREST returned empty insert response")
            return data[0]
        return data

    async def update(self, table, patch, *, where, user_jwt):
        data = await self._request(
            "PATCH",
            table,
            headers=self._headers(user_jwt, prefer="return=representation"),
            params=self._where_params(where),
            json=patch,
        )
        return data or []

    async def delete(self, table, *, where, user_jwt):
        data = await self._request(
            "DELETE",
            table,
            headers=self._headers(user_jwt, prefer="return=representation"),
            params=self._where_params(where),
        )
        return len(data) if isinstance(data, list) else 0

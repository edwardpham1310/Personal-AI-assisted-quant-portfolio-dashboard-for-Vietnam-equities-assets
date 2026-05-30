"""In-memory ``SupabaseDB`` for tests.

Mimics Row-Level Security by:
    * extracting ``sub`` from the JWT (so tests sign tokens for a specific user)
    * enforcing ownership at read/write time
    * propagating parent-table ownership to child tables (watchlist_items,
      manual_positions)
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from typing import Any
from uuid import uuid4

from jose import jwt

from core.config import get_settings


_USER_OWNED_TABLES = {
    "user_settings",
    "watchlists",
    "manual_portfolio_accounts",
    "recommendation_snapshots",
    "security_audit_logs",
}


class FakeSupabaseDB:
    """Test-only in-memory replacement for ``PostgrestDB``."""

    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = defaultdict(list)

    # ── JWT-derived identity ────────────────────────────────────────────────
    def _extract_user_id(self, user_jwt: str) -> str:
        settings = get_settings()
        claims = jwt.decode(
            user_jwt,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return str(claims["sub"])

    # ── Fake RLS ────────────────────────────────────────────────────────────
    def _owned_by(self, table: str, row: dict[str, Any], user_id: str) -> bool:
        if table == "profiles":
            return row.get("id") == user_id
        if table in _USER_OWNED_TABLES:
            return row.get("user_id") == user_id
        if table == "watchlist_items":
            parent = self._find_by_id("watchlists", row.get("watchlist_id"))
            return parent is not None and parent.get("user_id") == user_id
        if table in {"manual_positions", "cash_balances", "trade_transactions"}:
            parent = self._find_by_id("manual_portfolio_accounts", row.get("account_id"))
            return parent is not None and parent.get("user_id") == user_id
        return False

    def _find_by_id(self, table: str, pk: Any) -> dict[str, Any] | None:
        if pk is None:
            return None
        return next((r for r in self._tables[table] if r.get("id") == pk), None)

    @staticmethod
    def _matches(row: dict[str, Any], where: dict[str, Any]) -> bool:
        return all(row.get(k) == v for k, v in where.items())

    @staticmethod
    def _now_iso() -> str:
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    # ── SupabaseDB protocol ─────────────────────────────────────────────────
    async def select(
        self,
        table: str,
        *,
        where: dict[str, Any] | None = None,
        user_jwt: str,
    ) -> list[dict[str, Any]]:
        user_id = self._extract_user_id(user_jwt)
        rows = [r for r in self._tables[table] if self._owned_by(table, r, user_id)]
        if where:
            rows = [r for r in rows if self._matches(r, where)]
        # Return shallow copies so callers can't mutate the fake's storage.
        return [dict(r) for r in rows]

    async def insert(
        self,
        table: str,
        row: dict[str, Any],
        *,
        user_jwt: str,
    ) -> dict[str, Any]:
        user_id = self._extract_user_id(user_jwt)
        now = self._now_iso()
        candidate = {
            "id": row.get("id") or str(uuid4()),
            "created_at": now,
            "updated_at": now,
            **row,
        }
        if not self._owned_by(table, candidate, user_id):
            raise PermissionError(
                f"RLS violation: user {user_id} cannot insert into {table}."
            )
        self._tables[table].append(candidate)
        return dict(candidate)

    async def update(
        self,
        table: str,
        patch: dict[str, Any],
        *,
        where: dict[str, Any],
        user_jwt: str,
    ) -> list[dict[str, Any]]:
        user_id = self._extract_user_id(user_jwt)
        updated: list[dict[str, Any]] = []
        for row in self._tables[table]:
            if not self._owned_by(table, row, user_id):
                continue
            if not self._matches(row, where):
                continue
            row.update(patch)
            row["updated_at"] = self._now_iso()
            updated.append(dict(row))
        return updated

    async def delete(
        self,
        table: str,
        *,
        where: dict[str, Any],
        user_jwt: str,
    ) -> int:
        user_id = self._extract_user_id(user_jwt)
        before = len(self._tables[table])
        self._tables[table] = [
            r
            for r in self._tables[table]
            if not (self._owned_by(table, r, user_id) and self._matches(r, where))
        ]
        return before - len(self._tables[table])

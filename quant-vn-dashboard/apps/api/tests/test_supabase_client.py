"""Shared PostgREST httpx client lifecycle (PR-A #1: connection pooling)."""

from __future__ import annotations

import pytest

from services import supabase_db


@pytest.mark.asyncio
async def test_shared_client_is_reused_then_reset() -> None:
    await supabase_db.aclose_shared_client()  # clean slate

    c1 = supabase_db._get_shared_client(10.0)
    c2 = supabase_db._get_shared_client(10.0)
    assert c1 is c2, "shared client must be reused across calls (pooled)"
    assert not c1.is_closed

    await supabase_db.aclose_shared_client()
    assert c1.is_closed

    c3 = supabase_db._get_shared_client(10.0)
    assert c3 is not c1, "a fresh client is created after close"
    await supabase_db.aclose_shared_client()

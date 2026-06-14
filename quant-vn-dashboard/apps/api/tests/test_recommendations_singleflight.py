"""PR-B #4: single-flight — concurrent identical scans compute + persist once."""

from __future__ import annotations

import asyncio

import pytest

from api.routes import recommendations as reco
from core.security import AuthContext
from providers.market_data.mock_provider import MockMarketDataProvider
from services.cache import InMemoryCache
from services.fakes import FakeSupabaseDB

from .conftest import make_jwt


def _user() -> AuthContext:
    uid = "11111111-1111-1111-1111-111111111111"
    token = make_jwt(uid)
    return AuthContext(user_id=uid, email="t@e.com", role="authenticated", raw_token=token, claims={})


@pytest.mark.asyncio
async def test_concurrent_identical_runs_persist_one_snapshot() -> None:
    user = _user()
    db = FakeSupabaseDB()
    cache = InMemoryCache()
    provider = MockMarketDataProvider()

    async def call():
        return await reco._run_one(
            symbol="FPT", profile="short_aggressive", horizon="SHORT_2W",
            provider=provider, cache=cache, db=db, user=user,
            portfolio_positions=None, total_equity=None, cash_row=None, persist=True,
        )

    # 6 concurrent identical calls, cold cache → single-flight must collapse them.
    results = await asyncio.gather(*[call() for _ in range(6)])

    assert all(r is not None and r.symbol == "FPT" for r in results)
    # Exactly one snapshot row written (not 6) — stampede + dup-row defeated.
    snaps = db._tables.get("recommendation_snapshots", [])
    assert len(snaps) == 1, f"expected 1 snapshot, got {len(snaps)}"
    # Registry cleaned up.
    assert reco._inflight == {}

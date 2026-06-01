"""Quant VN Dashboard API entrypoint.

Run with: ``uvicorn main:app --reload``
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import (
    assets,
    auth,
    auto_trade,
    health,
    market,
    paper_trading,
    portfolio,
    recommendations,
    scanner,
    settings as settings_routes,
    stream,
    system,
    trading,
    watchlist,
)
from core.config import get_settings
from core.deps import get_market_provider, set_cache, set_poller
from core.logging import configure_logging, get_logger
from services.cache import build_cache
from services.supabase_db import PostgrestError
from workers.market_poller import MarketPoller


logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(level=settings.log_level)
    missing = settings.warn_if_missing_secrets()
    logger.info(
        "api.startup env=%s host=%s port=%s missing_secrets=%s",
        settings.app_env,
        settings.api_host,
        settings.api_port,
        missing or "none",
    )

    # Hot cache (Redis or in-memory fallback).
    cache = build_cache(
        settings.redis_url,
        upstash_url=settings.upstash_redis_rest_url,
        upstash_token=settings.upstash_redis_rest_token,
    )
    set_cache(cache)

    # Background poller — optional, off by default so SSI isn't touched in dev.
    poller: MarketPoller | None = None
    if settings.enable_market_poller:
        provider = get_market_provider(settings)
        poller = MarketPoller(
            provider=provider,
            cache=cache,
            poll_interval=settings.market_poll_interval_seconds,
            full_market_interval=settings.full_market_poll_interval_seconds,
            quote_ttl=settings.quote_cache_ttl_seconds,
            index_ttl=settings.index_cache_ttl_seconds,
            core_symbols=settings.market_core_symbols,
            core_indices=settings.market_core_indices,
        )
        set_poller(poller)
        await poller.start()
    else:
        logger.info(
            "market_poller.disabled set ENABLE_MARKET_POLLER=true to enable"
        )

    yield

    if poller is not None:
        await poller.stop()
        set_poller(None)
    await cache.close()
    set_cache(None)
    logger.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Quant VN Dashboard API",
        version="0.1.0",
        description="Sole SSI gateway for the Quant VN Dashboard MVP.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(PostgrestError)
    async def _postgrest_error_handler(_: Request, exc: PostgrestError) -> JSONResponse:
        """Never leak PostgREST's verbose body (column names, constraint detail).

        PostgrestError.detail can carry column names or constraint detail
        which is upstream-implementation information we don't want clients
        to see. We log only the exception class name + status_code; we
        respond with a generic 502 and a stable, redacted message.
        """
        logger.warning(
            "supabase.postgrest_error type=%s status=%s",
            type(exc).__name__,
            exc.status_code,
        )
        # 401/403 from PostgREST means the user JWT was bad — surface that
        # accurately so the frontend can re-authenticate. Everything else
        # collapses to "upstream error".
        if exc.status_code in (401, 403):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": "Not authorized."},
            )
        return JSONResponse(
            status_code=502,
            content={"detail": "Upstream database error."},
        )

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(settings_routes.router, prefix="/settings", tags=["settings"])
    app.include_router(watchlist.router, prefix="/watchlists", tags=["watchlist"])
    app.include_router(market.router, prefix="/market", tags=["market"])
    app.include_router(stream.router, prefix="/stream", tags=["stream"])
    app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
    app.include_router(assets.router, prefix="/assets", tags=["assets"])
    app.include_router(
        recommendations.router, prefix="/recommendations", tags=["recommendations"]
    )
    app.include_router(scanner.router, prefix="/scanner", tags=["scanner"])
    app.include_router(system.router, prefix="/system", tags=["system"])
    app.include_router(trading.router, prefix="/trading", tags=["trading"])
    app.include_router(auto_trade.router, prefix="/auto-trade", tags=["auto-trade"])
    app.include_router(paper_trading.router, prefix="/paper", tags=["paper-trading"])

    return app


app = create_app()

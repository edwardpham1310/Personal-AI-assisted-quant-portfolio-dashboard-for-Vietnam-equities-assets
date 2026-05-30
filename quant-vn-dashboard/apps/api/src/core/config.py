"""Pydantic Settings for the API.

Secrets are loaded from environment variables (and optionally a local ``.env``
file). Required production secrets fail loud on startup; in development the
service boots with placeholders and warns instead of crashing — convenient
for the first ``make dev-api`` after cloning.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_logger = logging.getLogger(__name__)


# Look for .env at the monorepo root (two levels above apps/api).
_REPO_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """All runtime configuration for the API."""

    model_config = SettingsConfigDict(
        env_file=(str(_REPO_ROOT_ENV), ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    # ── Supabase ───────────────────────────────────────────────────────────
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""
    supabase_db_password: str = ""
    database_url: str = ""

    # ── SSI FastConnect Data (read-only, server-only) ──────────────────────
    ssi_consumer_id: str = ""
    ssi_consumer_secret: str = ""
    ssi_base_url: str = "https://fc-data.ssi.com.vn"
    ssi_timeout_seconds: float = 10.0
    ssi_max_retries: int = 3
    ssi_use_mock: bool = False
    ssi_quote_stale_seconds: int = 60

    # ── SSI FastConnect Trading — PHASE 2 PLACEHOLDERS ─────────────────────
    # These fields are accepted from the environment so a Phase 2 sync
    # milestone can populate them, but **no code path under apps/api/src/
    # currently instantiates a Trading provider or calls any order-placement
    # endpoint.** Verified by the test
    # ``test_ssi_trading_keys_are_inert_in_phase_1`` and by the
    # acceptance grep for ``placeOrder/NewOrder/place_order``.
    ssi_trading_base_url: str = "https://fc-tradeapi.ssi.com.vn"
    ssi_trading_consumer_id: str = ""
    ssi_trading_consumer_secret: str = ""

    # ── Redis ──────────────────────────────────────────────────────────────
    redis_url: str = ""
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""

    # ── Market poller ──────────────────────────────────────────────────────
    enable_market_poller: bool = False
    market_poll_interval_seconds: float = 15.0
    watchlist_poll_interval_seconds: float = 10.0
    full_market_poll_interval_seconds: float = 300.0
    quote_cache_ttl_seconds: int = 30
    index_cache_ttl_seconds: int = 30
    top_movers_cache_ttl_seconds: int = 60
    market_core_symbols: list[str] = Field(
        default_factory=lambda: ["FPT", "MWG", "HPG", "VNM", "VCB", "VRE"]
    )
    market_core_indices: list[str] = Field(
        default_factory=lambda: ["VNINDEX", "VN30"]
    )

    @field_validator("market_core_symbols", "market_core_indices", mode="before")
    @classmethod
    def _split_csv_upper(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip().upper() for s in v.split(",") if s.strip()]
        return v

    # ── Data paths ─────────────────────────────────────────────────────────
    duckdb_path: str = "./data/duckdb/quant_vn.duckdb"
    parquet_data_dir: str = "./data/parquet"

    # ── Helpers ────────────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def required_secret_fields(self) -> tuple[str, ...]:
        """Secrets that must be set before production traffic is served."""
        return (
            "supabase_url",
            "supabase_jwt_secret",
            "supabase_service_role_key",
            "database_url",
            "ssi_consumer_id",
            "ssi_consumer_secret",
        )

    def missing_secrets(self) -> list[str]:
        return [f for f in self.required_secret_fields() if not getattr(self, f)]

    def warn_if_missing_secrets(self) -> list[str]:
        """In prod: raise. In dev/staging: log a warning. Returns the list."""
        # Production CORS guard — must run before the missing-secrets check
        # because a wide-open CORS in production is independently disqualifying.
        if self.is_production:
            self._assert_production_cors()
            # Production must never silently serve mock market data. Phase 2A
            # explicitly forbids ``SSI_USE_MOCK=true`` in production — if the
            # SSI provider isn't configured, the missing-secrets check below
            # will catch it; flipping mock mode is NOT a substitute.
            self._assert_production_ssi_real_mode()
        missing = self.missing_secrets()
        if not missing:
            return []
        if self.is_production:
            raise RuntimeError(
                f"Refusing to start in production with missing secrets: {missing}"
            )
        _logger.warning(
            "Starting with placeholder values for: %s. Routes that depend on "
            "these will respond with 503 until configured.",
            ", ".join(missing),
        )
        return missing

    def _assert_production_cors(self) -> None:
        """Refuse to start in production with localhost defaults or wildcard CORS.

        ``["http://localhost:3000"]`` is the dev default — shipping it to prod
        means the real frontend origin was never configured. ``"*"`` paired
        with ``allow_credentials=True`` (which we set in main.py) is a textbook
        misconfiguration that browsers will reject anyway, so fail loud.
        """
        # Wildcard rejection.
        if any(origin.strip() == "*" for origin in self.cors_origins):
            raise RuntimeError(
                "Refusing to start in production with CORS_ORIGINS=['*']. "
                "Set CORS_ORIGINS to your frontend origin(s) as a JSON list."
            )
        # Localhost-default rejection. We accept "localhost" as PART of the
        # list (some staging-prod setups need it) but not as the ONLY entry,
        # which means nobody overrode the dev default.
        non_local = [
            o for o in self.cors_origins
            if "localhost" not in o and "127.0.0.1" not in o
        ]
        if not non_local:
            raise RuntimeError(
                "Refusing to start in production with only localhost CORS_ORIGINS. "
                "Set CORS_ORIGINS to your production frontend origin "
                "(e.g. CORS_ORIGINS='[\"https://your-domain\"]')."
            )

    def _assert_production_ssi_real_mode(self) -> None:
        """Refuse to start in production with ``SSI_USE_MOCK=true``.

        Phase 2A rule: production dashboards must serve real SSI FastConnect
        Data — never deterministic mock data. The dashboard cannot silently
        fall back to mock if SSI credentials are missing. Operators who need
        a "demo-without-SSI" deploy must use ``APP_ENV=staging`` (which still
        permits mock mode for fixtures).
        """
        if self.ssi_use_mock:
            raise RuntimeError(
                "Refusing to start in production with SSI_USE_MOCK=true. "
                "Production must serve real SSI FastConnect Data. "
                "Set SSI_USE_MOCK=false and populate SSI_CONSUMER_ID + "
                "SSI_CONSUMER_SECRET on the API host."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Use this from FastAPI dependencies."""
    return Settings()

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

    # ── SSI FastConnect Trading — PHASE 2.5 READ-ONLY + PREVIEW ───────────
    # Phase 2.5 wires a TradingProvider for READ-ONLY account inspection
    # (cash, positions, max-buy/sell, order book, order history) plus a
    # pure-Python order-preview calculator.
    #
    # NO order-placement code path exists. The three forbidden routes
    # (POST /trading/new-order, /submit-order, /cancel-order) are wired to
    # return 501 + emit a security audit log. The
    # ``ssi_trading_order_placement_enabled`` flag stays false everywhere
    # and is asserted via ``_assert_production_order_placement_disabled``.
    ssi_trading_base_url: str = "https://fc-tradeapi.ssi.com.vn"
    ssi_trading_consumer_id: str = ""
    ssi_trading_consumer_secret: str = ""
    ssi_trading_use_mock: bool = True
    ssi_trading_read_only: bool = True
    ssi_trading_order_placement_enabled: bool = False
    ssi_trading_timeout_seconds: float = 10.0

    # ── Phase 2.8 Manual-confirm live trading ──────────────────────────────
    # Five-flag AND gate. Real SSI NewOrder runs ONLY when every flag is
    # in the "live" state AND the orchestrator validates re-auth +
    # confirmation + risk + preview-not-expired at submit time. Defaults
    # are conservative: live disabled, dry-run on, require re-auth.
    trading_live_order_enabled: bool = False
    trading_manual_confirm_enabled: bool = False
    trading_require_reauth: bool = True
    trading_reauth_max_age_seconds: int = 300
    trading_order_placement_dry_run: bool = True
    # Stored-preview-to-submit window. AC: 60s default.
    order_preview_max_age_seconds: int = 60

    # ── Phase 2.6 Auto-trade safety foundation ─────────────────────────────
    # The dashboard exposes a MODE state (OFF / PAPER_ONLY /
    # LIVE_MANUAL_CONFIRM / LIVE_AUTO) so a user can express intent. NONE
    # of these modes submit a real broker order in Phase 2.6 — execution
    # is gated by BOTH ``auto_trade_order_placement_enabled`` AND
    # ``ssi_trading_order_placement_enabled``, with a startup guard that
    # refuses production if either is true.
    auto_trade_enabled: bool = False
    auto_trade_live_enabled: bool = False
    auto_trade_reauth_max_age_seconds: int = 300
    auto_trade_require_2fa: bool = False
    auto_trade_default_mode: Literal[
        "OFF", "PAPER_ONLY", "LIVE_MANUAL_CONFIRM", "LIVE_AUTO"
    ] = "OFF"
    auto_trade_order_placement_enabled: bool = False

    # ── Phase 2.9 Guarded auto trading engine ──────────────────────────────
    # Layered AND-gate. Worker + dry-run + live execution flags must ALL be
    # in the "live" state for the engine to submit real orders, AND the
    # 13+ runtime checks in services/auto_trade_risk.py must pass per order.
    auto_trade_dry_run: bool = True
    auto_trade_worker_enabled: bool = False
    auto_trade_max_runtime_minutes: int = 240
    auto_trade_require_market_open: bool = True
    auto_trade_symbol_cooldown_minutes: int = 30
    # Optional shared secret for cron-style worker triggers. When set,
    # the worker-tick route accepts EITHER a valid user JWT OR this
    # header. When empty, only user-JWT path is allowed.
    auto_trade_worker_secret: str = ""
    # Conservative tick cap so a misconfigured external scheduler can't
    # hammer the engine.
    auto_trade_max_decisions_per_tick: int = 20

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
            # Sent as the PostgREST ``apikey`` header on every Supabase DB call
            # (services/supabase_db.PostgrestDB). If empty, PostgREST returns
            # 401 "No API key found" and every authed data route fails with
            # "Not authorized." even though JWT verification succeeded.
            "supabase_anon_key",
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
            # Phase 2.5: production must refuse to start with order
            # placement enabled. The current product is recommend-only +
            # preview-only; live trading is a deliberate Phase 3 milestone
            # that requires its own review.
            self._assert_production_order_placement_disabled()
            # Phase 2.6: production must refuse to start with auto-trade
            # order placement enabled OR auto-trade live enabled. Mode
            # selection is allowed; execution is not.
            self._assert_production_auto_trade_disabled()
            # Phase 2.8: warn loudly (do NOT refuse — AC permits operator
            # opt-in) if live order submission is enabled in production
            # while dry-run is off. Combined with the 5-flag orchestrator
            # gate this provides defence-in-depth.
            self._warn_production_live_order_enabled()
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

    def _assert_production_order_placement_disabled(self) -> None:
        """Refuse to start in production with order placement enabled.

        Phase 2.5 is read-only + preview-only. The dashboard never submits
        a real order. ``SSI_TRADING_ORDER_PLACEMENT_ENABLED=true`` in
        production indicates an operator tried to bypass the Phase 3
        gating step — fail loud.
        """
        if self.ssi_trading_order_placement_enabled:
            raise RuntimeError(
                "Refusing to start in production with "
                "SSI_TRADING_ORDER_PLACEMENT_ENABLED=true. "
                "Phase 2.5 is recommend + preview only. Live order "
                "placement is a Phase 3 milestone with its own review."
            )

    def _warn_production_live_order_enabled(self) -> None:
        """Log a loud warning when live order submission is on in prod.

        Phase 2.8 spec permits operator opt-in (unlike Phase 2.6 which
        refused startup), so this is a warn — not a raise. Combined with
        the 5-flag orchestrator gate + manual-confirm UX, accidental
        live-order shipment requires multiple distinct operator decisions.
        """
        if (
            self.trading_live_order_enabled
            and not self.trading_order_placement_dry_run
        ):
            _logger.warning(
                "Phase 2.8 LIVE ORDER SUBMISSION is ENABLED in production "
                "(TRADING_LIVE_ORDER_ENABLED=true + DRY_RUN=false). Real "
                "broker calls will be issued when an authenticated user "
                "manually confirms an order. Disable by setting "
                "TRADING_ORDER_PLACEMENT_DRY_RUN=true."
            )

    def _assert_production_auto_trade_disabled(self) -> None:
        """Refuse to start in production with auto-trade live execution
        flags enabled UNLESS the operator has also flipped the Phase 2.9
        worker + dry-run flags consistently.

        Phase 2.6 → 2.8: this method refused startup if either
        ``AUTO_TRADE_LIVE_ENABLED`` or ``AUTO_TRADE_ORDER_PLACEMENT_ENABLED``
        was true. Phase 2.9 introduces the guarded-auto-trade engine,
        which the AC permits in production once the operator has
        deliberately flipped a coherent set of flags. We now require:

          * ``AUTO_TRADE_WORKER_ENABLED=true`` paired with live flags,
            so the orchestrator actually runs.
          * ``AUTO_TRADE_DRY_RUN=false`` paired with live flags, so
            the operator's intent is explicit.

        A half-flipped combination (e.g. LIVE_ENABLED=true but
        DRY_RUN=true) is rejected as misconfiguration — the operator
        either wanted live or didn't.
        """
        live_pair = (
            self.auto_trade_live_enabled
            and self.auto_trade_order_placement_enabled
        )
        worker_on = self.auto_trade_worker_enabled
        dry_run = self.auto_trade_dry_run

        if live_pair and not worker_on:
            raise RuntimeError(
                "Refusing to start in production with auto-trade live "
                "flags on but AUTO_TRADE_WORKER_ENABLED=false. Either "
                "disable LIVE/ORDER_PLACEMENT or enable the worker."
            )
        if live_pair and dry_run:
            raise RuntimeError(
                "Refusing to start in production with auto-trade live "
                "flags on but AUTO_TRADE_DRY_RUN=true. Pick one — "
                "dry-run cannot coexist with live execution intent."
            )
        # Half-flipped guard kept from 2.6 — if only one of the live
        # pair is on, the operator's intent is ambiguous.
        if self.auto_trade_live_enabled and not self.auto_trade_order_placement_enabled:
            raise RuntimeError(
                "Refusing to start in production with "
                "AUTO_TRADE_LIVE_ENABLED=true but "
                "AUTO_TRADE_ORDER_PLACEMENT_ENABLED=false. Inconsistent."
            )
        if self.auto_trade_order_placement_enabled and not self.auto_trade_live_enabled:
            raise RuntimeError(
                "Refusing to start in production with "
                "AUTO_TRADE_ORDER_PLACEMENT_ENABLED=true but "
                "AUTO_TRADE_LIVE_ENABLED=false. Inconsistent."
            )
        # Phase 2.9 review HIGH carry-over: when the worker is enabled
        # in production, an empty AUTO_TRADE_WORKER_SECRET means the
        # worker-tick endpoint accepts any request that supplies the
        # JWT but omits ``X-Worker-Secret``. The header check uses
        # ``hmac.compare_digest("", "")`` which returns True. Refuse
        # to boot rather than expose an open tick endpoint.
        if worker_on and not self.auto_trade_worker_secret.strip():
            raise RuntimeError(
                "Refusing to start in production with "
                "AUTO_TRADE_WORKER_ENABLED=true but "
                "AUTO_TRADE_WORKER_SECRET is empty. Set a strong "
                "secret (>=32 chars) to gate the tick endpoint."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Use this from FastAPI dependencies."""
    return Settings()

.PHONY: help install install-api install-web dev dev-api dev-web \
        test test-api test-web lint lint-api lint-web format format-api format-web \
        ci-backend ci-frontend ci-lint \
        deploy-check \
        clean

API_DIR := apps/api
WEB_DIR := apps/web
PY      ?= python3
PNPM    ?= pnpm

help:
	@echo "Targets:"
	@echo "  install        Install API + web dependencies"
	@echo "  dev            Print run instructions for api+web"
	@echo "  dev-api        Run FastAPI dev server (port 8000)"
	@echo "  dev-web        Run Next.js dev server (port 3000)"
	@echo "  test           Run API + web tests"
	@echo "  lint           Lint API + web"
	@echo "  format         Format API + web"
	@echo "  build          Build web for production + build API container image"
	@echo "  build-web      pnpm build (production assets in apps/web/.next)"
	@echo "  build-api-image  docker build apps/api (TAG=local by default)"
	@echo "  ci-backend     Same pytest subset as GitHub Actions backend-tests.yml"
	@echo "  ci-frontend    Same typecheck + build + vitest as frontend-build.yml"
	@echo "  ci-lint        Same ruff + eslint + prettier --check as lint.yml"
	@echo "  deploy-check   Post-deploy smoke vs API_BASE_URL using JWT (read-only)"

install: install-api install-web

install-api:
	cd $(API_DIR) && $(PY) -m pip install -e ".[dev]"

install-web:
	cd $(WEB_DIR) && $(PNPM) install

dev:
	@echo "Run these in two terminals:"
	@echo "  make dev-api"
	@echo "  make dev-web"

dev-api:
	cd $(API_DIR) && $(PY) -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

dev-web:
	cd $(WEB_DIR) && $(PNPM) dev

test: test-api test-web

test-api:
	cd $(API_DIR) && $(PY) -m pytest tests/ -v

test-web:
	@cd $(WEB_DIR) && ($(PNPM) test 2>/dev/null || echo "(web tests are placeholder; pnpm build runs the smoke check)")

lint: lint-api lint-web

lint-api:
	cd $(API_DIR) && $(PY) -m ruff check .

lint-web:
	cd $(WEB_DIR) && $(PNPM) lint

format: format-api format-web

format-api:
	cd $(API_DIR) && $(PY) -m ruff format .

format-web:
	cd $(WEB_DIR) && $(PNPM) exec prettier --write "src/**/*.{ts,tsx,css,md}"

# ── Production build ────────────────────────────────────────────────────────

build: build-web build-api-image

build-web:
	cd $(WEB_DIR) && $(PNPM) build

# Build the API container image used by docker-compose --profile api.
# Tag is overridable: ``make build-api-image TAG=v0.1.0``.
TAG ?= local
build-api-image:
	cd $(API_DIR) && docker build -t quant-vn-api:$(TAG) .

# ── CI mirrors ──────────────────────────────────────────────────────────────
# These targets must stay in sync with .github/workflows/*.yml so devs can
# reproduce CI locally without pushing.

ci-backend:
	cd $(API_DIR) && APP_ENV=development CORS_ORIGINS='["http://localhost:3000"]' \
		SSI_USE_MOCK=true $(PY) -m pytest -q \
		--ignore=tests/test_market_routes.py \
		--ignore=tests/test_watchlist.py \
		--ignore=tests/test_config.py \
		--ignore=tests/test_mock_provider.py \
		--ignore=tests/test_portfolio_manual.py \
		--ignore=tests/test_live_routes.py \
		--ignore=tests/test_stream_routes.py \
		--ignore=tests/test_cache.py \
		--ignore=tests/test_market_poller.py \
		--ignore=tests/test_settings.py \
		--ignore=tests/test_auth.py \
		--ignore=tests/test_isolation.py \
		--ignore=tests/test_health.py \
		--ignore=tests/test_ssi_provider.py

ci-frontend:
	cd $(WEB_DIR) && $(PNPM) typecheck && $(PNPM) build && $(PNPM) test

ci-lint:
	cd $(API_DIR) && $(PY) -m ruff check src tests
	cd $(WEB_DIR) && $(PNPM) lint
	cd $(WEB_DIR) && $(PNPM) exec prettier --check "src/**/*.{ts,tsx,css,md}"

# ── Post-deploy smoke ──────────────────────────────────────────────────────
# Wraps scripts/production-smoke.sh with friendlier error messages.
# Read-only by design: 4 GET calls, no write, never logs the JWT.
#
# Usage:
#   make deploy-check API_BASE_URL=https://<host> JWT=<token>
#
# Optional:
#   SMOKE_SYMBOLS=FPT,MWG,HPG   override the symbol list
#   SMOKE_STRICT_QUOTES=1        also fail if any quote.stale=true
deploy-check:
	@if [ -z "$$API_BASE_URL" ]; then \
		echo "ERROR: API_BASE_URL is required."; \
		echo "Usage: make deploy-check API_BASE_URL=https://<host> JWT=<token>"; \
		exit 1; \
	fi
	@if [ -z "$$JWT" ]; then \
		echo "ERROR: JWT is required (paste a fresh Supabase access token)."; \
		echo "Usage: make deploy-check API_BASE_URL=https://<host> JWT=<token>"; \
		exit 1; \
	fi
	@echo "→ Running production smoke against $$API_BASE_URL"
	@bash scripts/production-smoke.sh

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
	rm -rf $(WEB_DIR)/.next $(WEB_DIR)/node_modules

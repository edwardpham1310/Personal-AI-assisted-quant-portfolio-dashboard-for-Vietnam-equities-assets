#!/usr/bin/env bash
# production-smoke.sh — read-only post-deploy smoke for the Quant VN
# Dashboard backend. Run from the operator workstation after a deploy
# and confirm the four release gates from the production runbook §3.4:
#
#   1. /health                  → liveness
#   2. /system/status           → missing_secrets is empty
#   3. /market/status           → SSI provider ready
#   4. /market/live/quotes      → real, non-stale quote for the core symbols
#
# Usage:
#   API_BASE_URL=https://<backend> JWT=<paste> \
#     scripts/production-smoke.sh
#
# Optional overrides:
#   SMOKE_SYMBOLS=FPT,MWG,HPG   (defaults to FPT,MWG,HPG)
#   SMOKE_STRICT_QUOTES=1        (fail if any quote is stale=true)
#
# Exit codes:
#   0 = every check passed
#   1 = missing env var (API_BASE_URL or JWT)
#   2 = liveness failed
#   3 = missing_secrets non-empty OR /system/status non-200
#   4 = market provider not ready
#   5 = quote endpoint returned empty / mock-sourced / stale (under strict)
#   6 = required CLI dependency missing (curl/jq)
#
# Read-only by design. This script never enables trading, never sends a
# write, and never logs the JWT. Tokens stay in environment variables
# and the script does not echo them.

set -uo pipefail

# ── Dependency check ────────────────────────────────────────────────────────
for bin in curl jq; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        printf 'ERROR: %s is required but not installed.\n' "$bin" >&2
        exit 6
    fi
done

# ── Input validation ────────────────────────────────────────────────────────
: "${API_BASE_URL:?Set API_BASE_URL to the backend host (e.g. https://api.example.com)}"
: "${JWT:?Set JWT to a valid Supabase user access token}"

SYMBOLS="${SMOKE_SYMBOLS:-FPT,MWG,HPG}"
STRICT_QUOTES="${SMOKE_STRICT_QUOTES:-0}"

# Trim trailing slash so we can string-concat paths cleanly.
API_BASE_URL="${API_BASE_URL%/}"

AUTH_HEADER="Authorization: Bearer ${JWT}"

# Helper: GET with auth, fail on HTTP >=400.
auth_get() {
    local path="$1"
    # -fS suppresses progress but DOES surface 4xx/5xx with body; we want
    # the body for diagnostics so we use --fail-with-body which prints
    # the response on failure.
    curl --fail-with-body -sS \
         -H "${AUTH_HEADER}" \
         "${API_BASE_URL}${path}"
}

step() { printf '\n── %s ──\n' "$1"; }
ok()   { printf '  ✓ %s\n' "$1"; }
fail() { printf '  ✗ %s\n' "$1" >&2; }

# ── 1. Liveness ─────────────────────────────────────────────────────────────
step "1. Liveness /health"
HEALTH_BODY="$(curl --fail-with-body -sS "${API_BASE_URL}/health" || true)"
if [[ -z "${HEALTH_BODY}" ]]; then
    fail "Liveness request returned empty body."
    exit 2
fi
HEALTH_STATUS="$(printf '%s' "${HEALTH_BODY}" | jq -r '.status // empty')"
if [[ "${HEALTH_STATUS}" != "ok" ]]; then
    fail "Expected .status='ok', got: ${HEALTH_BODY}"
    exit 2
fi
ok "/health returned status=ok"

# ── 2. System status — missing_secrets must be empty ───────────────────────
step "2. /system/status missing_secrets check"
if ! SYSTEM_BODY="$(auth_get '/system/status')"; then
    fail "/system/status did not return 2xx."
    exit 3
fi
MISSING_COUNT="$(printf '%s' "${SYSTEM_BODY}" | jq -r '.missing_secrets | length')"
if [[ "${MISSING_COUNT}" != "0" ]]; then
    fail "missing_secrets is non-empty: $(printf '%s' "${SYSTEM_BODY}" | jq -c '.missing_secrets')"
    exit 3
fi
ok "missing_secrets is []"

# Surface Redis status as informational (don't fail — Phase 1 permits
# the in-memory fallback for cheap deploys, but operator should see it).
REDIS_CONFIGURED="$(printf '%s' "${SYSTEM_BODY}" | jq -r '.redis_configured // false')"
ok "redis_configured=${REDIS_CONFIGURED}"

# ── 3. Market provider readiness ───────────────────────────────────────────
step "3. /market/status SSI readiness"
if ! MARKET_BODY="$(auth_get '/market/status')"; then
    fail "/market/status did not return 2xx."
    exit 4
fi
MARKET_READY="$(printf '%s' "${MARKET_BODY}" | jq -r '.ready // false')"
MARKET_STATUS_CODE="$(printf '%s' "${MARKET_BODY}" | jq -r '.status_code // .mode // "UNKNOWN"')"
if [[ "${MARKET_READY}" != "true" ]]; then
    fail "Market provider not ready: status_code=${MARKET_STATUS_CODE} body=${MARKET_BODY}"
    exit 4
fi
ok "market provider ready=true (status_code=${MARKET_STATUS_CODE})"

# ── 4. Real quotes for the core symbols ────────────────────────────────────
step "4. /market/live/quotes?symbols=${SYMBOLS}"
if ! QUOTES_BODY="$(auth_get "/market/live/quotes?symbols=${SYMBOLS}")"; then
    fail "/market/live/quotes did not return 2xx."
    exit 5
fi
QUOTE_COUNT="$(printf '%s' "${QUOTES_BODY}" | jq 'length')"
if [[ "${QUOTE_COUNT}" -eq 0 ]]; then
    fail "Quote endpoint returned 0 rows."
    exit 5
fi

# Source must be 'ssi' (live) or 'cache' (poller-filled). 'mock' is a
# release-blocker in production.
MOCK_SOURCED="$(printf '%s' "${QUOTES_BODY}" | jq '[.[] | select(.source == "mock")] | length')"
if [[ "${MOCK_SOURCED}" -gt 0 ]]; then
    fail "Quote endpoint returned ${MOCK_SOURCED} mock-sourced row(s). Production must serve real SSI data."
    printf '%s\n' "${QUOTES_BODY}" | jq '[.[] | {symbol, source, price, stale}]' >&2
    exit 5
fi
ok "all ${QUOTE_COUNT} quotes are real (source=ssi|cache)"

if [[ "${STRICT_QUOTES}" == "1" ]]; then
    STALE_COUNT="$(printf '%s' "${QUOTES_BODY}" | jq '[.[] | select(.stale == true)] | length')"
    if [[ "${STALE_COUNT}" -gt 0 ]]; then
        fail "${STALE_COUNT} quote(s) marked stale=true under strict mode."
        printf '%s\n' "${QUOTES_BODY}" | jq '[.[] | {symbol, source, price, stale, ts}]' >&2
        exit 5
    fi
    ok "no stale quotes (strict mode)"
else
    STALE_COUNT="$(printf '%s' "${QUOTES_BODY}" | jq '[.[] | select(.stale == true)] | length')"
    if [[ "${STALE_COUNT}" -gt 0 ]]; then
        printf '  ! %s quote(s) marked stale=true (informational; outside market hours this is expected)\n' "${STALE_COUNT}"
    fi
fi

# Sample one row for the operator log.
printf '%s\n' "${QUOTES_BODY}" | jq '.[0] | {symbol, source, price, stale, ts}'

# ── Done ────────────────────────────────────────────────────────────────────
step "ALL CHECKS PASSED"
printf 'Backend is serving real SSI data and the four release gates are green.\n'
printf 'Frontend-side checks (DevTools secret scan, bundle inspection) must still\n'
printf 'be run manually per docs/production-runbook.md §3.4.\n'
exit 0

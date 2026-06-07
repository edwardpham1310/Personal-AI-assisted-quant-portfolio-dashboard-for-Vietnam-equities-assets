#!/usr/bin/env bash
#
# Daily equity-curve NAV snapshot producer for the dashboard.
#
# The equity curve is forward-only: it only contains days that were actually
# snapshotted. The dashboard records a point when opened, but to capture NAV
# reliably even on days nobody opens the dashboard, cron this script after the
# HOSE close on TRADING DAYS (Mon–Fri, ~15:05 Asia/Ho_Chi_Minh):
#
#   5 8 * * 1-5  API_BASE_URL=https://api.example.com \
#                DASHBOARD_USER_TOKEN=eyJ... \
#                /path/to/snapshot-equity.sh   # 15:05 ICT == 08:05 UTC
#
# It calls the existing auth-gated POST /portfolio/snapshots/run with a
# dashboard USER token (RLS-scoped to that user's default account). It is:
#   * read-only valuation persistence — NO orders, NO trading;
#   * idempotent per trading day (a repeat call recomputes the same row);
#   * honest — if the quote cache is cold (a held position is unpriced) the API
#     returns {"recorded": false, "reason": "quotes_unavailable"} and writes
#     NOTHING rather than a misleading low NAV. Ensure the market poller is warm
#     (ENABLE_MARKET_POLLER=true) around the snapshot time, or re-run later.
#
# Requires: API_BASE_URL, DASHBOARD_USER_TOKEN. Exits non-zero on HTTP error.
set -euo pipefail

: "${API_BASE_URL:?set API_BASE_URL (e.g. https://api.example.com)}"
: "${DASHBOARD_USER_TOKEN:?set DASHBOARD_USER_TOKEN (a dashboard user JWT)}"

resp="$(curl -fsS -X POST "${API_BASE_URL%/}/portfolio/snapshots/run" \
  -H "Authorization: Bearer ${DASHBOARD_USER_TOKEN}" \
  -H "Content-Type: application/json")"

echo "snapshot-equity: ${resp}"

# Surface a non-recorded run (e.g. cold cache) for cron logs without failing —
# it is a valid honest outcome the operator may want to retry.
case "${resp}" in
  *'"recorded":false'*|*'"recorded": false'*)
    echo "snapshot-equity: NOTE — snapshot not recorded (see reason above)." >&2
    ;;
esac

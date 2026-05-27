# Audit Note: Product Direction SSI Intraday AI Dashboard

Date: 2026-05-27
Agent: Codex

## Intent

Record the confirmed product direction from the user: build a personal
AI-assisted quant portfolio dashboard for Vietnam market assets, SSI-first,
intraday 5m/15m, Claude/MCP narrative analysis, broad Vietnam asset scope, and
recommend-only in phase 1.

## Files Changed

- `docs/product-vision.md`: added workspace-level product vision and phase plan.
- `CLAUDE.md`: added product direction to workspace instructions.
- `docs/architecture.md`: updated workspace architecture with SSI-first and
  dashboard responsibilities.
- `docs/trading-rules.md`: added AI/realtime dashboard rules.
- `quant/docs/project-overview.md`: updated product direction and near-term
  roadmap.
- `quant/docs/dashboard/dashboard-spec.md`: updated dashboard goals, non-goals,
  product decisions, panels, and broker roadmap.
- `quant/docs/trading-recommendation-framework.md`: added intraday 5m/15m and AI
  narrative guardrails.
- `quant/docs/agent-memory/shared-context.md`: updated shared agent memory with
  SSI-first, 5m/15m, Claude/MCP, and recommend-only decisions.

## Behavior Changed

Agents should now treat the project as an SSI-first personal AI-assisted
portfolio dashboard, not only a static backtest/reporting tool. Phase 1 remains
recommend-only and must not include live order placement.

## Verification

- Documentation updated directly.
- No runtime behavior changed.

## Follow-Ups

- Design the database schema for portfolio holdings, recommendations, AI
  narratives, and intraday signal snapshots.
- Verify exact SSI FastConnect data endpoints and account entitlements for
  5m/15m bars and read-only account sync.
- Define MCP tools for Claude to read portfolio state and computed indicators.

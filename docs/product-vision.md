# Product Vision — Personal AI-Assisted Quant Portfolio Dashboard

## Target Product

The project is a personal AI-assisted quant portfolio dashboard for Vietnam
equities and related Vietnam market instruments.

The system should help the owner monitor portfolio risk, interpret market data,
and receive explainable buy/sell/hold/rotate suggestions. Phase 1 is
recommend-only: the dashboard can suggest actions, but it must not place orders.

## Confirmed Direction

- Broker/data ecosystem: SSI-first, because SSI FastConnect has supported APIs
  for market data and trading workflows.
- Signal horizon: intraday 5-minute and 15-minute signals are the core tactical
  timeframe.
- AI layer: Claude plus MCP should read computed indicators and portfolio state
  from the database, then produce natural-language risk warnings and trade
  suggestions for the dashboard.
- Asset scope: all supported Vietnam market assets over time, including stocks,
  ETFs, derivatives, funds, and other instruments if reliable data and broker
  support are available.
- Execution phase: recommend-only first. No automatic broker order placement in
  the initial product phase.

## Product Principles

- Quant rules compute evidence; AI explains evidence.
- Broker credentials remain outside source control.
- Every recommendation must be auditable: data timestamp, indicators, score,
  reasons, risks, and model/agent version if AI narrative is used.
- Realtime should mean timely enough for decision support, not high-frequency
  trading.
- Manual user judgment remains required before any real order.

## Phase Plan

### Phase 1: Recommend-Only Dashboard

- Portfolio input from CSV/manual entry or read-only broker sync when available.
- Intraday 5m/15m data ingestion from SSI where API access supports it.
- Technical signal engine computes tactical buy/sell/hold/reduce candidates.
- Claude/MCP reads DB snapshots and writes natural-language explanation.
- Dashboard shows action suggestions without order buttons.

### Phase 2: Read-Only Broker Integration

- Sync holdings, cash, buying power, order history, and realized/unrealized P/L.
- Reconcile broker portfolio state with local portfolio records.
- Keep dashboard recommend-only.

### Phase 3: Paper Trading And Action Audit

- Convert recommendations into proposed orders in a paper-trading ledger.
- Track simulated fills, slippage, missed signals, and post-signal outcomes.
- Use audit data to tune recommendation thresholds.

### Phase 4: Manual Approval Trading

- Add broker adapters for order preview, place, amend, cancel, and order-status
  streaming only after user approval.
- Require a confirmation step, kill switch, max order size, and daily loss guard.

### Phase 5: Limited Automation

- Only consider automation for narrowly defined risk controls or rules that have
  been validated out-of-sample and paper-traded.

## Non-Goals For Now

- Fully autonomous trading.
- HFT or tick-level latency competition.
- AI-generated orders without deterministic guardrails.
- Recommendations without data provenance.

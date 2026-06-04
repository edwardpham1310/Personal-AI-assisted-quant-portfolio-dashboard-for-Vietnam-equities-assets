# SSI read-only account connector (Phase 2.4)

Status: **implemented but SHIPPED DISABLED**. Date: 2026-06-04.

## What was built

A read-only SSI FastConnect **Trading** API connector that can surface broker
**cash balance** and **stock positions** to the dashboard, plus an honest UI
panel. Order placement is **not** part of this — `submit_order` stays 501.

- `providers/trading/ssi_trading.py` — real read-only `get_cash_balance` +
  `get_stock_positions` (RSA-signed token mint + authenticated GET). The other
  reads (`get_max_buy_qty`, `get_max_sell_qty`, `get_order_book`,
  `get_order_history`) remain 501 (not needed for display). `submit_order`
  remains 501 — there is **no** `NewOrder`/cancel/modify/`GetOTP`-for-orders
  code in the file.
- `core/config.py` — new (empty-default) settings:
  `ssi_trading_private_key`, `ssi_trading_account_no`,
  `ssi_trading_two_factor_type`, `ssi_trading_pin`.
- `core/deps.py` — passes the new credentials into `SSITradingProvider`.
- Frontend: `components/portfolio/BrokerAccountCard.tsx` +
  `hooks/useBrokerAccount.ts` — renders live broker cash/holdings **only** when
  the provider reports a genuinely connected read-only SSI session; otherwise an
  honest "mock"/"not connected" message. Never shows mock/fabricated balances
  as real.
- Tests: `tests/test_ssi_trading_provider.py` (mocked HTTP — mapping, missing
  creds → 503, `submit_order` 501, auth-failure sanitisation, status).

## The hard blocker / credential reality (read before enabling)

SSI FastConnect mints **even a read-only access token only after a 2FA PIN/OTP**
(`POST /Trading/AccessToken` requires `twoFactorType` + `code`). That same PIN
authorises **order placement**. Therefore:

- Read-only is **API-separable** from ordering (read GETs need no per-request
  OTP) but **NOT credential-separable** — the ConsumerID + ConsumerSecret + RSA
  private key + PIN that mint a read token are the same secrets an order would
  use. Populating `ssi_trading_pin` puts an order-capable secret in the
  deployment.
- This connector contains no order path, so the worst failure mode is a failed
  read (honest error), never an order. But the credential-level risk is real and
  is the operator's decision to accept.

## Required env/secrets to enable (none are committed)

| Env var | Purpose |
|---|---|
| `SSI_TRADING_USE_MOCK=false` | select the real connector (default `true`) |
| `SSI_TRADING_CONSUMER_ID` / `_CONSUMER_SECRET` | FastConnect Trading app creds |
| `SSI_TRADING_PRIVATE_KEY` | RSA PEM to sign the AccessToken request (hard blocker — no token without it) |
| `SSI_TRADING_ACCOUNT_NO` | broker account number for the read queries |
| `SSI_TRADING_PIN` | 2FA PIN/code (order-capable — see above) |
| `SSI_TRADING_TWO_FACTOR_TYPE` | `0` = PIN, `1` = OTP |

`SSI_TRADING_ORDER_PLACEMENT_ENABLED` stays `false` (prod startup guard refuses
`true`).

## Not yet verified (must be done before production enablement)

The exact AccessToken signing base string, endpoint paths
(`/Trading/AccessToken`, `/Trading/cashAcctBal`, `/Trading/stockPosition`), and
response field names are implemented to FastConnect Trading **conventions** and
are marked `TODO(ssi-sandbox)` in `ssi_trading.py`. They MUST be validated
against the operator's SSI **sandbox** (and the field mapping reconciled with a
real response) before flipping `SSI_TRADING_USE_MOCK=false` in production. Until
then the dashboard correctly shows the manual portfolio and the broker card
reads "not connected".

## Reconciliation note (future)

SSI `StockPosition` carries `sellable_quantity` / `pending_quantity` (T+2) that
`manual_positions` does not; the manual `CashBalance` carries `advanced_cash` /
`cash_advance_liability` (ứng trước) that SSI's cash schema lacks. If SSI
holdings are ever imported into the manual tables (via the
`POST /portfolio/sync/ssi` seam, still 501), use a `source` provenance
discriminator and reconcile rather than silently overwrite user-entered rows.

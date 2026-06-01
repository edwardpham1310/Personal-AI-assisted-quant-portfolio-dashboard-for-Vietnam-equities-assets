"use client";

import { useMemo, useState } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatVnd, formatNumber } from "@/lib/format";
import {
  useCashBalance,
  useOrderPreview,
  useStockPositions,
  useTradingAccounts,
  type OrderType,
  type Side,
} from "@/hooks/useTradingPreview";

const SIDES: Side[] = ["BUY", "SELL"];
const ORDER_TYPES: OrderType[] = ["LIMIT", "MARKET", "ATO", "ATC", "MTL"];

export default function TradingPreviewPage() {
  const accounts = useTradingAccounts();
  const [accountId, setAccountId] = useState<string>("");

  // Auto-select the first account once they load.
  const selected = useMemo(() => {
    if (accountId) return accountId;
    return accounts.data[0]?.id ?? "";
  }, [accountId, accounts.data]);

  const cash = useCashBalance(selected || null);
  const positions = useStockPositions(selected || null);
  const preview = useOrderPreview();

  const [symbol, setSymbol] = useState("FPT");
  const [side, setSide] = useState<Side>("BUY");
  const [quantity, setQuantity] = useState(100);
  const [limitPrice, setLimitPrice] = useState(86000);
  const [orderType, setOrderType] = useState<OrderType>("LIMIT");

  const [newAccountNumber, setNewAccountNumber] = useState("");
  const [newAccountAlias, setNewAccountAlias] = useState("");

  async function onCreateAccount(e: React.FormEvent) {
    e.preventDefault();
    if (!newAccountNumber) return;
    await accounts.create({
      account_number: newAccountNumber,
      account_alias: newAccountAlias || undefined,
    });
    setNewAccountNumber("");
    setNewAccountAlias("");
  }

  async function onPreview(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    await preview.submit({
      account_id: selected,
      symbol: symbol.toUpperCase(),
      side,
      quantity,
      limit_price: limitPrice,
      order_type: orderType,
    });
  }

  return (
    <div className="space-y-6" data-testid="trading-preview-page">
      <header>
        <h1 className="text-xl font-semibold text-ink">Trading Preview</h1>
        <p className="text-sm text-ink-dim mt-1">
          Read-only broker view + order preview calculator. No real order
          is ever submitted from this page.
        </p>
      </header>

      {/* Phase 2.5 critical notice — preview-only. */}
      <div
        role="status"
        data-testid="phase-2-5-banner"
        className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
      >
        <strong className="font-semibold">Preview only</strong> — no real
        order will be submitted. Live trading is disabled in Phase 2.5.
        Fees, taxes, and settlement are research estimates, not the
        broker&apos;s official ticket.
      </div>

      {/* ── Account selector + registration ─────────────────────────── */}
      <Card
        title="Trading account"
        hint="Register your SSI account by entering its number. Only the last-4 is stored."
      >
        {accounts.error ? (
          <p className="text-accent-down text-xs">{accounts.error}</p>
        ) : accounts.data.length === 0 ? (
          <p className="text-ink-muted text-xs">
            No trading account registered. Add one below.
          </p>
        ) : (
          <div className="flex items-center gap-3 flex-wrap">
            <label className="text-xs text-ink-dim">Account:</label>
            <select
              data-testid="account-selector"
              value={selected}
              onChange={(e) => setAccountId(e.target.value)}
              className="rounded border border-border bg-bg px-2 py-1 text-xs text-ink"
            >
              {accounts.data.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.account_alias ?? a.account_number_masked} ({a.broker})
                </option>
              ))}
            </select>
            <Badge tone="neutral">Read-only</Badge>
          </div>
        )}

        <form
          onSubmit={onCreateAccount}
          className="mt-3 flex gap-2 flex-wrap items-end text-xs"
        >
          <div>
            <label className="block text-ink-dim mb-1">Account number</label>
            <input
              data-testid="new-account-number"
              value={newAccountNumber}
              onChange={(e) => setNewAccountNumber(e.target.value)}
              placeholder="123456789"
              className="rounded border border-border bg-bg px-2 py-1 text-ink w-40"
            />
          </div>
          <div>
            <label className="block text-ink-dim mb-1">Alias (optional)</label>
            <input
              value={newAccountAlias}
              onChange={(e) => setNewAccountAlias(e.target.value)}
              placeholder="Main"
              className="rounded border border-border bg-bg px-2 py-1 text-ink w-32"
            />
          </div>
          <button
            type="submit"
            className="rounded border border-border bg-bg-panel px-3 py-1 text-ink hover:bg-bg"
          >
            Register
          </button>
        </form>
      </Card>

      {/* ── Cash + positions read-only views ─────────────────────────── */}
      {selected ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card title="Cash balance" hint="Settled + pending breakdown">
            {cash.error ? (
              <p className="text-accent-down text-xs">{cash.error}</p>
            ) : cash.data ? (
              <dl className="grid grid-cols-2 gap-2 text-xs">
                <dt className="text-ink-dim">Buying power</dt>
                <dd
                  data-testid="cash-buying-power"
                  className="text-right text-ink"
                >
                  {formatVnd(cash.data.buying_power)}
                </dd>
                <dt className="text-ink-dim">Cash balance</dt>
                <dd className="text-right text-ink">
                  {formatVnd(cash.data.cash_balance)}
                </dd>
                <dt className="text-ink-dim">Withdrawable</dt>
                <dd className="text-right text-ink">
                  {formatVnd(cash.data.withdrawable_cash)}
                </dd>
                <dt className="text-ink-dim">Pending (T+2)</dt>
                <dd className="text-right text-amber-200">
                  {formatVnd(cash.data.pending_cash)}
                </dd>
              </dl>
            ) : cash.loading ? (
              <p className="text-ink-muted text-xs">Loading…</p>
            ) : (
              <p className="text-ink-muted text-xs">No cash data.</p>
            )}
          </Card>

          <Card title="Positions" hint="Sellable + pending breakdown">
            {positions.error ? (
              <p className="text-accent-down text-xs">{positions.error}</p>
            ) : positions.data.length > 0 ? (
              <table
                data-testid="positions-table"
                className="w-full text-xs"
              >
                <thead className="text-ink-dim">
                  <tr>
                    <th className="text-left">Symbol</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Sellable</th>
                    <th className="text-right">Avg cost</th>
                    <th className="text-right">Market</th>
                  </tr>
                </thead>
                <tbody>
                  {positions.data.map((p) => (
                    <tr key={p.symbol} className="text-ink">
                      <td>{p.symbol}</td>
                      <td className="text-right">{formatNumber(p.quantity)}</td>
                      <td className="text-right">
                        {formatNumber(p.sellable_quantity)}
                      </td>
                      <td className="text-right">{formatVnd(p.avg_cost)}</td>
                      <td className="text-right">
                        {p.market_price ? formatVnd(p.market_price) : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : positions.loading ? (
              <p className="text-ink-muted text-xs">Loading…</p>
            ) : (
              <p className="text-ink-muted text-xs">No positions.</p>
            )}
          </Card>
        </div>
      ) : null}

      {/* ── Preview form ─────────────────────────────────────────────── */}
      {selected ? (
        <Card title="Order preview" hint="Computed locally — no broker contact">
          <form
            onSubmit={onPreview}
            data-testid="preview-form"
            className="grid grid-cols-2 lg:grid-cols-5 gap-3 text-xs"
          >
            <label className="flex flex-col gap-1">
              <span className="text-ink-dim">Symbol</span>
              <input
                data-testid="input-symbol"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                className="rounded border border-border bg-bg px-2 py-1 text-ink"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-ink-dim">Side</span>
              <select
                data-testid="input-side"
                value={side}
                onChange={(e) => setSide(e.target.value as Side)}
                className="rounded border border-border bg-bg px-2 py-1 text-ink"
              >
                {SIDES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-ink-dim">Quantity</span>
              <input
                data-testid="input-quantity"
                type="number"
                min={1}
                step={100}
                value={quantity}
                onChange={(e) => setQuantity(Number(e.target.value))}
                className="rounded border border-border bg-bg px-2 py-1 text-ink"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-ink-dim">Limit price (VND)</span>
              <input
                data-testid="input-price"
                type="number"
                min={1}
                step={100}
                value={limitPrice}
                onChange={(e) => setLimitPrice(Number(e.target.value))}
                className="rounded border border-border bg-bg px-2 py-1 text-ink"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-ink-dim">Order type</span>
              <select
                value={orderType}
                onChange={(e) => setOrderType(e.target.value as OrderType)}
                className="rounded border border-border bg-bg px-2 py-1 text-ink"
              >
                {ORDER_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <div className="col-span-2 lg:col-span-5 flex gap-3 items-center">
              <button
                type="submit"
                data-testid="preview-submit"
                disabled={preview.loading}
                className="rounded border border-accent/60 bg-accent/10 px-3 py-1 text-accent hover:bg-accent/20 disabled:opacity-50"
              >
                {preview.loading ? "Computing…" : "Preview order"}
              </button>
              {/* Submit-order placeholder — disabled until Phase 3. */}
              <button
                type="button"
                disabled
                title="Live trading not enabled in this phase"
                data-testid="submit-real-order"
                className="rounded border border-border bg-bg-panel px-3 py-1 text-ink-dim cursor-not-allowed"
              >
                Submit real order (disabled)
              </button>
              <span className="text-ink-dim">
                Preview only — no real order will be submitted.
              </span>
            </div>
          </form>
        </Card>
      ) : null}

      {/* ── Preview result ───────────────────────────────────────────── */}
      {preview.error ? (
        <Card title="Preview failed">
          <p className="text-accent-down text-xs">{preview.error}</p>
        </Card>
      ) : preview.result ? (
        <Card title="Preview result" hint={`Status: ${preview.result.validation_status}`}>
          <div data-testid="preview-result" className="space-y-3 text-xs">
            <div className="flex items-center gap-2">
              <Badge
                tone={
                  preview.result.validation_status === "REJECTED"
                    ? "down"
                    : preview.result.validation_status === "WARN"
                      ? "neutral"
                      : "up"
                }
              >
                {preview.result.validation_status}
              </Badge>
              <span className="text-ink">
                {preview.result.side} {preview.result.quantity} {preview.result.symbol}
                {" @ "}
                {formatVnd(preview.result.limit_price)} ({preview.result.order_type})
              </span>
            </div>

            <dl className="grid grid-cols-2 lg:grid-cols-3 gap-2">
              <dt className="text-ink-dim">Gross value</dt>
              <dd className="text-right text-ink lg:col-span-2">
                {formatVnd(preview.result.estimated_value)}
              </dd>
              <dt className="text-ink-dim">Brokerage fee</dt>
              <dd className="text-right text-ink lg:col-span-2">
                {formatVnd(preview.result.estimated_fees)}
              </dd>
              <dt className="text-ink-dim">VAT on fee</dt>
              <dd className="text-right text-ink lg:col-span-2">
                {formatVnd(preview.result.estimated_vat)}
              </dd>
              {preview.result.side === "SELL" ? (
                <>
                  <dt className="text-ink-dim">Sell tax</dt>
                  <dd className="text-right text-ink lg:col-span-2">
                    {formatVnd(preview.result.estimated_tax)}
                  </dd>
                </>
              ) : null}
              <dt className="text-ink-dim">Slippage estimate</dt>
              <dd className="text-right text-ink lg:col-span-2">
                {formatVnd(preview.result.estimated_slippage)}
              </dd>
              {preview.result.total_cash_required !== null ? (
                <>
                  <dt className="text-ink-dim font-semibold">
                    Total cash required
                  </dt>
                  <dd
                    data-testid="result-total-cash"
                    className="text-right text-ink font-semibold lg:col-span-2"
                  >
                    {formatVnd(preview.result.total_cash_required)}
                  </dd>
                </>
              ) : null}
              {preview.result.net_sell_proceeds !== null ? (
                <>
                  <dt className="text-ink-dim font-semibold">
                    Net sell proceeds
                  </dt>
                  <dd
                    data-testid="result-net-proceeds"
                    className="text-right text-ink font-semibold lg:col-span-2"
                  >
                    {formatVnd(preview.result.net_sell_proceeds)}
                  </dd>
                </>
              ) : null}
              {preview.result.settlement_date ? (
                <>
                  <dt className="text-ink-dim">Settlement</dt>
                  <dd className="text-right text-amber-200 lg:col-span-2">
                    T+2 → {preview.result.settlement_date}
                  </dd>
                </>
              ) : null}
            </dl>

            {preview.result.warnings.length > 0 ? (
              <div data-testid="result-warnings">
                <h3 className="text-ink-dim font-semibold mb-1">Warnings</h3>
                <ul className="list-disc list-inside text-amber-200 space-y-0.5">
                  {preview.result.warnings.map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {preview.result.rejection_reasons.length > 0 ? (
              <div data-testid="result-rejections">
                <h3 className="text-ink-dim font-semibold mb-1">
                  Rejection reasons
                </h3>
                <ul className="list-disc list-inside text-accent-down space-y-0.5">
                  {preview.result.rejection_reasons.map((r, idx) => (
                    <li key={idx}>{r}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <p className="text-ink-dim italic">
              Research-only estimate. The broker&apos;s official ticket may
              differ. Live submission disabled
              {": is_live_order_submission_enabled="}
              {String(preview.result.is_live_order_submission_enabled)}.
            </p>
          </div>
        </Card>
      ) : null}
    </div>
  );
}

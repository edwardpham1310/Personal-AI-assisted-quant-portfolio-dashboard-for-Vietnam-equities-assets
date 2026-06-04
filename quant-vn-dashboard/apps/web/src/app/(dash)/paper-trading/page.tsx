"use client";

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { formatVnd, formatNumber, formatPct } from "@/lib/format";
import { sortByTimeAsc } from "@/lib/dateRange";
import {
  usePaperAccounts,
  usePaperEquityCurve,
  usePaperOrderActions,
  usePaperOrdersAndFills,
  usePaperSummary,
  type PaperOrderType,
  type Side,
} from "@/hooks/usePaperTrading";

const SIDES: Side[] = ["BUY", "SELL"];
const ORDER_TYPES: PaperOrderType[] = ["MARKET", "LIMIT"];

export default function PaperTradingPage() {
  const accounts = usePaperAccounts();
  const [accountId, setAccountId] = useState<string>("");
  const selected = useMemo(
    () => accountId || accounts.data[0]?.id || "",
    [accountId, accounts.data],
  );

  const summary = usePaperSummary(selected || null);
  const ordersFills = usePaperOrdersAndFills(selected || null);
  const equity = usePaperEquityCurve(selected || null);
  const actions = usePaperOrderActions(selected || null);

  const [newName, setNewName] = useState("");
  const [newStartCash, setNewStartCash] = useState("100000000");

  const [symbol, setSymbol] = useState("FPT");
  const [side, setSide] = useState<Side>("BUY");
  const [orderType, setOrderType] = useState<PaperOrderType>("MARKET");
  const [quantity, setQuantity] = useState(100);
  const [limitPrice, setLimitPrice] = useState<string>("");

  async function onCreateAccount(e: React.FormEvent) {
    e.preventDefault();
    if (!newName) return;
    await accounts.create({
      name: newName,
      starting_cash: Number(newStartCash) || 0,
    });
    setNewName("");
  }

  async function onSubmitOrder(e: React.FormEvent) {
    e.preventDefault();
    if (!selected) return;
    const lp = limitPrice ? Number(limitPrice) : null;
    const r = await actions.submit({
      symbol: symbol.toUpperCase(),
      side,
      order_type: orderType,
      quantity,
      limit_price: lp,
    });
    if (r) {
      await Promise.all([summary.refresh(), ordersFills.refresh(), equity.refresh()]);
    }
  }

  // Defensive: sort by the raw timestamp ascending BEFORE formatting to a
  // locale string (which is not chronologically sortable), so the curve always
  // renders oldest→newest regardless of source order.
  const equityChartData = sortByTimeAsc(equity.data, (p) => p.timestamp).map((p) => ({
    ts: new Date(p.timestamp).toLocaleString(),
    equity: p.total_equity,
    drawdown: -(p.drawdown * 100),
  }));

  return (
    <div className="space-y-6" data-testid="paper-trading-page">
      <header>
        <h1 className="text-xl font-semibold text-ink">Paper Trading</h1>
        <p className="text-sm text-ink-dim mt-1">
          Simulated trades using real SSI market data. No real broker orders are placed.
        </p>
      </header>

      <div
        role="status"
        data-testid="phase-2-7-banner"
        className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
      >
        <strong className="font-semibold">Paper only</strong> — every order on this page is
        simulated. Live execution is disabled. Fees, taxes, T+2 settlement, and slippage are
        modelled but the broker is never contacted.
      </div>

      {/* ── Account selector + create ──────────────────────────── */}
      <Card title="Paper account" hint="Each account has its own cash + positions">
        {accounts.data.length === 0 ? (
          <p className="text-ink-muted text-xs">No paper account yet. Create one below.</p>
        ) : (
          <select
            data-testid="paper-account-selector"
            value={selected}
            onChange={(e) => setAccountId(e.target.value)}
            className="rounded border border-border bg-bg px-2 py-1 text-xs text-ink"
          >
            {accounts.data.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} ({a.currency})
              </option>
            ))}
          </select>
        )}
        <form
          onSubmit={onCreateAccount}
          data-testid="create-account-form"
          className="mt-3 flex flex-wrap gap-2 items-end text-xs"
        >
          <div>
            <label className="block text-ink-dim mb-1">Name</label>
            <input
              data-testid="new-account-name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="rounded border border-border bg-bg px-2 py-1 text-ink w-40"
            />
          </div>
          <div>
            <label className="block text-ink-dim mb-1">Starting cash (VND)</label>
            <input
              data-testid="new-account-cash"
              type="number"
              min={0}
              value={newStartCash}
              onChange={(e) => setNewStartCash(e.target.value)}
              className="rounded border border-border bg-bg px-2 py-1 text-ink w-40"
            />
          </div>
          <button
            type="submit"
            className="rounded border border-border bg-bg-panel px-3 py-1 text-ink hover:bg-bg"
          >
            Create
          </button>
        </form>
      </Card>

      {/* ── Cash + equity cards ─────────────────────────────────── */}
      {selected && summary.data ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <KpiBlock label="Cash" value={formatVnd(summary.data.cash)} />
          <KpiBlock
            label="Pending cash (T+2)"
            value={formatVnd(summary.data.pending_cash)}
            tone="warning"
          />
          <KpiBlock label="Stock value" value={formatVnd(summary.data.stock_value)} />
          <KpiBlock
            label="Total equity"
            value={formatVnd(summary.data.total_equity)}
            sub={`Drawdown: ${formatPct(-summary.data.drawdown, 2)}`}
          />
        </div>
      ) : null}

      {/* ── Settlement panel ────────────────────────────────────── */}
      {summary.data ? (
        <Card title="Settlement pending" hint="T+2 simulation status">
          <dl className="grid grid-cols-2 gap-2 text-xs">
            <dt className="text-ink-dim">Pending cash</dt>
            <dd data-testid="pending-cash" className="text-right text-amber-200">
              {formatVnd(summary.data.pending_cash)}
            </dd>
            <dt className="text-ink-dim">Data status</dt>
            <dd data-testid="data-status" className="text-right text-ink">
              <Badge tone={summary.data.data_status === "FRESH" ? "up" : "down"}>
                {summary.data.data_status}
              </Badge>
            </dd>
          </dl>
        </Card>
      ) : null}

      {/* ── Positions table ─────────────────────────────────────── */}
      {summary.data ? (
        <Card title="Positions" hint="Pending vs sellable">
          {summary.data.positions.length === 0 ? (
            <p className="text-ink-muted text-xs">No positions yet.</p>
          ) : (
            <table data-testid="positions-table" className="w-full text-xs">
              <thead className="text-ink-dim">
                <tr>
                  <th className="text-left">Symbol</th>
                  <th className="text-right">Qty</th>
                  <th className="text-right">Sellable</th>
                  <th className="text-right">Pending</th>
                  <th className="text-right">Avg cost</th>
                  <th className="text-right">Market</th>
                  <th className="text-right">Unrealized PnL</th>
                </tr>
              </thead>
              <tbody>
                {summary.data.positions.map((p) => (
                  <tr key={p.symbol} className="text-ink">
                    <td>{p.symbol}</td>
                    <td className="text-right">{formatNumber(p.quantity)}</td>
                    <td className="text-right">{formatNumber(p.sellable_quantity)}</td>
                    <td className="text-right text-amber-200">
                      {formatNumber(p.pending_quantity)}
                    </td>
                    <td className="text-right">{formatVnd(p.avg_cost)}</td>
                    <td className="text-right">
                      {p.market_price ? formatVnd(p.market_price) : "—"}
                    </td>
                    <td className="text-right">
                      {p.unrealized_pnl != null ? formatVnd(p.unrealized_pnl) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      ) : null}

      {/* ── Order form ──────────────────────────────────────────── */}
      {selected ? (
        <Card title="Submit paper order" hint="Simulated — no broker contact">
          <form
            data-testid="paper-order-form"
            onSubmit={onSubmitOrder}
            className="grid grid-cols-2 lg:grid-cols-5 gap-3 text-xs"
          >
            <Field
              label="Symbol"
              testid="paper-input-symbol"
              value={symbol}
              onChange={(v) => setSymbol(v.toUpperCase())}
            />
            <SelectField
              label="Side"
              testid="paper-input-side"
              value={side}
              options={SIDES}
              onChange={(v) => setSide(v as Side)}
            />
            <SelectField
              label="Order type"
              testid="paper-input-order-type"
              value={orderType}
              options={ORDER_TYPES}
              onChange={(v) => setOrderType(v as PaperOrderType)}
            />
            <NumberField
              label="Quantity"
              testid="paper-input-quantity"
              value={quantity}
              onChange={setQuantity}
            />
            <Field
              label="Limit price (VND)"
              testid="paper-input-limit"
              value={limitPrice}
              onChange={setLimitPrice}
            />
            <div className="col-span-2 lg:col-span-5">
              <button
                type="submit"
                data-testid="paper-submit"
                disabled={actions.busy}
                className="rounded border border-accent/60 bg-accent/10 px-3 py-1 text-accent hover:bg-accent/20 disabled:opacity-50"
              >
                {actions.busy ? "Submitting…" : "Submit paper order"}
              </button>
              <span className="ml-3 text-ink-dim">
                Simulated — no real broker order will be placed.
              </span>
            </div>
          </form>
          {actions.lastResult ? (
            <div
              data-testid="paper-order-result"
              className="mt-3 rounded border border-border bg-bg px-3 py-2 text-xs"
            >
              <Badge tone={actions.lastResult.rejection_reason ? "down" : "up"}>
                {actions.lastResult.order.status}
              </Badge>
              {actions.lastResult.rejection_reason ? (
                <span className="ml-2 text-accent-down">{actions.lastResult.rejection_reason}</span>
              ) : actions.lastResult.fill ? (
                <span className="ml-2 text-ink">
                  Filled {actions.lastResult.fill.quantity} {actions.lastResult.order.symbol} @{" "}
                  {formatVnd(actions.lastResult.fill.fill_price)} · net{" "}
                  {formatVnd(actions.lastResult.fill.net_cash_impact)}
                </span>
              ) : null}
            </div>
          ) : null}
        </Card>
      ) : null}

      {/* ── Orders + fills ─────────────────────────────────────── */}
      {selected ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Card title="Orders" hint="Recent paper orders">
            {ordersFills.orders.length === 0 ? (
              <p className="text-ink-muted text-xs">None yet.</p>
            ) : (
              <table data-testid="orders-table" className="w-full text-xs">
                <thead className="text-ink-dim">
                  <tr>
                    <th>When</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {ordersFills.orders.slice(0, 15).map((o) => (
                    <tr key={o.id} className="text-ink">
                      <td>{o.created_at?.slice(0, 16)}</td>
                      <td>{o.symbol}</td>
                      <td>{o.side}</td>
                      <td className="text-right">{o.quantity}</td>
                      <td>{o.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
          <Card title="Fills" hint="Settled paper fills">
            {ordersFills.fills.length === 0 ? (
              <p className="text-ink-muted text-xs">None yet.</p>
            ) : (
              <table data-testid="fills-table" className="w-full text-xs">
                <thead className="text-ink-dim">
                  <tr>
                    <th>When</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Price</th>
                    <th>Net cash</th>
                  </tr>
                </thead>
                <tbody>
                  {ordersFills.fills.slice(0, 15).map((f) => (
                    <tr key={f.id} className="text-ink">
                      <td>{f.filled_at.slice(0, 16)}</td>
                      <td>{f.symbol}</td>
                      <td>{f.side}</td>
                      <td className="text-right">{f.quantity}</td>
                      <td className="text-right">{formatVnd(f.fill_price)}</td>
                      <td className="text-right">{formatVnd(f.net_cash_impact)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      ) : null}

      {/* ── Equity curve ────────────────────────────────────────── */}
      {selected ? (
        <Card title="Equity curve" hint="Total equity over time">
          {equityChartData.length === 0 ? (
            <p className="text-ink-muted text-xs">No snapshots yet.</p>
          ) : (
            <div data-testid="equity-chart" style={{ width: "100%", height: 240 }}>
              <ResponsiveContainer>
                <LineChart data={equityChartData}>
                  <CartesianGrid stroke="#222" strokeDasharray="3 3" />
                  <XAxis dataKey="ts" hide />
                  <YAxis tickFormatter={(v) => formatVnd(v, { compact: true })} />
                  <Tooltip
                    formatter={(v: number) => formatVnd(v)}
                    labelStyle={{ color: "#999" }}
                    contentStyle={{ background: "#111", border: "1px solid #333" }}
                  />
                  <Line type="monotone" dataKey="equity" stroke="#4ade80" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      ) : null}
    </div>
  );
}

function Field({
  label,
  testid,
  value,
  onChange,
}: {
  label: string;
  testid: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-ink-dim">{label}</span>
      <input
        data-testid={testid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-border bg-bg px-2 py-1 text-ink"
      />
    </label>
  );
}

function NumberField({
  label,
  testid,
  value,
  onChange,
}: {
  label: string;
  testid: string;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-ink-dim">{label}</span>
      <input
        data-testid={testid}
        type="number"
        min={1}
        step={100}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="rounded border border-border bg-bg px-2 py-1 text-ink"
      />
    </label>
  );
}

function SelectField({
  label,
  testid,
  value,
  options,
  onChange,
}: {
  label: string;
  testid: string;
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-ink-dim">{label}</span>
      <select
        data-testid={testid}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-border bg-bg px-2 py-1 text-ink"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function KpiBlock({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "warning";
}) {
  const cls =
    tone === "warning"
      ? "rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2"
      : "rounded border border-border bg-bg-panel px-3 py-2";
  return (
    <div className={cls}>
      <p className="text-xs text-ink-dim">{label}</p>
      <p className="text-sm text-ink font-semibold">{value}</p>
      {sub ? <p className="text-[10px] text-ink-dim mt-0.5">{sub}</p> : null}
    </div>
  );
}

"""Performance metrics for backtest results."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_metrics(
    equity_curve: pd.DataFrame,
    trade_log: list | pd.DataFrame,
    initial_capital: float,
    annual_trading_days: int = 252,
    risk_free_rate: float = 0.04,  # approximate Vietnam risk-free rate
) -> dict:
    """
    Compute comprehensive performance metrics from an equity curve and trade log.

    Args:
        equity_curve: DataFrame indexed by date with an 'equity' column.
        trade_log: List of Trade objects or DataFrame with trade records.
        initial_capital: Starting capital in VND.
        annual_trading_days: Trading days per year (252 for Vietnam).
        risk_free_rate: Annual risk-free rate for Sharpe/Sortino calculation.

    Returns:
        dict of metric_name → value.
    """
    if isinstance(trade_log, list):
        trades_df = pd.DataFrame([t.to_dict() if hasattr(t, "to_dict") else t for t in trade_log])
    else:
        trades_df = trade_log.copy() if not trade_log.empty else pd.DataFrame()

    metrics: dict = {}

    if equity_curve.empty:
        return _empty_metrics()

    equity = equity_curve["equity"]
    returns = equity.pct_change().fillna(0.0)

    # ── Return metrics ────────────────────────────────────────────────────
    final_equity = float(equity.iloc[-1])
    total_return = (final_equity - initial_capital) / initial_capital
    metrics["total_return"] = total_return
    metrics["total_return_pct"] = total_return * 100

    n_days = len(equity_curve)
    n_years = n_days / annual_trading_days
    if n_years > 0 and final_equity > 0:
        cagr = (final_equity / initial_capital) ** (1 / n_years) - 1
    else:
        cagr = 0.0
    metrics["cagr"] = cagr
    metrics["cagr_pct"] = cagr * 100

    # ── Risk metrics ──────────────────────────────────────────────────────
    ann_vol = returns.std() * np.sqrt(annual_trading_days)
    metrics["annualized_volatility"] = ann_vol
    metrics["annualized_volatility_pct"] = ann_vol * 100

    # Max drawdown
    rolling_max = equity.cummax()
    drawdown = (equity - rolling_max) / rolling_max
    max_dd = float(drawdown.min())
    metrics["max_drawdown"] = max_dd
    metrics["max_drawdown_pct"] = max_dd * 100

    # Drawdown duration (longest consecutive drawdown in trading days)
    in_dd = drawdown < 0
    dd_groups = (in_dd != in_dd.shift()).cumsum()
    dd_lengths = in_dd.groupby(dd_groups).sum()
    metrics["max_drawdown_duration_days"] = int(dd_lengths.max()) if len(dd_lengths) > 0 else 0

    # ── Risk-adjusted metrics ─────────────────────────────────────────────
    daily_rf = risk_free_rate / annual_trading_days
    excess_returns = returns - daily_rf

    if ann_vol > 0:
        sharpe = (excess_returns.mean() * annual_trading_days) / ann_vol
    else:
        sharpe = 0.0
    metrics["sharpe"] = sharpe

    # Sortino: semi-deviation over ALL observations (standard definition).
    # Positive excess returns are floored at zero before squaring — not filtered out.
    # Using the subset-std approach (as done previously) inflates Sortino 1.5-3x.
    downside = np.minimum(excess_returns.values, 0.0)
    downside_variance = np.mean(downside ** 2)
    downside_std_ann = np.sqrt(downside_variance * annual_trading_days)
    sortino = (excess_returns.mean() * annual_trading_days) / downside_std_ann if downside_std_ann > 0 else float("inf")
    metrics["sortino"] = sortino

    # Calmar: CAGR / |max_drawdown|
    if max_dd != 0:
        calmar = cagr / abs(max_dd)
    else:
        calmar = float("inf") if cagr > 0 else 0.0
    metrics["calmar"] = calmar

    # ── Exposure time ─────────────────────────────────────────────────────
    if "position_value" in equity_curve.columns:
        exposure = (equity_curve["position_value"] > 0).mean()
        metrics["exposure_time"] = float(exposure)
        metrics["exposure_time_pct"] = float(exposure) * 100
    else:
        metrics["exposure_time"] = float("nan")
        metrics["exposure_time_pct"] = float("nan")

    # ── Trade statistics ──────────────────────────────────────────────────
    if not trades_df.empty and "net_pnl" in trades_df.columns:
        metrics["n_trades"] = len(trades_df)

        winning = trades_df[trades_df["net_pnl"] > 0]
        losing = trades_df[trades_df["net_pnl"] <= 0]

        win_rate = len(winning) / len(trades_df) if len(trades_df) > 0 else 0.0
        metrics["win_rate"] = win_rate
        metrics["win_rate_pct"] = win_rate * 100

        avg_win = float(winning["net_pnl"].mean()) if len(winning) > 0 else 0.0
        avg_loss = float(losing["net_pnl"].mean()) if len(losing) > 0 else 0.0
        metrics["avg_win"] = avg_win
        metrics["avg_loss"] = avg_loss

        total_wins = float(winning["net_pnl"].sum()) if len(winning) > 0 else 0.0
        total_losses = float(losing["net_pnl"].sum()) if len(losing) > 0 else 0.0
        metrics["profit_factor"] = abs(total_wins / total_losses) if total_losses != 0 else float("inf")

        # Expectancy per trade
        metrics["expectancy"] = float(trades_df["net_pnl"].mean())

        if "holding_days" in trades_df.columns:
            metrics["avg_holding_days"] = float(trades_df["holding_days"].mean())

        if "return_pct" in trades_df.columns:
            metrics["avg_trade_return_pct"] = float(trades_df["return_pct"].mean() * 100)

        # Turnover (rough: sum of notional traded / average equity)
        if "entry_price" in trades_df.columns and "quantity" in trades_df.columns:
            total_notional = (trades_df["entry_price"] * trades_df["quantity"]).sum() * 2
            avg_equity = equity.mean()
            metrics["turnover"] = float(total_notional / avg_equity / n_years) if n_years > 0 else 0.0
    else:
        metrics["n_trades"] = 0
        metrics["win_rate"] = 0.0
        metrics["profit_factor"] = 0.0

    # ── Final equity ──────────────────────────────────────────────────────
    metrics["initial_capital"] = initial_capital
    metrics["final_equity"] = final_equity
    metrics["n_trading_days"] = n_days

    return metrics


def _empty_metrics() -> dict:
    keys = [
        "total_return", "total_return_pct", "cagr", "cagr_pct",
        "annualized_volatility", "annualized_volatility_pct",
        "max_drawdown", "max_drawdown_pct", "max_drawdown_duration_days",
        "sharpe", "sortino", "calmar",
        "exposure_time", "exposure_time_pct",
        "n_trades", "win_rate", "win_rate_pct",
        "avg_win", "avg_loss", "profit_factor", "expectancy",
        "avg_holding_days", "avg_trade_return_pct",
        "initial_capital", "final_equity", "n_trading_days",
    ]
    return {k: 0.0 for k in keys}


def format_metrics_table(metrics: dict) -> str:
    """Format metrics as a human-readable table string."""
    lines = ["=" * 50, "BACKTEST PERFORMANCE METRICS", "=" * 50]

    sections = {
        "Returns": ["total_return_pct", "cagr_pct"],
        "Risk": ["annualized_volatility_pct", "max_drawdown_pct", "max_drawdown_duration_days"],
        "Risk-Adjusted": ["sharpe", "sortino", "calmar"],
        "Trades": ["n_trades", "win_rate_pct", "avg_win", "avg_loss", "profit_factor",
                   "expectancy", "avg_holding_days"],
        "Portfolio": ["initial_capital", "final_equity", "exposure_time_pct"],
    }

    fmt_map = {
        "total_return_pct": ("Total Return", "{:.2f}%"),
        "cagr_pct": ("CAGR", "{:.2f}%"),
        "annualized_volatility_pct": ("Ann. Volatility", "{:.2f}%"),
        "max_drawdown_pct": ("Max Drawdown", "{:.2f}%"),
        "max_drawdown_duration_days": ("Max DD Duration", "{:.0f} days"),
        "sharpe": ("Sharpe Ratio", "{:.3f}"),
        "sortino": ("Sortino Ratio", "{:.3f}"),
        "calmar": ("Calmar Ratio", "{:.3f}"),
        "n_trades": ("# Trades", "{:.0f}"),
        "win_rate_pct": ("Win Rate", "{:.1f}%"),
        "avg_win": ("Avg Win (VND)", "{:,.0f}"),
        "avg_loss": ("Avg Loss (VND)", "{:,.0f}"),
        "profit_factor": ("Profit Factor", "{:.3f}"),
        "expectancy": ("Expectancy (VND)", "{:,.0f}"),
        "avg_holding_days": ("Avg Hold Days", "{:.1f}"),
        "initial_capital": ("Initial Capital", "{:,.0f}"),
        "final_equity": ("Final Equity", "{:,.0f}"),
        "exposure_time_pct": ("Exposure Time", "{:.1f}%"),
    }

    for section, keys in sections.items():
        lines.append(f"\n  {section}")
        lines.append("  " + "-" * 40)
        for key in keys:
            if key in metrics and key in fmt_map:
                label, fmt = fmt_map[key]
                val = metrics[key]
                try:
                    val_str = fmt.format(val)
                except (ValueError, TypeError):
                    val_str = str(val)
                lines.append(f"  {label:<30} {val_str}")

    lines.append("=" * 50)
    return "\n".join(lines)

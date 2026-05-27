"""Backtest report generation: console, CSV, and HTML."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from .engine import BacktestResult
from .metrics import format_metrics_table


def print_report(result: BacktestResult) -> None:
    """Print a full backtest report to stdout."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        console = Console()
        header = (
            f"Strategy: {result.strategy_name}  |  Symbol: {result.symbol}\n"
            f"Period: {result.start_date} → {result.end_date}  |  "
            f"Initial Capital: {result.initial_capital:,.0f} VND"
        )
        console.print(Panel(header, title="[bold blue]Backtest Report[/bold blue]"))
        console.print(format_metrics_table(result.metrics))
    except ImportError:
        print(f"\n{'='*60}")
        print(f"Strategy: {result.strategy_name} | Symbol: {result.symbol}")
        print(f"Period: {result.start_date} → {result.end_date}")
        print(format_metrics_table(result.metrics))


def save_csv_report(result: BacktestResult, output_dir: str | Path = "reports") -> dict[str, Path]:
    """Save equity curve and trade log as CSV files. Returns paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{result.strategy_name}_{result.symbol}_{ts}"

    paths: dict[str, Path] = {}

    if not result.equity_curve.empty:
        eq_path = output_dir / f"{prefix}_equity.csv"
        result.equity_curve.to_csv(eq_path)
        paths["equity_curve"] = eq_path

    if not result.trade_log.empty:
        tl_path = output_dir / f"{prefix}_trades.csv"
        result.trade_log.to_csv(tl_path, index=False)
        paths["trade_log"] = tl_path

    # Metrics summary
    metrics_path = output_dir / f"{prefix}_metrics.csv"
    pd.Series(result.metrics).to_csv(metrics_path, header=["value"])
    paths["metrics"] = metrics_path

    return paths


def save_html_report(result: BacktestResult, output_dir: str | Path = "reports") -> Path:
    """Generate an HTML report with an equity curve chart."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        raise ImportError("plotly is required for HTML reports. Install with: pip install plotly")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fig = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=["Equity Curve", "Drawdown (%)"],
        row_heights=[0.7, 0.3],
        shared_xaxes=True,
        vertical_spacing=0.05,
    )

    eq = result.equity_curve

    # Equity curve
    fig.add_trace(
        go.Scatter(
            x=eq.index,
            y=eq["equity"],
            name="Equity",
            line=dict(color="royalblue", width=2),
        ),
        row=1,
        col=1,
    )

    # Drawdown
    if "drawdown" in eq.columns:
        fig.add_trace(
            go.Scatter(
                x=eq.index,
                y=eq["drawdown"] * 100,
                name="Drawdown %",
                fill="tozeroy",
                line=dict(color="red"),
                fillcolor="rgba(255,0,0,0.2)",
            ),
            row=2,
            col=1,
        )

    metrics = result.metrics
    title = (
        f"{result.strategy_name} | {result.symbol} | "
        f"{result.start_date} → {result.end_date}<br>"
        f"<sup>CAGR: {metrics.get('cagr_pct', 0):.1f}%  |  "
        f"Sharpe: {metrics.get('sharpe', 0):.2f}  |  "
        f"Max DD: {metrics.get('max_drawdown_pct', 0):.1f}%  |  "
        f"Win Rate: {metrics.get('win_rate_pct', 0):.1f}%</sup>"
    )

    fig.update_layout(
        title=title,
        height=700,
        showlegend=True,
        yaxis_title="Equity (VND)",
        yaxis2_title="Drawdown (%)",
        template="plotly_white",
    )

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = output_dir / f"{result.strategy_name}_{result.symbol}_{ts}.html"
    fig.write_html(str(html_path))
    return html_path

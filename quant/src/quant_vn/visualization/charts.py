"""Visualization: equity curve, drawdown, monthly returns."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd


def plot_equity_curve(
    equity_df: pd.DataFrame,
    title: str = "Equity Curve",
    benchmark_df: Optional[pd.DataFrame] = None,
    output_path: Optional[str | Path] = None,
    show: bool = True,
) -> None:
    """Plot equity curve with optional benchmark comparison."""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        _matplotlib_equity_curve(equity_df, title, output_path, show)
        return

    rows = 3 if "drawdown" in equity_df.columns else 2
    row_heights = [0.6, 0.2, 0.2] if rows == 3 else [0.7, 0.3]
    subplot_titles = ["Equity", "Daily Returns"]
    if rows == 3:
        subplot_titles.append("Drawdown (%)")

    fig = make_subplots(
        rows=rows,
        cols=1,
        subplot_titles=subplot_titles,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=row_heights,
    )

    fig.add_trace(
        go.Scatter(x=equity_df.index, y=equity_df["equity"], name="Strategy", line=dict(color="royalblue", width=2)),
        row=1, col=1,
    )

    if benchmark_df is not None and "equity" in benchmark_df.columns:
        scale = equity_df["equity"].iloc[0] / benchmark_df["equity"].iloc[0]
        fig.add_trace(
            go.Scatter(
                x=benchmark_df.index,
                y=benchmark_df["equity"] * scale,
                name="Benchmark (scaled)",
                line=dict(color="gray", width=1.5, dash="dash"),
            ),
            row=1, col=1,
        )

    if "returns" in equity_df.columns:
        colors = ["green" if r >= 0 else "red" for r in equity_df["returns"]]
        fig.add_trace(
            go.Bar(x=equity_df.index, y=equity_df["returns"] * 100, name="Daily Ret %", marker_color=colors),
            row=2, col=1,
        )

    if rows == 3 and "drawdown" in equity_df.columns:
        fig.add_trace(
            go.Scatter(
                x=equity_df.index,
                y=equity_df["drawdown"] * 100,
                name="Drawdown %",
                fill="tozeroy",
                line=dict(color="red"),
                fillcolor="rgba(255,0,0,0.2)",
            ),
            row=3, col=1,
        )

    fig.update_layout(
        title=title,
        height=700,
        showlegend=True,
        template="plotly_white",
        yaxis_title="Equity (VND)",
    )

    if output_path:
        fig.write_html(str(output_path))
    if show:
        fig.show()


def _matplotlib_equity_curve(equity_df, title, output_path, show):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("Neither plotly nor matplotlib found. Install one to plot charts.")
        return

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    axes[0].plot(equity_df.index, equity_df["equity"], label="Equity", color="royalblue")
    axes[0].set_title(title)
    axes[0].set_ylabel("Equity (VND)")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    if "drawdown" in equity_df.columns:
        axes[1].fill_between(equity_df.index, equity_df["drawdown"] * 100, 0, color="red", alpha=0.3)
        axes[1].set_ylabel("Drawdown (%)")
        axes[1].grid(alpha=0.3)

    plt.tight_layout()
    if output_path:
        plt.savefig(str(output_path), dpi=150, bbox_inches="tight")
    if show:
        plt.show()
    plt.close()


def plot_monthly_returns_heatmap(
    equity_df: pd.DataFrame,
    title: str = "Monthly Returns Heatmap",
    output_path: Optional[str | Path] = None,
    show: bool = True,
) -> None:
    """Plot a monthly returns heatmap."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("plotly required for heatmap. Install: pip install plotly")
        return

    monthly = equity_df["equity"].resample("ME").last().pct_change() * 100
    monthly.name = "returns"
    df = monthly.to_frame()
    df["year"] = df.index.year
    df["month"] = df.index.month

    pivot = df.pivot(index="year", columns="month", values="returns")
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    z = pivot.values.tolist()
    y = [str(yr) for yr in pivot.index]
    x = [month_names[m - 1] for m in pivot.columns]

    fig = go.Figure(data=go.Heatmap(
        z=z,
        x=x,
        y=y,
        colorscale="RdYlGn",
        zmid=0,
        text=[[f"{v:.1f}%" if v == v else "" for v in row] for row in z],
        texttemplate="%{text}",
    ))
    fig.update_layout(title=title, template="plotly_white")

    if output_path:
        fig.write_html(str(output_path))
    if show:
        fig.show()

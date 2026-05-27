"""Static HTML dashboard rendering."""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

import pandas as pd

from .analysis import DashboardSignal, analyze_universe


def save_dashboard(
    price_map: dict[str, pd.DataFrame],
    output_path: str | Path,
    start: str,
    end: str,
) -> Path:
    """Analyze prices and write a static dashboard HTML file."""
    signals = analyze_universe(price_map)
    html_text = build_dashboard_html(signals, price_map, start=start, end=end)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8")
    return path


def build_dashboard_html(
    signals: list[DashboardSignal],
    price_map: dict[str, pd.DataFrame],
    start: str,
    end: str,
) -> str:
    """Build static HTML for dashboard signals and price charts."""
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    table_rows = "\n".join(_signal_row(signal) for signal in signals)
    detail_cards = "\n".join(_detail_card(signal) for signal in signals)
    charts = "\n".join(_chart_block(signal.symbol, price_map.get(signal.symbol)) for signal in signals)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>quant-vn Trading Dashboard</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #637083;
      --line: #d9dee7;
      --buy: #0f7b5c;
      --watch: #956b00;
      --avoid: #a23b3b;
      --accent: #22577a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
    }}
    header {{
      padding: 24px 32px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin: 28px 0 12px; font-size: 18px; letter-spacing: 0; }}
    h3 {{ margin: 0 0 10px; font-size: 15px; letter-spacing: 0; }}
    main {{ padding: 24px 32px 40px; }}
    .meta {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .notice {{
      margin-top: 12px;
      max-width: 960px;
      color: #4b5563;
      font-size: 13px;
      line-height: 1.5;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      font-size: 13px;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }}
    th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) {{
      text-align: left;
    }}
    th {{ color: var(--muted); font-weight: 600; background: #fbfcfd; }}
    .badge {{
      display: inline-block;
      min-width: 92px;
      padding: 4px 8px;
      border-radius: 4px;
      color: white;
      font-weight: 650;
      text-align: center;
    }}
    .strong-buy, .buy {{ background: var(--buy); }}
    .hold-watch {{ background: var(--watch); }}
    .reduce-avoid {{ background: var(--avoid); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 14px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 14px;
    }}
    .card ul {{ margin: 8px 0 0 18px; padding: 0; }}
    .card li {{ margin: 5px 0; color: #344054; font-size: 13px; line-height: 1.4; }}
    .chart {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      margin-bottom: 14px;
      min-height: 420px;
    }}
    .empty {{
      padding: 24px;
      background: var(--panel);
      border: 1px solid var(--line);
      color: var(--muted);
    }}
    @media (max-width: 760px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      .table-wrap {{ overflow-x: auto; }}
      th, td {{ padding: 8px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>quant-vn Trading Dashboard</h1>
    <div class="meta">Universe: {len(signals)} symbols | Range: {html.escape(start)} to {html.escape(end)} | Generated: {generated_at}</div>
    <div class="notice">Research signals only. Recommendations are based on technical indicators and local data quality; they are not financial advice and do not guarantee trading outcomes.</div>
  </header>
  <main>
    <h2>Recommendation Summary</h2>
    {_summary_table(table_rows)}
    <h2>Signal Notes</h2>
    <section class="grid">{detail_cards or '<div class="empty">No symbols available.</div>'}</section>
    <h2>Charts</h2>
    <section>{charts or '<div class="empty">No chart data available.</div>'}</section>
  </main>
</body>
</html>
"""


def _summary_table(rows: str) -> str:
    if not rows:
        return '<div class="empty">No signals generated. Ingest data first.</div>'
    return f"""<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Recommendation</th>
        <th>Score</th>
        <th>Confidence</th>
        <th>Close</th>
        <th>RSI14</th>
        <th>SMA20</th>
        <th>SMA50</th>
        <th>Vol Ratio</th>
        <th>ATR%</th>
        <th>20D%</th>
        <th>60D%</th>
        <th>DD%</th>
        <th>Date</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def _signal_row(signal: DashboardSignal) -> str:
    badge_class = signal.label.lower().replace(" / ", "-").replace(" ", "-")
    return f"""<tr>
  <td><strong>{html.escape(signal.symbol)}</strong></td>
  <td><span class="badge {badge_class}">{html.escape(signal.label)}</span></td>
  <td>{signal.score}</td>
  <td>{html.escape(signal.confidence)}</td>
  <td>{_fmt(signal.close)}</td>
  <td>{_fmt(signal.rsi14)}</td>
  <td>{_fmt(signal.sma20)}</td>
  <td>{_fmt(signal.sma50)}</td>
  <td>{_fmt(signal.volume_ratio20)}</td>
  <td>{_fmt(signal.atr_pct14)}</td>
  <td>{_fmt(signal.return_20d_pct)}</td>
  <td>{_fmt(signal.return_60d_pct)}</td>
  <td>{_fmt(signal.drawdown_pct)}</td>
  <td>{html.escape(signal.last_date)}</td>
</tr>"""


def _detail_card(signal: DashboardSignal) -> str:
    reasons = "".join(f"<li>{html.escape(item)}</li>" for item in signal.reasons)
    risks = "".join(f"<li>{html.escape(item)}</li>" for item in signal.risks)
    return f"""<article class="card">
  <h3>{html.escape(signal.symbol)} - {html.escape(signal.label)} ({signal.score})</h3>
  <strong>Reasons</strong>
  <ul>{reasons}</ul>
  <strong>Risks</strong>
  <ul>{risks}</ul>
</article>"""


def _chart_block(symbol: str, prices: pd.DataFrame | None) -> str:
    if prices is None or prices.empty:
        return ""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return f'<div class="chart"><strong>{html.escape(symbol)}</strong>: plotly is not installed.</div>'

    df = prices.copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    df["sma20"] = df["close"].rolling(20, min_periods=20).mean()
    df["sma50"] = df["close"].rolling(50, min_periods=50).mean()

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.05,
    )
    fig.add_trace(go.Scatter(x=df.index, y=df["close"], name="Close", line=dict(color="#22577a", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["sma20"], name="SMA20", line=dict(color="#0f7b5c", width=1.5)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df["sma50"], name="SMA50", line=dict(color="#956b00", width=1.5)), row=1, col=1)
    if "volume" in df.columns:
        fig.add_trace(go.Bar(x=df.index, y=df["volume"], name="Volume", marker_color="#9aa6b2"), row=2, col=1)
    fig.update_layout(
        title=symbol,
        template="plotly_white",
        height=410,
        margin=dict(l=42, r=20, t=52, b=34),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    div = fig.to_html(full_html=False, include_plotlyjs="cdn")
    return f'<div class="chart">{div}</div>'


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}"

"""
quant-vn CLI — command line interface for the quant trading research platform.

Usage:
    quant-vn --help
    quant-vn db-init
    quant-vn ingest --provider csv --path data/raw/FPT.csv
    quant-vn validate-data --symbol FPT
    quant-vn backtest --strategy ma_cross --symbol FPT --start 2020-01-01 --end 2024-12-31
    quant-vn sweep --strategy ma_cross --symbol FPT
    quant-vn report --run-id latest
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="quant-vn",
    help="Personal quant trading research for Vietnam stock market.",
    add_completion=False,
)
console = Console()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("quant_vn")


def _get_db():
    from .config.settings import settings
    from .data.storage import Database
    db = Database(url=settings.database_url)
    db.init_db()
    return db


def _get_strategy(name: str, params_str: Optional[str] = None):
    """Resolve strategy by name and optional JSON params string."""
    import json
    from .strategies.buy_and_hold import BuyAndHoldStrategy
    from .strategies.moving_average_cross import MovingAverageCrossStrategy, MACrossParams
    from .strategies.rsi_mean_reversion import RSIMeanReversionStrategy, RSIMeanReversionParams
    from .strategies.breakout import BreakoutStrategy, BreakoutParams

    params_dict = json.loads(params_str) if params_str else {}

    registry = {
        "buy_and_hold": lambda: BuyAndHoldStrategy(),
        "ma_cross": lambda: MovingAverageCrossStrategy(MACrossParams(**params_dict)),
        "rsi_mean_reversion": lambda: RSIMeanReversionStrategy(RSIMeanReversionParams(**params_dict)),
        "breakout": lambda: BreakoutStrategy(BreakoutParams(**params_dict)),
    }

    key = name.lower().replace("-", "_")
    if key not in registry:
        console.print(f"[red]Unknown strategy: {name}[/red]")
        console.print(f"Available: {', '.join(registry.keys())}")
        raise typer.Exit(1)

    return registry[key]()


# ─── db-init ──────────────────────────────────────────────────────────────────

@app.command("db-init")
def db_init():
    """Initialise the SQLite database (creates tables if they don't exist)."""
    from .config.settings import settings
    from .data.storage import Database
    db = Database(url=settings.database_url)
    db.init_db()
    console.print(f"[green]✓[/green] Database initialised at: {settings.database_url}")


# ─── ingest ────────────────────────────────────────────────────────────────────

@app.command("ingest")
def ingest(
    provider: str = typer.Option("csv", help="Data provider: csv | vnstock"),
    path: Optional[str] = typer.Option(None, help="Path to CSV file or directory"),
    symbol: Optional[str] = typer.Option(None, help="Symbol to fetch (for vnstock provider)"),
    start: str = typer.Option("2015-01-01", help="Start date YYYY-MM-DD"),
    end: str = typer.Option("2025-12-31", help="End date YYYY-MM-DD"),
    exchange: str = typer.Option("HOSE", help="Exchange: HOSE | HNX | UPCOM"),
    adjusted: bool = typer.Option(False, help="Flag data as adjusted prices"),
):
    """Ingest OHLCV data into the local database."""
    from .data.ingestion import IngestionPipeline
    from .data.validation import print_quality_report

    db = _get_db()

    if provider == "csv":
        if not path:
            console.print("[red]--path is required for CSV provider[/red]")
            raise typer.Exit(1)
        from .data.providers.csv_provider import CsvProvider
        p = CsvProvider(path)
    elif provider == "vnstock":
        from .data.providers.vnstock_provider import VnstockProvider
        p = VnstockProvider()
    else:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        raise typer.Exit(1)

    pipeline = IngestionPipeline(provider=p, db=db)

    if symbol:
        symbols = [symbol.upper()]
    else:
        symbols = p.get_symbols()
        if not symbols and path:
            symbols = [Path(path).stem.upper()]

    if not symbols:
        console.print("[yellow]No symbols found. Use --symbol or ensure CSV filenames match ticker names.[/yellow]")
        raise typer.Exit(1)

    console.print(f"Ingesting {len(symbols)} symbol(s) via {provider}...")

    for sym in symbols:
        with console.status(f"  [cyan]{sym}[/cyan]..."):
            report = pipeline.ingest(sym, start, end, exchange=exchange, is_adjusted=adjusted)
        color = "green" if not report.has_errors else "yellow"
        console.print(
            f"  [{color}]✓[/{color}] {sym}: {report.total_rows} rows, "
            f"{len(report.issues)} issues"
        )
        if report.has_errors:
            print_quality_report(report)


# ─── validate-data ─────────────────────────────────────────────────────────────

@app.command("validate-data")
def validate_data(
    symbol: str = typer.Argument(..., help="Ticker symbol e.g. FPT"),
    start: str = typer.Option("2000-01-01", help="Start date"),
    end: str = typer.Option("2099-12-31", help="End date"),
):
    """Run data quality validation and print a report."""
    from .data.storage import PriceRepository
    from .data.validation import validate_ohlcv, print_quality_report

    db = _get_db()
    repo = PriceRepository(db)

    prices = repo.get_ohlcv(symbol.upper(), start, end)
    if prices.empty:
        console.print(f"[yellow]No data found for {symbol}. Run 'quant-vn ingest' first.[/yellow]")
        raise typer.Exit(1)

    df = prices.reset_index()
    report = validate_ohlcv(df, symbol=symbol.upper())
    print_quality_report(report)


# ─── backtest ──────────────────────────────────────────────────────────────────

@app.command("backtest")
def backtest(
    strategy: str = typer.Option(..., "--strategy", "-s", help="Strategy name"),
    symbol: str = typer.Option(..., "--symbol", help="Ticker symbol"),
    start: str = typer.Option("2020-01-01", help="Start date"),
    end: str = typer.Option("2025-12-31", help="End date"),
    capital: float = typer.Option(100_000_000, help="Initial capital (VND)"),
    params_json: Optional[str] = typer.Option(None, "--params", help='JSON strategy params e.g. \'{"fast_window": 10}\''),
    html: bool = typer.Option(False, help="Generate HTML report"),
    csv: bool = typer.Option(True, help="Save CSV results"),
    universe: Optional[str] = typer.Option(None, "--universe", help="Universe name (overrides --symbol)"),
):
    """Run a backtest for a strategy on one or more symbols."""
    from .backtest.engine import BacktestEngine
    from .backtest.reports import print_report, save_csv_report, save_html_report
    from .config.settings import settings
    from .data.storage import PriceRepository
    from .market.costs import TransactionCosts
    from .market.universe import get_universe

    db = _get_db()
    repo = PriceRepository(db)

    costs = TransactionCosts(
        commission_rate=settings.commission_rate,
        sell_tax_rate=settings.sell_tax_rate,
        slippage_bps=settings.slippage_bps,
    )
    engine = BacktestEngine(costs=costs, initial_capital=capital)

    symbols = get_universe(universe) if universe else [symbol.upper()]

    strat = _get_strategy(strategy, params_json)
    console.print(f"Running [bold]{strat.describe()}[/bold] on {', '.join(symbols)} | {start} → {end}")

    all_results = []
    for sym in symbols:
        prices = repo.get_ohlcv(sym, start, end)
        if prices.empty:
            console.print(f"  [yellow]No data for {sym}. Skipping.[/yellow]")
            continue

        with console.status(f"  Backtesting {sym}..."):
            result = engine.run(strat, prices, symbol=sym)

        all_results.append(result)
        print_report(result)

        if csv:
            paths = save_csv_report(result, output_dir=settings.reports_dir_path())
            for name, p in paths.items():
                console.print(f"    [dim]Saved {name}: {p}[/dim]")

        if html:
            html_path = save_html_report(result, output_dir=settings.reports_dir_path())
            console.print(f"    [dim]HTML report: {html_path}[/dim]")

    if len(all_results) > 1:
        _print_portfolio_summary(all_results)


def _print_portfolio_summary(results):
    table = Table(title="Portfolio Summary")
    table.add_column("Symbol")
    table.add_column("CAGR %", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("MaxDD %", justify="right")
    table.add_column("# Trades", justify="right")

    for r in results:
        m = r.metrics
        table.add_row(
            r.symbol,
            f"{m.get('cagr_pct', 0):.1f}",
            f"{m.get('sharpe', 0):.2f}",
            f"{m.get('max_drawdown_pct', 0):.1f}",
            str(int(m.get('n_trades', 0))),
        )
    console.print(table)


# ─── sweep ─────────────────────────────────────────────────────────────────────

@app.command("sweep")
def sweep(
    strategy: str = typer.Option(..., "--strategy", "-s", help="Strategy name"),
    symbol: str = typer.Option(..., "--symbol", help="Ticker symbol"),
    start: str = typer.Option("2018-01-01", help="Start date"),
    end: str = typer.Option("2025-12-31", help="End date"),
    capital: float = typer.Option(100_000_000, help="Initial capital"),
    top_n: int = typer.Option(10, help="Show top N results"),
):
    """Run a parameter sweep for a strategy (in-sample optimization)."""
    from .backtest.engine import BacktestEngine
    from .config.settings import settings
    from .data.storage import PriceRepository
    from .market.costs import TransactionCosts
    from .research.parameter_sweep import parameter_sweep

    db = _get_db()
    repo = PriceRepository(db)
    prices = repo.get_ohlcv(symbol.upper(), start, end)

    if prices.empty:
        console.print(f"[red]No data for {symbol}. Run ingest first.[/red]")
        raise typer.Exit(1)

    costs = TransactionCosts(
        commission_rate=settings.commission_rate,
        sell_tax_rate=settings.sell_tax_rate,
        slippage_bps=settings.slippage_bps,
    )

    key = strategy.lower().replace("-", "_")

    if key == "ma_cross":
        from .strategies.moving_average_cross import MovingAverageCrossStrategy, MACrossParams
        grid = {
            "fast_window": [5, 10, 15, 20, 30],
            "slow_window": [30, 50, 75, 100, 150, 200],
        }
        df = parameter_sweep(MovingAverageCrossStrategy, MACrossParams, grid, prices, symbol, capital, costs)

    elif key == "rsi_mean_reversion":
        from .strategies.rsi_mean_reversion import RSIMeanReversionStrategy, RSIMeanReversionParams
        grid = {
            "rsi_window": [7, 10, 14, 21],
            "oversold_threshold": [20, 25, 30, 35],
            "exit_threshold": [60, 65, 70, 75],
        }
        df = parameter_sweep(RSIMeanReversionStrategy, RSIMeanReversionParams, grid, prices, symbol, capital, costs)

    elif key == "breakout":
        from .strategies.breakout import BreakoutStrategy, BreakoutParams
        grid = {
            "lookback_window": [10, 15, 20, 30, 50],
            "trailing_stop_pct": [0.03, 0.05, 0.08, 0.10],
        }
        df = parameter_sweep(BreakoutStrategy, BreakoutParams, grid, prices, symbol, capital, costs)

    else:
        console.print(f"[red]Sweep not configured for strategy: {strategy}[/red]")
        raise typer.Exit(1)

    if df.empty:
        console.print("[yellow]No valid parameter combinations found.[/yellow]")
        return

    console.print(f"\nTop {top_n} results by Sharpe ratio:")
    console.print(df.head(top_n).to_string(index=True))

    # Save
    out_dir = settings.reports_dir_path()
    out_dir.mkdir(parents=True, exist_ok=True)
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"sweep_{strategy}_{symbol}_{ts}.csv"
    df.to_csv(out_path, index=False)
    console.print(f"\n[dim]Full results saved: {out_path}[/dim]")


# ─── report ────────────────────────────────────────────────────────────────────

@app.command("report")
def report(
    run_id: str = typer.Option("latest", help="Backtest run ID or 'latest'"),
    strategy: Optional[str] = typer.Option(None, help="Filter by strategy name"),
    symbol: Optional[str] = typer.Option(None, help="Filter by symbol"),
):
    """List backtest runs from the database."""
    from .data.storage import BacktestRepository

    db = _get_db()
    repo = BacktestRepository(db)
    df = repo.list_runs(strategy_name=strategy, symbol=symbol)

    if df.empty:
        console.print("[yellow]No backtest runs found in database.[/yellow]")
        return

    table = Table(title="Backtest Runs")
    for col in df.columns:
        table.add_column(str(col), overflow="fold")

    for _, row in df.head(20).iterrows():
        table.add_row(*[str(v) if v is not None else "" for v in row])

    console.print(table)


# ─── dashboard ─────────────────────────────────────────────────────────────────

@app.command("dashboard")
def dashboard(
    symbols: Optional[str] = typer.Option(
        None,
        "--symbols",
        help="Comma-separated symbols. If omitted, all DB symbols are used.",
    ),
    start: str = typer.Option("2023-01-01", help="Start date"),
    end: str = typer.Option("2099-12-31", help="End date"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output HTML path"),
):
    """Generate a local static HTML dashboard with technical recommendations."""
    import datetime

    from .config.settings import settings
    from .dashboard.static import save_dashboard
    from .data.storage import PriceRepository

    db = _get_db()
    repo = PriceRepository(db)

    if symbols:
        selected_symbols = [item.strip().upper() for item in symbols.split(",") if item.strip()]
    else:
        selected_symbols = repo.get_available_symbols()

    if not selected_symbols:
        console.print("[yellow]No symbols found. Run 'quant-vn ingest' first.[/yellow]")
        return

    price_map = {}
    for sym in selected_symbols:
        prices = repo.get_ohlcv(sym, start, end)
        if prices.empty:
            console.print(f"  [yellow]No data for {sym}. Skipping.[/yellow]")
            continue
        price_map[sym] = prices

    if not price_map:
        console.print("[yellow]No usable price data for dashboard.[/yellow]")
        return

    if output:
        output_path = Path(output)
    else:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = settings.reports_dir_path() / f"dashboard_{ts}.html"

    path = save_dashboard(price_map, output_path=output_path, start=start, end=end)
    console.print(f"[green]✓[/green] Dashboard written: {path}")


# ─── symbols ───────────────────────────────────────────────────────────────────

@app.command("symbols")
def symbols_cmd():
    """List all symbols available in the database."""
    from .data.storage import PriceRepository

    db = _get_db()
    repo = PriceRepository(db)
    syms = repo.get_available_symbols()

    if not syms:
        console.print("[yellow]No symbols found. Run 'quant-vn ingest' first.[/yellow]")
        return

    table = Table(title=f"Available Symbols ({len(syms)})")
    table.add_column("Symbol")
    table.add_column("First Date")
    table.add_column("Last Date")
    table.add_column("# Rows (est.)")

    for sym in syms:
        first, last = repo.get_date_range(sym)
        n_days = (last - first).days if first and last else 0
        table.add_row(sym, str(first or ""), str(last or ""), str(n_days))

    console.print(table)


if __name__ == "__main__":
    app()

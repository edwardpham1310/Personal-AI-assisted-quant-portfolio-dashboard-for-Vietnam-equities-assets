"""CLI entrypoint: quant-vn-data <command> [options]"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="quant-vn-data",
    help="Vietnam stock market data pipeline for quantitative research.",
    no_args_is_help=True,
)
console = Console()

# ── Helpers ──────────────────────────────────────────────────────────────────

def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _get_store():
    from quant_vn_data.storage.database import get_db
    from quant_vn_data.storage.sqlite_store import SQLiteStore
    db = get_db()
    return SQLiteStore(db)


def _get_raw_store():
    from quant_vn_data.config import get_settings
    from quant_vn_data.ingestion.raw_store import RawStore
    settings = get_settings()
    settings.raw_dir.mkdir(parents=True, exist_ok=True)
    return RawStore(settings.raw_dir)


def _make_ssi_provider():
    from quant_vn_data.config import get_settings
    from quant_vn_data.providers.ssi_fastconnect import SSIFastConnectProvider
    settings = get_settings()
    settings.require_ssi_credentials()
    return SSIFastConnectProvider(
        consumer_id=settings.ssi_consumer_id,
        consumer_secret=settings.ssi_consumer_secret,
        base_url=settings.ssi_base_url,
    )


# ── config ────────────────────────────────────────────────────────────────────

@app.command("config")
def config_show():
    """Show current configuration (redacts secrets)."""
    _setup_logging()
    from quant_vn_data.config import get_settings
    s = get_settings()

    table = Table(title="quant-vn-data Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("SSI_CONSUMER_ID", "***" if s.ssi_consumer_id else "(not set)")
    table.add_row("SSI_CONSUMER_SECRET", "***" if s.ssi_consumer_secret else "(not set)")
    table.add_row("SSI_BASE_URL", s.ssi_base_url)
    table.add_row("DATA_DIR", str(s.data_dir))
    table.add_row("DATABASE_URL", "sqlite:///<redacted>")
    table.add_row("DUCKDB_PATH", "<redacted>")
    table.add_row("LOG_LEVEL", s.log_level)
    table.add_row("SSI credentials ready", str(s.has_ssi_credentials()))

    console.print(table)


# ── db ────────────────────────────────────────────────────────────────────────

@app.command("db")
def db_command(
    action: str = typer.Argument("init", help="Action: init | counts"),
):
    """Database management (init, counts)."""
    _setup_logging()
    from quant_vn_data.storage.database import get_db
    from quant_vn_data.storage.sqlite_store import SQLiteStore

    if action == "init":
        db = get_db()
        console.print("[green]Database initialized.[/green]")
        store = SQLiteStore(db)
        counts = store.table_counts()
        for t, n in counts.items():
            console.print(f"  {t}: {n} rows")
    elif action == "counts":
        store = _get_store()
        counts = store.table_counts()
        for t, n in counts.items():
            console.print(f"  {t}: {n} rows")
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        raise typer.Exit(1)


# ── ingest-symbols ────────────────────────────────────────────────────────────

@app.command("ingest-symbols")
def ingest_symbols_cmd(
    provider: str = typer.Option("ssi", "--provider", "-p", help="Provider: ssi | vnstock"),
    exchange: Optional[str] = typer.Option(None, "--exchange", "-e", help="Filter by exchange (HOSE/HNX/UPCoM)"),
):
    """Ingest security symbols from the specified provider."""
    _setup_logging()
    from quant_vn_data.ingestion.ingest_symbols import ingest_symbols

    store = _get_store()
    raw_store = _get_raw_store()

    if provider == "ssi":
        p = _make_ssi_provider()
    elif provider == "vnstock":
        from quant_vn_data.providers.vnstock_provider import VnstockProvider
        p = VnstockProvider()
    else:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        raise typer.Exit(1)

    count = ingest_symbols(p, store, exchange=exchange, raw_store=raw_store)
    console.print(f"[green]Ingested/updated {count} symbols from {provider}.[/green]")


# ── ingest-ohlcv ──────────────────────────────────────────────────────────────

@app.command("ingest-ohlcv")
def ingest_ohlcv_cmd(
    provider: str = typer.Option("ssi", "--provider", "-p"),
    symbol: str = typer.Option(..., "--symbol", "-s"),
    start: str = typer.Option("2020-01-01", "--start"),
    end: str = typer.Option("2026-12-31", "--end"),
    exchange: Optional[str] = typer.Option(None, "--exchange"),
):
    """Ingest daily OHLCV for a single symbol."""
    _setup_logging()
    from quant_vn_data.ingestion.ingest_ohlcv import ingest_ohlcv

    store = _get_store()
    raw_store = _get_raw_store()

    if provider == "ssi":
        p = _make_ssi_provider()
    elif provider == "vnstock":
        from quant_vn_data.providers.vnstock_provider import VnstockProvider
        p = VnstockProvider()
    elif provider == "csv":
        console.print("[yellow]Use import-csv for CSV ingestion.[/yellow]")
        raise typer.Exit(1)
    else:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        raise typer.Exit(1)

    count = ingest_ohlcv(p, symbol, start, end, store, raw_store=raw_store, exchange=exchange)
    console.print(f"[green]Ingested {count} OHLCV rows for {symbol} from {provider}.[/green]")


# ── ingest-watchlist ──────────────────────────────────────────────────────────

@app.command("ingest-watchlist")
def ingest_watchlist_cmd(
    provider: str = typer.Option("ssi", "--provider", "-p"),
    watchlist: Optional[str] = typer.Option(None, "--watchlist", "-w", help="Path to watchlist YAML"),
    start: str = typer.Option("2020-01-01", "--start"),
    end: str = typer.Option("2026-12-31", "--end"),
):
    """Ingest OHLCV for all symbols in a watchlist."""
    _setup_logging()
    from quant_vn_data.config.loader import load_watchlist
    from quant_vn_data.ingestion.ingest_ohlcv import ingest_ohlcv

    if watchlist:
        import yaml
        wl_path = Path(watchlist)
        if not wl_path.is_file():
            console.print(f"[red]Watchlist file not found: {watchlist}[/red]")
            raise typer.Exit(1)
        cfg = yaml.safe_load(wl_path.read_text()) or {}
        symbols = cfg.get("symbols", [])
    else:
        symbols = load_watchlist()

    if not symbols:
        console.print("[red]No symbols in watchlist.[/red]")
        raise typer.Exit(1)

    store = _get_store()
    raw_store = _get_raw_store()

    if provider == "ssi":
        p = _make_ssi_provider()
    elif provider == "vnstock":
        from quant_vn_data.providers.vnstock_provider import VnstockProvider
        p = VnstockProvider()
    else:
        console.print(f"[red]Unknown provider: {provider}[/red]")
        raise typer.Exit(1)

    total = 0
    for sym in symbols:
        count = ingest_ohlcv(p, sym, start, end, store, raw_store=raw_store)
        console.print(f"  {sym}: {count} rows")
        total += count

    console.print(f"[green]Total: {total} rows for {len(symbols)} symbols.[/green]")


# ── import-csv ────────────────────────────────────────────────────────────────

@app.command("import-csv")
def import_csv_cmd(
    path: str = typer.Option(..., "--path", help="Path to CSV file"),
    symbol: str = typer.Option(..., "--symbol", "-s"),
    exchange: Optional[str] = typer.Option(None, "--exchange"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
):
    """Import OHLCV data from a local CSV file."""
    _setup_logging()
    from quant_vn_data.ingestion.ingest_ohlcv import ingest_ohlcv
    from quant_vn_data.providers.csv_provider import CSVProvider

    provider = CSVProvider(path, symbol=symbol, exchange=exchange)
    store = _get_store()
    raw_store = _get_raw_store()

    start_date = start or "2000-01-01"
    end_date = end or "2099-12-31"

    count = ingest_ohlcv(provider, symbol, start_date, end_date, store, raw_store=raw_store, exchange=exchange)
    console.print(f"[green]Imported {count} rows for {symbol} from {path}.[/green]")


# ── validate ──────────────────────────────────────────────────────────────────

@app.command("validate")
def validate_cmd(
    symbol: str = typer.Option(..., "--symbol", "-s"),
    source: Optional[str] = typer.Option(None, "--source"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
):
    """Run data quality validation for a symbol."""
    _setup_logging()
    from quant_vn_data.validation.ohlcv_checks import validate_ohlcv
    from quant_vn_data.validation.data_quality_report import generate_quality_report

    store = _get_store()
    df = store.query_ohlcv(symbol, start_date=start, end_date=end, source=source)

    if df.empty:
        console.print(f"[yellow]No data found for {symbol}.[/yellow]")
        raise typer.Exit(0)

    annotated, issues = validate_ohlcv(df)

    if not issues:
        console.print(f"[green]{symbol}: No issues found ({len(df)} rows checked).[/green]")
        return

    issues_df = _issues_to_df(issues)
    store.insert_quality_issues(issues_df)

    # Update quality_status in ohlcv_daily
    _update_quality_status(store, annotated)

    generate_quality_report(issues_df)
    console.print(f"[yellow]{len(issues)} issues found for {symbol}. Stored in database.[/yellow]")


def _issues_to_df(issues):
    import pandas as pd
    from dataclasses import asdict
    return pd.DataFrame([asdict(i) for i in issues])


def _update_quality_status(store, annotated_df):
    """Batch-update quality_status on OHLCV rows after validation."""
    updated = store.bulk_update_quality_status(annotated_df)
    if updated:
        logger.debug("Updated quality_status for %d rows", updated)


# ── reconcile ─────────────────────────────────────────────────────────────────

@app.command("reconcile")
def reconcile_cmd(
    symbol: str = typer.Option(..., "--symbol", "-s"),
    primary: str = typer.Option("ssi", "--primary"),
    secondary: str = typer.Option("vnstock", "--secondary"),
    start: Optional[str] = typer.Option(None, "--start"),
    end: Optional[str] = typer.Option(None, "--end"),
):
    """Reconcile OHLCV data between two providers for a symbol."""
    _setup_logging()
    from quant_vn_data.validation.provider_reconciliation import reconcile_providers

    store = _get_store()
    pri_df = store.query_ohlcv(symbol, start_date=start, end_date=end, source=primary)
    sec_df = store.query_ohlcv(symbol, start_date=start, end_date=end, source=secondary)

    if pri_df.empty:
        console.print(f"[yellow]No primary ({primary}) data for {symbol}.[/yellow]")
    if sec_df.empty:
        console.print(f"[yellow]No secondary ({secondary}) data for {symbol}.[/yellow]")

    recon_df = reconcile_providers(pri_df, sec_df, primary_source=primary, secondary_source=secondary)

    if recon_df.empty:
        console.print("[yellow]No reconciliation data produced.[/yellow]")
        return

    store.insert_reconciliation(recon_df)

    status_counts = recon_df["status"].value_counts().to_dict()
    table = Table(title=f"Reconciliation: {symbol} ({primary} vs {secondary})")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    for status, count in sorted(status_counts.items()):
        color = "red" if "MAJOR" in status else "yellow" if "MINOR" in status else "green"
        table.add_row(f"[{color}]{status}[/{color}]", str(count))
    console.print(table)


# ── build-liquidity ───────────────────────────────────────────────────────────

@app.command("build-liquidity")
def build_liquidity_cmd(
    symbol: Optional[str] = typer.Option(None, "--symbol", "-s"),
    all_symbols: bool = typer.Option(False, "--all", help="Build for all symbols"),
):
    """Compute and store liquidity features."""
    _setup_logging()
    from quant_vn_data.market.liquidity import build_liquidity_features

    store = _get_store()

    if all_symbols:
        symbols_df = store.query_symbols()
        symbols = symbols_df["symbol"].tolist() if not symbols_df.empty else []
    elif symbol:
        symbols = [symbol]
    else:
        console.print("[red]Provide --symbol or --all.[/red]")
        raise typer.Exit(1)

    if not symbols:
        console.print("[yellow]No symbols found.[/yellow]")
        return

    total = 0
    for sym in symbols:
        df = store.query_ohlcv(sym)
        if df.empty:
            continue
        liq_df = build_liquidity_features(df)
        if not liq_df.empty:
            n = store.upsert_liquidity(liq_df)
            total += n
            console.print(f"  {sym}: {n} liquidity rows")

    console.print(f"[green]Liquidity features built for {len(symbols)} symbols ({total} rows).[/green]")


# ── quality-report ────────────────────────────────────────────────────────────

@app.command("quality-report")
def quality_report_cmd(
    output: str = typer.Option("reports/data_quality_report.csv", "--output", "-o"),
    symbol: Optional[str] = typer.Option(None, "--symbol"),
    severity: Optional[str] = typer.Option(None, "--severity"),
):
    """Generate data quality report and write CSV."""
    _setup_logging()
    from quant_vn_data.validation.data_quality_report import generate_quality_report

    store = _get_store()
    issues_df = store.query_quality_issues(symbol=symbol, severity=severity)

    if issues_df.empty:
        console.print("[green]No data quality issues recorded.[/green]")
        return

    generate_quality_report(issues_df, output_path=output)
    console.print(f"[green]Report written to {output}.[/green]")


# ── export-duckdb ─────────────────────────────────────────────────────────────

@app.command("export-duckdb")
def export_duckdb_cmd():
    """Export all SQLite tables into DuckDB and create analytical views."""
    _setup_logging()
    from quant_vn_data.config import get_settings
    from quant_vn_data.storage.duckdb_store import DuckDBStore

    settings = get_settings()
    sqlite_path = settings.database_url.replace("sqlite:///", "")
    duckdb_store = DuckDBStore(settings.duckdb_path)
    duckdb_store.export_from_sqlite(sqlite_path)

    counts = duckdb_store.table_counts()
    table = Table(title="DuckDB Export")
    table.add_column("Table")
    table.add_column("Rows", justify="right")
    for t, n in counts.items():
        table.add_row(t, str(n))
    console.print(table)
    console.print(f"[green]DuckDB updated at {settings.duckdb_path}[/green]")


if __name__ == "__main__":
    app()

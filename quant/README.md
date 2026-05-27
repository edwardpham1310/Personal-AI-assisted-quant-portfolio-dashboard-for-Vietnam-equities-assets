# quant-vn

Personal quantitative trading research platform for the Vietnam stock market (HOSE / HNX / UPCoM).

> ⚠️ **Disclaimer**: This is a research tool, not financial advice. Backtest results do not guarantee future performance. Vietnam stock market liquidity, price limits, and corporate actions significantly affect real trading outcomes.

---

## Features

- **Data ingestion**: CSV import with flexible column mapping, optional vnstock integration
- **Data cleaning**: duplicate removal, OHLC validation, spike detection, forward-fill
- **SQLite storage**: fast local database with indexed queries
- **Indicators**: SMA, EMA, RSI, ATR, Bollinger Bands, OBV, Volume Ratio
- **4 starter strategies**: Buy & Hold, MA Crossover, RSI Mean Reversion, Breakout
- **Vectorized backtest engine**: next-open execution, no lookahead bias, T+2 awareness
- **Realistic costs**: commission 0.1% + sell tax 0.1% + 10bps slippage (configurable)
- **Performance metrics**: CAGR, Sharpe, Sortino, Calmar, max drawdown, win rate, profit factor
- **Research tools**: parameter sweep with overfitting warnings, walk-forward analysis
- **CLI**: `quant-vn ingest | backtest | sweep | report | symbols`
- **Reports**: console summary, CSV export, HTML equity curve chart

---

## Quick Start

### 1. Install

```bash
cd quant-vn
pip install -e ".[dev]"           # development install with test tools
# or
pip install -e ".[dev,vnstock]"   # include vnstock for live data
```

### 2. Initialise database

```bash
quant-vn db-init
```

### 3. Import your CSV data

Your CSV must have these columns (case-insensitive):
`date, open, high, low, close, volume`

```bash
# Single file
quant-vn ingest --provider csv --path data/raw/FPT.csv --exchange HOSE

# Directory of CSVs (one file per symbol, named SYMBOL.csv)
quant-vn ingest --provider csv --path data/raw/ --exchange HOSE
```

**Flexible column mapping**: if your CSV uses different column names, use a Python script:
```python
from quant_vn.data.providers.csv_provider import CsvProvider

provider = CsvProvider(
    path="data/raw/my_data.csv",
    column_map={
        "ngay": "date",
        "gia_dong_cua": "close",
        "khoi_luong": "volume",
        "gia_mo_cua": "open",
        "gia_cao_nhat": "high",
        "gia_thap_nhat": "low",
    }
)
```

### 4. Validate data quality

```bash
quant-vn validate-data FPT
```

### 5. Run a backtest

```bash
# MA crossover on FPT
quant-vn backtest --strategy ma_cross --symbol FPT --start 2020-01-01 --end 2024-12-31

# RSI mean reversion with custom parameters
quant-vn backtest --strategy rsi_mean_reversion --symbol HPG --params '{"rsi_window": 10, "oversold_threshold": 25}'

# All VN30 symbols
quant-vn backtest --strategy ma_cross --universe vn30

# Generate HTML report
quant-vn backtest --strategy ma_cross --symbol FPT --html
```

### 6. Parameter sweep

```bash
quant-vn sweep --strategy ma_cross --symbol FPT --top-n 10
```

> ⚠️ In-sample optimization results are shown with an overfitting warning. Use walk-forward testing to validate any parameters found.

### 7. List available symbols

```bash
quant-vn symbols
```

---

## CSV Data Format

Minimum required columns:

| Column | Description |
|--------|-------------|
| `date` | Trading date (any parseable format: `2020-01-02`, `02/01/2020`, etc.) |
| `open` | Opening price (VND) |
| `high` | Highest price of the day |
| `low` | Lowest price of the day |
| `close` | Closing price |
| `volume` | Number of shares traded |

Optional columns: `symbol`, `exchange`

**Example CSV** (`data/raw/FPT.csv`):
```csv
date,open,high,low,close,volume
2020-01-02,60000,61500,59800,61000,2500000
2020-01-03,61000,62000,60500,61800,1800000
...
```

---

## Strategy Reference

### Buy and Hold (`buy_and_hold`)
- Enters at the second bar, holds until end of period
- No parameters
- Benchmark for all other strategies

### Moving Average Crossover (`ma_cross`)
- Long when fast MA > slow MA, flat otherwise
- Parameters: `fast_window` (default 20), `slow_window` (default 50), `method` (sma/ema)
- Entry: next-open after fast MA crosses above slow MA

### RSI Mean Reversion (`rsi_mean_reversion`)
- Enter long when RSI < `oversold_threshold`
- Exit when RSI > `exit_threshold`
- Parameters: `rsi_window` (14), `oversold_threshold` (30), `exit_threshold` (70)

### Breakout (`breakout`)
- Enter long when close breaks above rolling high of last N bars
- Optional volume confirmation
- Exit on trailing stop or price falls back below rolling high
- Parameters: `lookback_window` (20), `volume_confirmation` (True), `trailing_stop_pct` (0.05)

---

## Transaction Cost Model

Default assumptions (Vietnam market):

| Cost | Rate | Notes |
|------|------|-------|
| Commission | 0.10% per side | Typical broker fee |
| Sell tax | 0.10% on sell | Securities transfer tax |
| Slippage | 10 bps | Market impact estimate |
| **Round-trip total** | **~0.30%** | Commission×2 + tax + slippage×2 |

Override defaults via `config/default.yaml` or `--params` flag.

---

## Architecture

```
src/quant_vn/
├── config/        # Settings (pydantic-settings)
├── data/
│   ├── providers/ # AbstractDataProvider, CsvProvider, VnstockProvider
│   ├── cleaning.py
│   ├── validation.py
│   ├── storage.py  # SQLAlchemy ORM + repositories
│   └── ingestion.py
├── market/
│   ├── calendar.py  # Vietnam trading calendar
│   ├── universe.py  # VN30, blue chips, custom lists
│   └── costs.py     # Transaction cost model
├── indicators/    # SMA, EMA, RSI, ATR, Bollinger, volume
├── strategies/    # AbstractStrategy + 4 implementations
├── backtest/
│   ├── engine.py   # VectorizedBacktestEngine
│   ├── portfolio.py # Position/Trade tracking
│   ├── execution.py # ExecutionConfig
│   ├── metrics.py   # Performance calculations
│   └── reports.py   # Console/CSV/HTML output
├── research/
│   ├── experiment.py       # run_experiment(), compare_strategies()
│   ├── parameter_sweep.py  # Grid search with overfitting warning
│   └── walk_forward.py     # Rolling IS/OOS analysis
├── visualization/ # Charts (plotly/matplotlib)
└── cli.py         # typer app
```

---

## No-Lookahead Bias Guarantee

The engine enforces a strict no-lookahead rule:

1. `strategy.generate_signals(prices)` at index `T` may only use rows `0..T`
2. Engine applies `signals.shift(1)` → execution at T+1 open (not T close)
3. All rolling indicators use `min_periods=window` to prevent partial-window initialization
4. Walk-forward splits have a 5-day embargo between IS end and OOS start

**Verify this yourself**: the `test_no_lookahead_execution_at_next_open` and
`test_identical_results_regardless_of_future_data` tests in `tests/test_backtest_engine.py`
prove these guarantees hold.

---

## Vietnam Market Notes

### Known Limitations

| Issue | Status | Notes |
|-------|--------|-------|
| **T+2 settlement** | Documented | MVP does not enforce; future versions will |
| **Price limits** | Documented | HOSE ±7%, HNX ±10%; spike detector flags these |
| **Survivorship bias** | Documented | Using current tickers only; historical constituents not tracked |
| **Adjusted prices** | Flag present | Mark CSV as adjusted with `--adjusted` flag |
| **Corporate actions** | Placeholder table | Dividends/splits tracked in DB but not auto-applied |
| **Foreign ownership limits** | Not implemented | Relevant for live trading only |
| **Short selling** | Disabled | Long-only by default; `allow_short` config exists |

### Getting Real Data

1. **vnstock** (free, community library):
   ```bash
   pip install vnstock
   quant-vn ingest --provider vnstock --symbol FPT --start 2015-01-01 --end 2025-12-31
   ```

2. **CSV from broker** (VPS, SSI, VNDS, VCSC, etc.):
   - Download from your broker's platform
   - Map columns using `CsvProvider(column_map={...})`

3. **Paid APIs** (FireAnt, VNDirect API):
   - Subclass `CustomProvider` in `src/quant_vn/data/providers/custom_provider.py`

---

## Running Tests

```bash
make test
# or
pytest tests/ -v
```

Expected: all tests pass. The tests use synthetic data — no real data required.

---

## TODO / Roadmap

### Next milestones
- [ ] T+2 settlement enforcement in backtest engine
- [ ] Corporate action adjustment (dividend/split)
- [ ] Intraday data support (HOSE 5-min)
- [ ] Multi-asset portfolio with equal-weight position sizing
- [ ] Benchmark comparison (VNINDEX)
- [ ] Streamlit dashboard

### AI/ML phase (future)
- [ ] Feature engineering pipeline
- [ ] Direction prediction (XGBoost baseline)
- [ ] Time series cross-validation
- [ ] MLflow experiment tracking
- [ ] Model backtest integration

### Live trading (future)
- [ ] Broker API integration (SSI, VPS)
- [ ] Paper trading mode
- [ ] Telegram alerting
- [ ] Risk kill-switch

---

## Project Structure

```
quant-vn/
├── README.md
├── pyproject.toml
├── Makefile
├── .env.example          ← copy to .env, add API keys
├── .gitignore
├── config/
│   ├── default.yaml      ← all configurable defaults
│   ├── universe_vn30.yaml
│   └── watchlist.yaml
├── data/
│   ├── raw/              ← put your CSV files here
│   ├── processed/
│   └── database/         ← quant_vn.db lives here
├── notebooks/            ← Jupyter notebooks for exploration
├── src/quant_vn/         ← all source code
├── tests/                ← pytest tests
└── examples/             ← runnable example scripts
```

---

*Built with Python 3.11+, pandas, SQLAlchemy, pydantic, typer, plotly.*

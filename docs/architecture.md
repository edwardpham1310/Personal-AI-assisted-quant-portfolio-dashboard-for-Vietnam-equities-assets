# Kiến Trúc Hệ Thống — Quant Finance Vietnam

## Tổng quan

Hệ thống được chia thành 4 package độc lập, mỗi package có một trách nhiệm duy nhất.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Quant Finance Workspace                  │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  datapipe/   │    │   quant/     │    │   dashboard/     │  │
│  │              │───▶│              │───▶│                  │  │
│  │ Thu thập &   │    │ Chiến lược & │    │  Biểu đồ &       │  │
│  │ lưu trữ dữ  │    │ Backtest     │    │  Báo cáo         │  │
│  │ liệu sạch   │    │              │    │                  │  │
│  └──────────────┘    └──────┬───────┘    └──────────────────┘  │
│         │                  │                                   │
│         │            ┌─────▼────────┐                          │
│         └───────────▶│    ml/       │                          │
│                      │              │                          │
│                      │ Feature eng  │                          │
│                      │ Training     │                          │
│                      │ Experiment   │                          │
│                      └──────────────┘                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## MVP App Phase Architecture

Giai đoạn MVP dashboard dùng stack sau:

| Layer | Technology |
|-------|------------|
| Frontend | Next.js + Plotly.js |
| Backend | FastAPI |
| Auth | Supabase Auth |
| App DB | Supabase Postgres |
| Realtime cache | Upstash Redis |
| Market data | SSI FastConnect Data |
| Historical analytics | DuckDB + Parquet |
| Streaming | FastAPI Server-Sent Events (SSE) |
| Deployment target | Cloudflare Pages + GCP e2-micro hoặc cheap VPS |

Luồng MVP:

```text
Browser
  |
  | Next.js + Plotly.js
  v
FastAPI backend
  |-- verifies Supabase Auth JWT
  |-- reads/writes app state in Supabase Postgres
  |-- caches latest quotes/signals in Upstash Redis
  |-- fetches market data via SSI FastConnect Data
  |-- reads historical analytics from DuckDB + Parquet
  `-- streams updates to browser via SSE
```

Secrets như Supabase service role key, database password, SSI credentials, và
Redis token chỉ được cấu hình trong backend/API host secret manager hoặc file
`.env` local bị gitignore. Không commit secrets vào docs/config tracked.

---

## Các package

### datapipe/ — Data Pipeline
**Python package:** `quant_vn_data`  
**CLI:** `quant-vn-data`  
**Database:** `datapipe/data/database/quant_vn_data.sqlite` + `.duckdb`

Trách nhiệm:
- Thu thập dữ liệu từ SSI FastConnect, VSDC, Vnstock, CSV
- Ưu tiên SSI-first cho market data realtime/intraday khi API entitlement cho phép
- Lưu raw data theo content-addressed path (SHA-256 hash dedup)
- Chuẩn hóa OHLCV về schema chung
- Kiểm tra chất lượng dữ liệu (15 loại check, 5 mức severity)
- Reconcile multi-source (SSI vs Vnstock)
- Tính liquidity features (20d/60d rolling, tradable_flag)
- Export sang DuckDB để phân tích

### quant/ — Strategy & Backtest
**Python package:** `quant_vn`  
**CLI:** `quant-vn`  
**Database:** `quant/data/database/quant_vn.db`

Trách nhiệm:
- Chỉ báo kỹ thuật (RSI, MA, Bollinger, ATR, volume)
- AbstractStrategy interface + 4 chiến lược built-in
- BacktestEngine vectorized (no-lookahead guarantee)
- Walk-forward validation
- Experiment tracking
- Dashboard & báo cáo

### ml/ — Machine Learning (chưa triển khai)
**Python package:** `quant_vn_ml` (tương lai)

Trách nhiệm:
- Feature engineering từ OHLCV + indicators
- Label generation (forward returns)
- Walk-forward training với embargo
- XGBoost baseline
- Prediction → Signal conversion
- Experiment registry

### dashboard/ — Visualization (chưa triển khai đầy đủ)

Trách nhiệm:
- Hiển thị equity curves, drawdown, metrics
- Data quality reports tương tác
- So sánh chiến lược
- Hiển thị portfolio, intraday 5m/15m signals, AI narrative, risk alerts, và
  recommend-only action suggestions

---

## Luồng dữ liệu chi tiết

```
Nguồn dữ liệu
  SSI FastConnect API  (SSI-first, cần API key/entitlement)
  VSDC (corporate actions, public)
  Vnstock (fallback, public)
  CSV files (local dev)
        │
        ▼
datapipe/providers/          Fetch raw data
datapipe/ingestion/raw_store  Lưu raw → disk (content-addressed)
datapipe/normalization/       Chuẩn hóa → canonical schema
datapipe/validation/          Check chất lượng → issues table
datapipe/storage/sqlite_store Upsert → SQLite (system of record)
datapipe/market/liquidity     Tính liquidity features
datapipe/storage/duckdb_store Export → DuckDB (analytics)
        │
        ▼
quant/data/                  Load từ SQLite/DuckDB hoặc CSV
quant/indicators/            Tính chỉ báo kỹ thuật
quant/strategies/            Generate signals {-1, 0, 1}
quant/backtest/              Simulate positions, costs, equity
quant/research/              Walk-forward, experiment tracking
quant/visualization/         Biểu đồ
dashboard/                   Portfolio UI, intraday signal UI, AI narrative
        │
        ▼ (tương lai)
ml/features/                 Build feature matrix (causal)
ml/labels/                   Forward returns (training only)
ml/trainer/                  Fit XGBoost trên IS window
ml/predictor/                Predict trên OOS → pd.Series
ml/strategy/                 MLStrategy wraps predictions
quant/backtest/              Backtest ML signals (giống rule-based)
```

---

## Nguyên tắc thiết kế

### No-lookahead (bất khả xâm phạm)
- Signal tại T chỉ được dùng data từ 0..T
- `BacktestEngine` shift signal 1 bar: `positions = signals.shift(1)`
- Execute tại T+1 open — không có exception
- Rolling features dùng `min_periods=window` — không có partial-window leakage

### Chất lượng dữ liệu
- Raw data lưu trước normalization, không bao giờ mất
- Mỗi row trong DB có `source` field
- Dữ liệu xấu bị flag (`quality_status`), không bị xóa
- Corporate action dates lưu tách biệt — không tự động adjust giá

### Security
- SSI credentials chỉ lưu trong `.env`, không commit
- Token SSI cache in-memory only, không lưu disk
- Path traversal bị chặn ở RawStore
- API keys được redact trong logs và meta.json

---

## Schema chính (datapipe SQLite)

| Table | Unique key | Mô tả |
|-------|-----------|-------|
| `ohlcv_daily` | (symbol, trading_date, source) | Giá OHLCV hàng ngày |
| `symbols` | (symbol, exchange, source) | Danh mục chứng khoán |
| `corporate_actions` | (symbol, action_type, source, announcement_date) | Sự kiện công ty |
| `data_quality_issues` | id (auto) | Log các vấn đề chất lượng |
| `provider_reconciliation` | (symbol, date, field, primary, secondary) | So sánh đa nguồn |
| `liquidity_features` | (symbol, trading_date) | Chỉ số thanh khoản |

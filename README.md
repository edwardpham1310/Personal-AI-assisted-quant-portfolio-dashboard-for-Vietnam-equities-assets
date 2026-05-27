# Quant Finance — Vietnam Stock Market Research Platform

Hệ thống nghiên cứu định lượng cá nhân cho thị trường chứng khoán Việt Nam (HOSE, HNX, UPCoM).

---

## Cấu trúc thư mục

```
Quant_Finance/
  datapipe/     Data pipeline — thu thập, chuẩn hóa, lưu trữ, kiểm tra chất lượng dữ liệu
  quant/        Chiến lược, backtest, chỉ báo kỹ thuật, nghiên cứu
  ml/           Machine learning — feature/label engineering, training, experiment (chưa triển khai)
  dashboard/    Visualization — biểu đồ, báo cáo tương tác (chưa triển khai)
  docs/         Tài liệu kiến trúc workspace-level
  guide/        Hướng dẫn sử dụng và ví dụ thực tế
```

---

## Luồng dữ liệu

```
SSI FastConnect / VSDC / Vnstock / CSV
        │
        ▼
   [datapipe]
   Thu thập → Chuẩn hóa → Kiểm tra chất lượng → SQLite / DuckDB
        │
        ▼
   [quant]
   Load dữ liệu sạch → Tính chỉ báo → Generate tín hiệu → Backtest → Báo cáo
        │
        ▼ (tương lai)
   [ml]                        [dashboard]
   Feature engineering         Biểu đồ equity curve
   Walk-forward training        Báo cáo data quality
   Prediction → Signal         So sánh chiến lược
```

---

## Bắt đầu nhanh

### 1. Cài đặt

```bash
# Data pipeline
cd datapipe && pip3 install -e ".[dev]" && cd ..

# Strategy/backtest
cd quant && pip3 install -e ".[dev]" && cd ..
```

### 2. Khởi tạo database

```bash
cd datapipe
cp .env.example .env   # điền SSI_CONSUMER_ID + SSI_CONSUMER_SECRET
quant-vn-data db init
```

### 3. Thu thập dữ liệu

```bash
# Dùng Vnstock (không cần API key)
quant-vn-data ingest-ohlcv --provider vnstock --symbol FPT --start 2020-01-01 --end 2026-12-31

# Dùng CSV local
quant-vn-data import-csv --path data/raw/fpt.csv --symbol FPT --exchange HOSE
```

### 4. Kiểm tra chất lượng dữ liệu

```bash
quant-vn-data validate --symbol FPT
quant-vn-data quality-report --output reports/quality.csv
```

### 5. Chạy backtest

```bash
cd ../quant
quant-vn backtest --strategy ma_cross --symbol FPT --start 2020-01-01 --end 2024-12-31
```

Xem thêm: [guide/quickstart.md](guide/quickstart.md)

---

## Nguyên tắc

- **Không lookahead:** Tín hiệu tại T chỉ dùng dữ liệu đến T. Lệnh thực thi tại T+1 open.
- **Chất lượng dữ liệu trước:** Dữ liệu xấu → backtest sai → quyết định sai.
- **Đây là công cụ nghiên cứu, không phải bot giao dịch tự động.**
- Mọi tín hiệu là research signal, không phải lời khuyên đầu tư.

# Hướng Dẫn Bắt Đầu Nhanh

---

## Yêu cầu

- Python 3.11+
- Git

---

## Bước 1: Cài đặt

```bash
# Data pipeline
cd datapipe
pip3 install -e ".[dev]"
cd ..

# Strategy / backtest
cd quant
pip3 install -e ".[dev]"
cd ..
```

---

## Bước 2: Cấu hình credentials

```bash
cd datapipe
cp .env.example .env
```

Mở `.env` và điền:
```
SSI_CONSUMER_ID=your_consumer_id
SSI_CONSUMER_SECRET=your_consumer_secret
```

> Nếu không có SSI key: dùng `--provider vnstock` hoặc `--provider csv` — không cần key.

---

## Bước 3: Khởi tạo database

```bash
cd datapipe
quant-vn-data db init
# Output: Database initialized. Hiển thị table counts.
```

---

## Bước 4: Thu thập dữ liệu (không cần API key)

```bash
# Dùng Vnstock (miễn phí, public data)
quant-vn-data ingest-ohlcv --provider vnstock --symbol FPT --start 2020-01-01 --end 2026-12-31
quant-vn-data ingest-ohlcv --provider vnstock --symbol VCB --start 2020-01-01 --end 2026-12-31
quant-vn-data ingest-ohlcv --provider vnstock --symbol MWG --start 2020-01-01 --end 2026-12-31
```

---

## Bước 5: Kiểm tra chất lượng

```bash
quant-vn-data validate --symbol FPT
quant-vn-data quality-report --output reports/quality.csv
```

---

## Bước 6: Tính liquidity features

```bash
quant-vn-data build-liquidity --symbol FPT
# hoặc cho tất cả symbols:
quant-vn-data build-liquidity --all
```

---

## Bước 7: Chạy backtest đơn giản

```bash
cd ../quant
python3 examples/run_backtest_fpt.py
```

Hoặc qua CLI:
```bash
quant-vn backtest --strategy ma_cross --symbol FPT --start 2020-01-01 --end 2024-12-31
```

---

## Bước 8: Walk-forward validation

```bash
quant-vn walk-forward --strategy ma_cross --symbol FPT --is-months 24 --oos-months 6
```

---

## Luồng ví dụ đầy đủ (script)

Xem:
- [`datapipe/examples/ingest_fpt.py`](../datapipe/examples/ingest_fpt.py) — thu thập dữ liệu
- [`datapipe/examples/validate_data_quality.py`](../datapipe/examples/validate_data_quality.py) — kiểm tra chất lượng
- [`quant/examples/run_backtest_fpt.py`](../quant/examples/run_backtest_fpt.py) — chạy backtest
- [`quant/examples/compare_strategies.py`](../quant/examples/compare_strategies.py) — so sánh chiến lược

---

## Test suite

```bash
# Test data pipeline
cd datapipe && python3 -m pytest tests/ -v

# Test strategy/backtest
cd ../quant && python3 -m pytest tests/ -v
```

---

## Lỗi thường gặp

| Lỗi | Nguyên nhân | Fix |
|-----|------------|-----|
| `ModuleNotFoundError: quant_vn_data` | Chưa install | `cd datapipe && pip3 install -e .` |
| `ModuleNotFoundError: quant_vn` | Chưa install | `cd quant && pip3 install -e .` |
| `SSI credentials are missing` | Chưa điền .env | Dùng `--provider vnstock` thay thế |
| `No data found for symbol` | Chưa ingest | Chạy `ingest-ohlcv` trước |
| `Database not initialized` | Chưa init | `quant-vn-data db init` |

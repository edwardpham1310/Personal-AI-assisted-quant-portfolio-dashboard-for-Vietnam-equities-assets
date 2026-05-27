# Quant Finance Workspace — Claude Instructions

Hệ thống nghiên cứu định lượng cho thị trường chứng khoán Việt Nam.

## Cấu trúc workspace

```
Quant_Finance/
  datapipe/     Data pipeline (quant_vn_data package, CLI: quant-vn-data)
  quant/        Strategy & backtest (quant_vn package, CLI: quant-vn)
  ml/           Machine learning — chưa triển khai
  dashboard/    Visualization — chưa triển khai đầy đủ
  docs/         Tài liệu kiến trúc workspace-level
  guide/        Hướng dẫn sử dụng và ví dụ
```

## Nguyên tắc cốt lõi

- Hệ thống nghiên cứu, không phải bot giao dịch tự động
- Ưu tiên chất lượng dữ liệu, no-lookahead backtest, chi phí giao dịch thực tế
- Mọi tín hiệu là research signal — phải kèm context rủi ro
- Không thêm dependency nặng nếu không cần thiết
- Định hướng sản phẩm: Personal AI-assisted quant portfolio dashboard for Vietnam
  equities, SSI-first, intraday 5m/15m, recommend-only trong phase đầu

## Đọc trước khi code

- Kiến trúc tổng thể: `docs/architecture.md`
- Product vision: `docs/product-vision.md`
- Nguyên tắc nghiên cứu: `docs/trading-rules.md`
- Kiến trúc ML (tương lai): `docs/ml-architecture.md`
- Coding rules (quant): `quant/docs/agent-memory/coding-rules.md`
- Context chung (quant): `quant/docs/agent-memory/shared-context.md`
- Trading framework: `quant/docs/trading-recommendation-framework.md`
- Dashboard spec: `quant/docs/dashboard/dashboard-spec.md`
- Audit datapipe: `datapipe/docs/audit/`
- Audit quant: `quant/docs/audit/`

## Quy tắc no-lookahead (bất khả xâm phạm)

- Signal tại T chỉ dùng data 0..T
- Execute tại T+1 open (BacktestEngine shift signals +1)
- Không dùng `.shift(-n)` bên trong `generate_signals()`
- Rolling features dùng `min_periods=window`

## Khi thêm thay đổi quan trọng

- Thêm audit note vào `datapipe/docs/audit/` hoặc `quant/docs/audit/`
- Chạy test suite của package liên quan trước khi coi là xong

## Package references

| Package | Thư mục | Python import | CLI |
|---------|---------|--------------|-----|
| Data pipeline | `datapipe/` | `from quant_vn_data import ...` | `quant-vn-data` |
| Strategy/backtest | `quant/` | `from quant_vn import ...` | `quant-vn` |
| ML (future) | `ml/` | `from quant_vn_ml import ...` | TBD |
| Dashboard (future) | `dashboard/` | TBD | TBD |

## Cài đặt (sau khi clone)

```bash
cd datapipe && pip3 install -e ".[dev]" && cd ..
cd quant && pip3 install -e ".[dev]" && cd ..
```

## Test

```bash
cd datapipe && python3 -m pytest tests/ -q   # 82 tests
cd quant && python3 -m pytest tests/ -q      # 70 tests
```

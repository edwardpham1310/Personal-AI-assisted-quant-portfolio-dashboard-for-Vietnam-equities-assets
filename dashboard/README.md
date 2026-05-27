# dashboard/ — Visualization Layer

**Trạng thái: Chưa triển khai đầy đủ.** Backend dashboard hiện nằm trong `quant/src/quant_vn/dashboard/`.

---

## Nhiệm vụ

Hiển thị kết quả nghiên cứu dưới dạng biểu đồ và báo cáo tương tác:

```
dashboard/
  app.py                Entry point — chạy dashboard (Flask/Streamlit hoặc static HTML)
  pages/
    equity_curve.py     Equity curve + drawdown chart
    data_quality.py     Data quality issues heatmap
    strategy_compare.py So sánh nhiều chiến lược
    backtest_report.py  Chi tiết một backtest
    ml_results.py       Walk-forward ML results (sau khi ml/ được triển khai)
  templates/            Jinja2 HTML templates
  static/
    css/
    js/
  reports/              Output HTML/PDF đã generated
```

## Phụ thuộc

```
dashboard/ → quant/    (BacktestResult, metrics)
dashboard/ → datapipe/ (data quality issues, OHLCV)
dashboard/ → ml/       (experiment results — tương lai)
```

## Chạy dashboard hiện tại

Logic hiển thị đang nằm trong `quant/`:

```bash
cd ../quant
quant-vn dashboard --symbol FPT
# hoặc
quant-vn reports  # tạo static HTML
```

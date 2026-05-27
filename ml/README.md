# ml/ — Machine Learning Package

**Trạng thái: Chưa triển khai.** Xem kiến trúc đề xuất tại [docs/ml-architecture.md](../docs/ml-architecture.md).

---

## Nhiệm vụ

Mỗi module có một trách nhiệm duy nhất:

```
ml/src/quant_vn_ml/
  features.py           Feature engineering — tất cả features causal tại T
  labels.py             Label generation — forward return, chỉ dùng cho training
  dataset.py            Tạo (X, y) dataset với metadata (symbol, date)
  splitter.py           TimeSeriesSplit với embargo gap chống lookahead
  trainer.py            Training interface + XGBoost baseline
  registry.py           Lưu/tải model artifact (joblib)
  predictor.py          Predict trên OOS data
  signal_converter.py   Prediction → {-1, 0, 1}
  strategy.py           MLStrategy(AbstractStrategy) — wraps precomputed signals
  experiment_store.py   SQLite log: config + metrics + artifact path mỗi lần chạy
```

## Phụ thuộc

```
ml/ → datapipe/ (dữ liệu sạch qua DuckDB)
ml/ → quant/    (BacktestEngine, AbstractStrategy)
```

## Nguyên tắc không được vi phạm

- Features tại row T chỉ được dùng OHLCV/liquidity data từ 0..T
- Labels `y[T] = close[T+n]/close[T]-1` — chỉ dùng làm training target, KHÔNG làm feature
- Scaler/encoder phải fit chỉ trên IS data, apply sang OOS
- Mỗi lần chạy phải được log vào experiment_store TRƯỚC khi xem OOS metrics
- Embargo gap ≥ max_lookback_days giữa IS end và OOS start

## Cài đặt (sau khi triển khai)

```bash
cd ml
pip3 install -e ".[dev]"
```

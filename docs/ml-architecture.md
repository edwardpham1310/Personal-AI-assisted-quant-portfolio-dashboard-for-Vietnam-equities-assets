# Kiến Trúc ML — Đề Xuất

**Trạng thái:** Chưa triển khai. Đây là blueprint thiết kế cho `ml/` package.

---

## Các module cần tạo

```
ml/src/quant_vn_ml/
  features.py           Build feature matrix (all causal at T)
  labels.py             Forward return labels (y[T] = close[T+n]/close[T]-1)
  dataset.py            MLDataset: align X + y + metadata, verify no overlap
  splitter.py           walk_forward_splits() với embargo gap
  trainer.py            ModelTrainer protocol + XGBoostTrainer
  registry.py           save/load model artifacts (joblib) theo experiment_id
  predictor.py          load model → predict(X_oos) → pd.Series indexed by date
  signal_converter.py   to_signals(preds, long_threshold, short_threshold) → {-1,0,1}
  strategy.py           MLStrategy(AbstractStrategy): wraps precomputed signal Series
  experiment_store.py   SQLite log: config + per-window metrics + artifact path
```

```
quant/src/quant_vn/research/
  ml_walk_forward.py    Coordinator: retrain-per-window → predict OOS → backtest
```

---

## Luồng dữ liệu ML

```
datapipe SQLite → DuckDB v_ohlcv_clean
    │
    ├── features.py → X (feature matrix, tất cả columns causal tại T)
    │                   ví dụ: rsi_14, ma_20, volume_ratio, momentum_5d, ...
    │
    ├── labels.py   → y (forward returns, chỉ dùng làm training target)
    │                   y[T] = close[T+5] / close[T] - 1
    │
    └── dataset.py  → MLDataset(X, y, dates, symbols)
            │
            ▼
    splitter.py → [(IS_1, OOS_1), (IS_2, OOS_2), ...]
            │
    ┌───────┘ mỗi window:
    │
    ├── trainer.py  → fit(X_IS, y_IS) → Model
    ├── registry.py → save(model, experiment_id, window_id)
    │
    └── predictor.py → predict(X_OOS) → pd.Series(date → float)
            │
    signal_converter.py → pd.Series(date → {-1, 0, 1})
            │
    MLStrategy.generate_signals(prices) → signals
            │
    BacktestEngine.run(ml_strategy, prices) → BacktestResult
            │
    experiment_store.py → log(metrics, config, artifact_path)
```

---

## Schema database mới (ml/data/ml_experiments.sqlite)

```sql
CREATE TABLE ml_experiments (
    experiment_id   TEXT PRIMARY KEY,   -- uuid4
    created_at      DATETIME NOT NULL,
    model_type      TEXT NOT NULL,      -- "xgboost_classifier"
    symbols         TEXT NOT NULL,      -- JSON list
    feature_version TEXT NOT NULL,      -- hash(feature_config)
    label_type      TEXT NOT NULL,      -- "forward_return_5d"
    horizon_days    INTEGER NOT NULL,
    train_start     DATE NOT NULL,
    train_end       DATE NOT NULL,
    test_start      DATE NOT NULL,
    test_end        DATE NOT NULL,
    hyperparams     TEXT,               -- JSON
    is_metrics      TEXT,               -- JSON
    oos_metrics     TEXT,               -- JSON
    artifact_path   TEXT
);

CREATE TABLE ml_predictions (
    experiment_id   TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    trading_date    DATE NOT NULL,
    raw_prediction  REAL,
    signal          INTEGER,            -- {-1, 0, 1}
    PRIMARY KEY (experiment_id, symbol, trading_date)
);
```

**Lưu tại:** `ml/data/ml_experiments.sqlite` — tách biệt khỏi `datapipe/data/`.

---

## Rủi ro và anti-pattern cần tránh

### Label leakage (nghiêm trọng nhất)
- `y[T]` dùng `close[T+n]` → đúng cho training target
- NHƯNG column này không bao giờ được xuất hiện trong feature matrix `X`
- `dataset.py` phải assert rằng không có cột nào trong X overlap với y

### Rolling window leakage
```python
# SAI: shift(-1) bên trong feature construction
df["feature"] = df["close"].rolling(20).mean().shift(-1)

# ĐÚNG: chỉ dùng dữ liệu đến T
df["feature"] = df["close"].rolling(20, min_periods=20).mean()
```

### Scaler leakage
```python
# SAI: fit scaler trên toàn bộ data trước khi split
scaler.fit(X_full)

# ĐÚNG: fit chỉ trên IS, apply sang OOS
scaler.fit(X_IS)
X_OOS_scaled = scaler.transform(X_OOS)
```

### Walk-forward overfitting
- KHÔNG tune hyperparameter bằng cách nhìn OOS Sharpe
- Hyperparameter search phải dùng nested cross-validation trong IS
- Mỗi lần chạy phải log vào experiment_store TRƯỚC khi xem OOS metrics

### Survivorship bias
- Dùng `tradable_flag` tại thời điểm T để filter universe, không phải universe hiện tại
- Cổ phiếu bị hủy niêm yết sau training window vẫn phải được include trong training

### Corporate action contamination
- `is_adjusted=False` trên tất cả prices hiện tại → price jump tại ex-date
- Feature momentum/return qua ex-date sẽ có spike giả
- Cần resolve `is_adjusted` trước khi dùng price-derived features trong ML

### Vietnam-specific
- Limit-up/limit-down ±7%/10%/15%: tạo autocorrelation giả trong returns
- Lịch sử dữ liệu mỏng (~2,400 rows/symbol cho 10 năm với 60-day lookback)
- XGBoost cần early stopping và regularization mạnh để tránh overfit

---

## Phụ thuộc package

```toml
# ml/pyproject.toml
[project.optional-dependencies]
ml = [
    "scikit-learn>=1.4.0",
    "xgboost>=2.0.0",
    "joblib>=1.3.0",
    "optuna>=3.5.0",    # hyperparameter search (optional)
]
```

Không thêm dependencies vào `datapipe/` hay `quant/` — ML là optional layer.

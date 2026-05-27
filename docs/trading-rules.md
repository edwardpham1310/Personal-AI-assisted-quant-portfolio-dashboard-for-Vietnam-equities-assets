# Nguyên Tắc Nghiên Cứu & Giao Dịch

Áp dụng cho tất cả code trong workspace này.

---

## Quy tắc dữ liệu

1. **Lưu raw trước, normalize sau.** Raw data không bao giờ bị mất.
2. **Mỗi row phải có `source` field.** Không có dữ liệu vô danh trong database.
3. **Dữ liệu xấu bị flag, không bị xóa.** `quality_status` ghi nhận vấn đề, không xóa rows.
4. **Corporate action lưu tách biệt.** Không tự động adjust giá tại data layer.
5. **`adjusted_close` không được bịa đặt.** Nếu nguồn không cung cấp, để `None` và `is_adjusted=False`.
6. **Reconciliation mismatch được ghi lại.** Không tự resolve xung đột giữa các nguồn.

---

## Quy tắc no-lookahead (bất khả xâm phạm)

| Hành động | Được phép | Không được phép |
|-----------|-----------|-----------------|
| Signal tại T dùng data 0..T | ✓ | |
| Signal tại T dùng data T+1.. | | ✗ LOOKAHEAD |
| `.shift(-n)` bên trong `generate_signals()` | | ✗ LOOKAHEAD |
| `.shift(-n)` để tạo training label | ✓ (label only) | |
| Execute tại T+1 open | ✓ (default) | |
| Execute tại T close với signal tại T | Academic only | Không dùng production |
| Scaler fit trên full dataset | | ✗ LEAKAGE |
| Scaler fit chỉ trên IS data | ✓ | |

---

## Quy tắc backtest

- **Chi phí giao dịch phải thực tế:** commission 0.1%, thuế bán 0.1%, slippage 0.05%
- **T+2 settlement:** không thể mua và bán cùng ngày (Vietnam)
- **Long-only** cho giai đoạn nghiên cứu — Vietnam hạn chế short selling
- **Position sizing:** full allocation mặc định, add fractional-size sau
- Không pathfinder trên OOS — nếu nhìn OOS để chọn chiến lược tốt hơn, đó là overfit

---

## Quy tắc khi viết code

- Không dùng `df.shift(-n)` bên trong bất kỳ strategy hay indicator nào
- Rolling features phải dùng `min_periods=window` — partial windows là lookahead
- Không dùng future prices để tính bất kỳ indicator nào
- Mỗi thay đổi quan trọng cần file audit trong `<package>/docs/audit/`
- Không hardcode API keys — luôn dùng `.env`

---

## Quy tắc báo cáo

- Mọi báo cáo phải ghi rõ: symbol, period, strategy, transaction costs, initial capital
- Sharpe ratio dùng annualized với 252 trading days
- Không so sánh chiến lược nếu period khác nhau
- "Tín hiệu tốt trong backtest" ≠ "sẽ có lãi trong tương lai"
- Luôn kèm max drawdown và số lệnh — nhiều metric mới có giá trị

---

## Quy tắc Dashboard AI & Realtime

- Phase đầu là recommend-only: không đặt lệnh thật từ dashboard.
- Signal tactical mặc định dùng khung intraday 5m/15m nếu dữ liệu đủ sạch.
- AI narrative chỉ được đọc dữ liệu/chỉ báo đã tính và trạng thái portfolio từ DB;
  AI không được tự tạo số liệu không có nguồn.
- Mỗi action suggestion phải có timestamp dữ liệu, lý do định lượng, rủi ro, và
  confidence.
- Portfolio risk alerts phải tách biệt với buy/sell suggestions.
- Broker integration bắt đầu bằng read-only sync trước, sau đó mới paper trading,
  rồi mới manual approval trading.

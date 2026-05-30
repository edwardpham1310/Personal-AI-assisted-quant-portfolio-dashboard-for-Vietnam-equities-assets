from collections.abc import Iterable

from .schemas import PriceBar, Transaction, ValidationIssue, ValidationResult


def validate_price_bars(price_bars: Iterable[PriceBar]) -> ValidationResult:
    issues: list[ValidationIssue] = []
    seen_keys: set[tuple[str, object, str]] = set()

    for row_index, bar in enumerate(price_bars):
        symbol = bar.symbol.strip().upper()
        key = (symbol, bar.trading_date, bar.timeframe)

        if not symbol:
            issues.append(_issue("error", "missing_symbol", "Missing ticker symbol", row_index))

        if key in seen_keys:
            issues.append(
                _issue(
                    "error",
                    "duplicate_price_bar",
                    "Duplicate symbol/date/timeframe price bar",
                    row_index,
                    symbol,
                )
            )
        seen_keys.add(key)

        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            issues.append(_issue("error", "invalid_price", "OHLC prices must be positive", row_index, symbol))

        if bar.low > bar.high:
            issues.append(_issue("error", "invalid_range", "Low price cannot exceed high price", row_index, symbol))

        if not (bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high):
            issues.append(
                _issue("warning", "ohlc_outside_range", "Open/close is outside low/high range", row_index, symbol)
            )

        if bar.volume < 0:
            issues.append(_issue("error", "invalid_volume", "Volume cannot be negative", row_index, symbol))

    return ValidationResult(issues)


def validate_transactions(transactions: Iterable[Transaction]) -> ValidationResult:
    issues: list[ValidationIssue] = []
    seen_ids: set[str] = set()

    for row_index, transaction in enumerate(transactions):
        symbol = transaction.symbol.strip().upper()

        if not transaction.transaction_id:
            issues.append(_issue("error", "missing_transaction_id", "Missing transaction id", row_index, symbol))
        elif transaction.transaction_id in seen_ids:
            issues.append(_issue("error", "duplicate_transaction_id", "Duplicate transaction id", row_index, symbol))
        seen_ids.add(transaction.transaction_id)

        if not symbol:
            issues.append(_issue("error", "missing_symbol", "Missing ticker symbol", row_index))

        if transaction.quantity <= 0:
            issues.append(_issue("error", "invalid_quantity", "Quantity must be positive", row_index, symbol))

        if transaction.price <= 0:
            issues.append(_issue("error", "invalid_price", "Transaction price must be positive", row_index, symbol))

        if transaction.fee < 0 or transaction.tax < 0:
            issues.append(_issue("error", "invalid_cost", "Fee and tax cannot be negative", row_index, symbol))

    return ValidationResult(issues)


def _issue(
    severity: str,
    code: str,
    message: str,
    row_index: int,
    symbol: str | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,  # type: ignore[arg-type]
        code=code,
        message=message,
        row_index=row_index,
        symbol=symbol,
    )

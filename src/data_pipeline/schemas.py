from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class PriceBar:
    symbol: str
    trading_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    source: str
    timeframe: str = "1d"


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: int
    price: Decimal
    trade_datetime: datetime
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    source: str = "manual"


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    action_type: str
    announcement_date: date
    effective_date: date | None = None
    ratio: Decimal | None = None
    cash_amount: Decimal | None = None
    source: str = "manual"


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    row_index: int | None = None
    symbol: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

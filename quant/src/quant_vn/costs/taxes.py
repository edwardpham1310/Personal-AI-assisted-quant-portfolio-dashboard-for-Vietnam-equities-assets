"""
Vietnam tax models for securities transactions.

Sell-side personal income tax (thuế TNCN từ chuyển nhượng chứng khoán):
    - Rate: 0.1% of GROSS sell transaction value
    - Applied per trade regardless of profit or loss
    - Withheld by broker at point of sale
    - Legal basis: Law on Personal Income Tax No. 04/2007/QH12, Art. 11;
      amended by Law No. 26/2012/QH13

Dividend income tax (thuế TNCN từ cổ tức):
    - Rate: 5% of cash dividend gross amount
    - Withheld at source by the issuing company / VSD
    - Legal basis: Law on Personal Income Tax, Art. 10

Stock dividend / bonus shares:
    - NOT taxed at receipt; cost basis is zero
    - Taxed as securities transfer income (0.1%) when sold
    - StockDividendTaxModel raises NotImplementedError until rules are verified

DISCLAIMER: For research only. Tax rules may change. Verify with a Vietnamese
tax professional and the relevant circulars before making investment decisions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TaxResult:
    gross_amount: float   # VND — the amount the tax is calculated on
    tax_amount: float     # VND
    tax_rate: float
    tax_type: str


class TaxModel(ABC):
    @abstractmethod
    def calculate(self, gross_amount: float) -> TaxResult: ...


@dataclass
class SellTaxModel(TaxModel):
    """
    Securities transfer tax: 0.1% of gross sell transaction value.

    Formula:
        sell_tax = gross_sell_value * rate

    Important:
        - Applied to GROSS sell value (before deducting brokerage fee).
        - Applied on every sell trade, regardless of profit or loss.
        - NOT applied on buy trades.
        - NOT subject to VAT (it is a statutory tax, not a service fee).
    """
    rate: float = 0.001   # 0.1% — statutory as of 2024

    def calculate(self, gross_amount: float) -> TaxResult:
        if gross_amount < 0:
            raise ValueError(f"gross_amount must be non-negative, got {gross_amount}")
        return TaxResult(
            gross_amount=gross_amount,
            tax_amount=gross_amount * self.rate,
            tax_rate=self.rate,
            tax_type="sell_tax",
        )


@dataclass
class DividendTaxModel(TaxModel):
    """
    Personal income tax on cash dividends: 5% of gross dividend amount.

    Formula:
        dividend_tax = cash_dividend_gross * rate
        net_dividend = cash_dividend_gross - dividend_tax

    Important:
        - Applied to CASH dividends only.
        - Withheld at source before dividend reaches investor account.
        - Stock dividends and bonus shares use StockDividendTaxModel.
    """
    rate: float = 0.05    # 5% — statutory as of 2024

    def calculate(self, gross_amount: float) -> TaxResult:
        if gross_amount < 0:
            raise ValueError(f"gross_amount must be non-negative, got {gross_amount}")
        return TaxResult(
            gross_amount=gross_amount,
            tax_amount=gross_amount * self.rate,
            tax_rate=self.rate,
            tax_type="dividend_tax",
        )


class StockDividendTaxModel(TaxModel):
    """
    Placeholder for stock dividend / bonus share tax model.

    Tax treatment:
        - Stock dividends and bonus shares are NOT taxed at receipt.
        - Cost basis of those shares is ZERO.
        - When eventually sold, 0.1% securities transfer tax applies to the
          full gross sell value (same as SellTaxModel).
        - The zero-cost-basis effect means capital gains are effectively fully
          taxable, but through the sell-tax mechanism, not a capital gains tax.

    This model raises NotImplementedError — implement only after confirming the
    exact rules with a Vietnamese tax professional.
    """

    def calculate(self, gross_amount: float) -> TaxResult:
        raise NotImplementedError(
            "StockDividendTaxModel is not implemented. "
            "Tax treatment of stock dividends requires explicit confirmation "
            "of applicable Vietnamese tax regulations before implementation. "
            "For the sell-side tax when selling stock-dividend shares, use "
            "SellTaxModel with rate=0.001 applied to the gross sell value."
        )


@dataclass
class TaxProfile:
    """
    Bundled tax configuration for a backtest or recommendation run.

    All rates must be verified against current Vietnamese tax law before use.
    """
    sell_tax: SellTaxModel = None          # type: ignore[assignment]
    dividend_cash_tax: DividendTaxModel = None   # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.sell_tax is None:
            self.sell_tax = SellTaxModel()
        if self.dividend_cash_tax is None:
            self.dividend_cash_tax = DividendTaxModel()


# Default profile using statutory Vietnam rates as of 2024
VIETNAM_DEFAULT_TAXES = TaxProfile()

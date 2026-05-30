"""
Vietnam trading cost models.

New, detailed cost calculation for recommendation validation and reporting.
The backtest engine continues to use the legacy TransactionCosts from
quant_vn.market.costs.

Modules:
    vat          — VAT on brokerage service fees (10% in Vietnam)
    taxes        — Securities transfer tax (0.1%) and dividend income tax (5%)
    brokerage    — Broker fee profiles: flat and tiered fee models
    slippage     — Market impact / bid-ask spread models
    cash_advance — Ứng trước tiền bán: cash advance on pending sell proceeds
    transaction  — Facade composing all cost components

DISCLAIMER: Default rates are for research only and are NOT financial, tax, or
legal advice. Verify all rates with your actual broker and relevant Vietnamese
authorities before making investment decisions.
"""

from .vat import VATModel, VATResult, VAT_INCLUSIVE, VAT_EXCLUSIVE_10PCT, VAT_DISABLED
from .taxes import SellTaxModel, DividendTaxModel, StockDividendTaxModel, TaxProfile, VIETNAM_DEFAULT_TAXES
from .brokerage import FlatFeeModel, TieredFeeModel, FeeTier, BrokerFeeProfile, BrokerageResult
from .slippage import FixedBpsSlippageModel, LiquidityBucketSlippageModel, SlippageResult, Side
from .cash_advance import (
    CashAdvanceProfile, CashAdvanceModel, CashAdvanceResult, FeeModel,
    CASH_ADVANCE_DISABLED,
)
from .transaction import TransactionCostModel, TransactionCostBreakdown, DEFAULT_COSTS

__all__ = [
    # VAT
    "VATModel", "VATResult", "VAT_INCLUSIVE", "VAT_EXCLUSIVE_10PCT", "VAT_DISABLED",
    # Taxes
    "SellTaxModel", "DividendTaxModel", "StockDividendTaxModel", "TaxProfile",
    "VIETNAM_DEFAULT_TAXES",
    # Brokerage
    "FlatFeeModel", "TieredFeeModel", "FeeTier", "BrokerFeeProfile", "BrokerageResult",
    # Slippage
    "FixedBpsSlippageModel", "LiquidityBucketSlippageModel", "SlippageResult", "Side",
    # Cash advance
    "CashAdvanceProfile", "CashAdvanceModel", "CashAdvanceResult", "FeeModel",
    "CASH_ADVANCE_DISABLED",
    # Transaction facade
    "TransactionCostModel", "TransactionCostBreakdown", "DEFAULT_COSTS",
]

"""
VAT model for Vietnam brokerage service fees.

Vietnam VAT (Thuế Giá Trị Gia Tăng) applies to brokerage commission as a
service fee. As of 2024 the standard rate is 10%.

Key rules:
- VAT applies to the brokerage fee amount, NOT to the trade notional.
- VAT does NOT apply to the 0.1% securities transfer tax (sell tax).
- Some broker fee schedules already include VAT (VAT-inclusive). In that case
  adding VAT on top would double-count it — use ``fee_includes_vat=True``.

DISCLAIMER: For research only. Verify with your broker and Vietnamese tax
authority. Rates may change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VATResult:
    """Result of a VAT calculation."""
    base_fee: float        # fee before VAT (VND)
    vat_amount: float      # VAT charged (VND); 0 if disabled or already included
    total_with_vat: float  # base_fee + vat_amount


@dataclass
class VATModel:
    """
    Compute VAT on a brokerage service fee.

    Args:
        enabled: Whether VAT applies at all. Set False for VAT-exempt scenarios.
        rate: VAT rate as a decimal (e.g. 0.10 for 10%).
        fee_includes_vat: If True the fee passed in already embeds VAT — no
            additional VAT is added (prevents double-counting).

    Assumption: VAT applies only to brokerage/service fees, not to the
    securities transfer tax (sell tax).
    """
    enabled: bool = True
    rate: float = 0.10           # 10% — statutory rate as of 2024
    fee_includes_vat: bool = False

    def calculate(self, base_fee: float) -> VATResult:
        """
        Compute VAT on ``base_fee``.

        Logic:
            if fee_includes_vat is True  → vat = 0  (fee already contains VAT)
            elif enabled is True          → vat = base_fee * rate
            else                          → vat = 0
        """
        if self.fee_includes_vat or not self.enabled:
            vat_amount = 0.0
        else:
            vat_amount = base_fee * self.rate

        return VATResult(
            base_fee=base_fee,
            vat_amount=vat_amount,
            total_with_vat=base_fee + vat_amount,
        )


# Singleton with VAT disabled — used when broker fee already includes VAT.
VAT_INCLUSIVE = VATModel(enabled=True, rate=0.10, fee_includes_vat=True)

# Singleton with VAT enabled at 10% on top of fee.
VAT_EXCLUSIVE_10PCT = VATModel(enabled=True, rate=0.10, fee_includes_vat=False)

# Singleton with VAT disabled.
VAT_DISABLED = VATModel(enabled=False, rate=0.10, fee_includes_vat=False)

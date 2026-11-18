"""Shared Decimal types for the pure calculation engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANT = Decimal("0.01")


def round_money(value: Decimal) -> Decimal:
    """Round a monetary amount to 2 decimal places (ROUND_HALF_UP)."""
    return Decimal(value).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class DebtInput:
    outstanding_balance: Decimal
    annual_rate: Decimal
    remaining_term_years: int
    grace_years: int = 0


@dataclass(frozen=True, slots=True)
class ProposalScheduleInput:
    financed_amount: Decimal
    annual_rate: Decimal
    term_years: int
    grace_years: int
    charge_interest_during_grace: bool = False


@dataclass(frozen=True, slots=True)
class YearPayment:
    year: int
    interest: Decimal
    principal: Decimal
    payment: Decimal
    balance: Decimal


@dataclass(frozen=True, slots=True)
class CapacityYearInput:
    year: int
    total_revenue: Decimal
    activity_expense: Decimal
    family_maintenance: Decimal
    proposal_payment: Decimal
    existing_debt_principal: Decimal
    existing_debt_interest: Decimal


@dataclass(frozen=True, slots=True)
class CapacityYearResult:
    year: int
    total_expense: Decimal
    surplus: Decimal


@dataclass(frozen=True, slots=True)
class ClassificationInput:
    total_rba: Decimal
    agro_revenue_share: Decimal
    milk_vbp_factor: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    group_code: str
    rule_source: str

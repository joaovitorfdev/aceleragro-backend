"""Payment capacity (annual surplus) calculations."""

from __future__ import annotations

from decimal import Decimal

from acelera_agro.engine.types import CapacityYearInput, CapacityYearResult, round_money


def compute_payment_capacity(years: list[CapacityYearInput]) -> list[CapacityYearResult]:
    """Compute annual payment capacity (surplus).

    Surplus = revenue − (activity expense + proposal payment + family maintenance
    + existing debt principal + existing debt interest).
    """
    results: list[CapacityYearResult] = []
    for row in years:
        total_expense = round_money(
            Decimal(row.activity_expense)
            + Decimal(row.proposal_payment)
            + Decimal(row.family_maintenance)
            + Decimal(row.existing_debt_principal)
            + Decimal(row.existing_debt_interest)
        )
        surplus = round_money(Decimal(row.total_revenue) - total_expense)
        results.append(
            CapacityYearResult(
                year=row.year,
                total_expense=total_expense,
                surplus=surplus,
            )
        )
    return results

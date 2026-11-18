"""Amortization of existing debts (BB spreadsheet convention)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from acelera_agro.engine.types import DebtInput, round_money


def _compound_growth_factor(annual_rate: Decimal, periods: int) -> Decimal:
    """Return (1 + rate) ** periods - 1 via iterative multiply (exact for Decimal rates)."""
    growth = Decimal("1")
    one_plus = Decimal("1") + annual_rate
    for _ in range(periods):
        growth *= one_plus
    return growth - Decimal("1")


def amortize_existing_debts(
    debts: list[DebtInput],
    horizon_years: int,
) -> dict[str, Any]:
    """Amortize existing debts over ``horizon_years``.

    Per debt (BB spreadsheet rule):

    - ``annual_principal = outstanding / (remaining_term - grace)`` for payment
      years after grace; zero during grace.
    - Year ``k`` interest (1-based index within the amortization window) =
      ``principal * ((1 + rate) ** k - 1)``. Interest uses the exact
      (unrounded) principal quotient so cents match the BB reference; the
      per-year principal total is still rounded per debt for cash flows.
    - ``payment = principal + interest``.

    Returns::

        {
          "years": [
            {"year": 1, "principal": Decimal, "interest": Decimal, "payment": Decimal},
            ...
          ],
          "annual_principal_by_debt": [Decimal, ...],
        }
    """
    if horizon_years <= 0:
        raise ValueError("horizon_years must be positive")

    year_principal = [Decimal("0.00") for _ in range(horizon_years)]
    year_interest = [Decimal("0.00") for _ in range(horizon_years)]
    annual_principals: list[Decimal] = []

    for debt in debts:
        amort_years = debt.remaining_term_years - debt.grace_years
        if amort_years <= 0:
            raise ValueError(
                "remaining_term_years must be greater than grace_years for each debt"
            )
        if debt.outstanding_balance < 0 or debt.annual_rate < 0:
            raise ValueError("outstanding_balance and annual_rate must be non-negative")

        outstanding = Decimal(debt.outstanding_balance)
        # Exact quotient for interest; rounded value for principal cash-flow lines.
        principal_exact = outstanding / Decimal(amort_years)
        annual_principal = round_money(principal_exact)
        annual_principals.append(annual_principal)
        rate = Decimal(debt.annual_rate)

        for year in range(1, horizon_years + 1):
            if year > debt.remaining_term_years:
                continue
            if year <= debt.grace_years:
                principal = Decimal("0.00")
                interest = Decimal("0.00")
            else:
                k = year - debt.grace_years
                principal = annual_principal
                factor = _compound_growth_factor(rate, k)
                interest = round_money(principal_exact * factor)

            idx = year - 1
            year_principal[idx] = round_money(year_principal[idx] + principal)
            year_interest[idx] = round_money(year_interest[idx] + interest)

    years: list[dict[str, Decimal | int]] = []
    for year in range(1, horizon_years + 1):
        idx = year - 1
        principal = year_principal[idx]
        interest = year_interest[idx]
        years.append(
            {
                "year": year,
                "principal": principal,
                "interest": interest,
                "payment": round_money(principal + interest),
            }
        )

    return {
        "years": years,
        "annual_principal_by_debt": annual_principals,
    }

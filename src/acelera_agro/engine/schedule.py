"""Proposal amortization schedule (annual compound interest)."""

from __future__ import annotations

from decimal import Decimal

from acelera_agro.engine.types import ProposalScheduleInput, YearPayment, round_money


def build_proposal_schedule(input: ProposalScheduleInput) -> list[YearPayment]:
    """Build the annual payment schedule for a financed proposal.

    Confirmed against BB reference (to the cent for years 1–N under ROUND_HALF_UP):

    - Financed amount is given (budget + financed technical assistance).
    - Interest accrues annually on the outstanding balance (compound).
    - During grace without interest charge: interest capitalizes; principal and
      payment are zero.
    - During grace with interest charge: pay the year's interest only; balance
      unchanged.
    - After grace: principal = (balance + year_interest) / remaining_installments;
      balance becomes balance + interest - principal; payment = interest + principal.
    - The final year clears the remaining balance (principal = balance + interest).
    """
    if input.term_years <= 0:
        raise ValueError("term_years must be positive")
    if input.grace_years < 0 or input.grace_years > input.term_years:
        raise ValueError("grace_years must be between 0 and term_years")
    if input.financed_amount < 0:
        raise ValueError("financed_amount must be non-negative")
    if input.annual_rate < 0:
        raise ValueError("annual_rate must be non-negative")

    balance = round_money(input.financed_amount)
    rate = Decimal(input.annual_rate)
    schedule: list[YearPayment] = []

    for year in range(1, input.term_years + 1):
        interest = round_money(balance * rate)
        in_grace = year <= input.grace_years

        if in_grace:
            if input.charge_interest_during_grace:
                principal = Decimal("0.00")
                payment = interest
                # Interest is paid; it does not capitalize.
                new_balance = balance
            else:
                principal = Decimal("0.00")
                payment = Decimal("0.00")
                new_balance = round_money(balance + interest)
        else:
            remaining = input.term_years - year + 1
            if remaining == 1:
                # Clear residual cents on the final installment.
                principal = round_money(balance + interest)
            else:
                principal = round_money((balance + interest) / Decimal(remaining))
            payment = round_money(principal + interest)
            new_balance = round_money(balance + interest - principal)

        if new_balance < 0:
            new_balance = Decimal("0.00")

        schedule.append(
            YearPayment(
                year=year,
                interest=interest,
                principal=principal,
                payment=payment,
                balance=new_balance,
            )
        )
        balance = new_balance

    return schedule

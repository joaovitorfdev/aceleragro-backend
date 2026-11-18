"""Proposal calculation service wrapping the pure engine."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from acelera_agro.engine import (
    CapacityYearInput,
    ClassificationInput,
    DebtInput,
    ProposalScheduleInput,
    amortize_existing_debts,
    build_proposal_schedule,
    classify_producer_current_rule,
    classify_producer_spreadsheet_rule,
    compute_payment_capacity,
)
from acelera_agro.proposals.models import Proposal


def _d(value) -> Decimal:
    return Decimal(str(value))


def _money_rows(schedule) -> list[dict]:
    return [
        {
            "year": row.year,
            "interest": str(row.interest),
            "principal": str(row.principal),
            "payment": str(row.payment),
            "balance": str(row.balance),
        }
        for row in schedule
    ]


@transaction.atomic
def calculate_proposal(proposal: Proposal) -> Proposal:
    """Run schedule / debt / capacity / classification and persist JSON results."""
    financed = proposal.financed_amount
    if proposal.budget_items.exists() and financed == 0:
        financed = sum(
            (_d(item.amount) for item in proposal.budget_items.all()),
            Decimal("0.00"),
        )
        proposal.financed_amount = financed

    annual_rate = proposal.annual_rate
    term_years = proposal.term_years
    grace_years = proposal.grace_years
    charge_grace = proposal.charge_interest_during_grace

    if proposal.credit_line_id:
        line = proposal.credit_line
        if annual_rate is None:
            annual_rate = line.annual_rate
        if term_years is None:
            term_years = line.term_years
        if grace_years is None:
            grace_years = line.grace_years
        charge_grace = line.charge_interest_during_grace

    annual_rate = annual_rate if annual_rate is not None else Decimal("0.03")
    term_years = term_years or 10
    grace_years = grace_years if grace_years is not None else 0

    proposal.annual_rate = annual_rate
    proposal.term_years = term_years
    proposal.grace_years = grace_years
    proposal.charge_interest_during_grace = charge_grace

    schedule = build_proposal_schedule(
        ProposalScheduleInput(
            financed_amount=_d(financed),
            annual_rate=_d(annual_rate),
            term_years=int(term_years),
            grace_years=int(grace_years),
            charge_interest_during_grace=bool(charge_grace),
        )
    )
    proposal.schedule_json = _money_rows(schedule)

    debts = [
        DebtInput(
            outstanding_balance=_d(d.outstanding_balance),
            annual_rate=_d(d.annual_rate),
            remaining_term_years=int(d.remaining_term_years),
            grace_years=int(d.grace_years),
        )
        for d in proposal.existing_debts.all()
        # Form drafts may hold debt rows still being filled in (zero = not informed).
        if d.outstanding_balance > 0 and d.remaining_term_years > 0
    ]
    horizon = max(int(term_years), 5)
    debt_result = (
        amortize_existing_debts(debts, horizon_years=horizon)
        if debts
        else {"years": [{"year": y, "principal": Decimal("0"), "interest": Decimal("0")} for y in range(1, horizon + 1)]}
    )

    # Aggregate activity projections by year
    revenue_by_year: dict[int, Decimal] = {}
    expense_by_year: dict[int, Decimal] = {}
    for proj in proposal.activity_projections.all():
        revenue_by_year[proj.year] = revenue_by_year.get(proj.year, Decimal("0")) + _d(
            proj.revenue
        )
        expense_by_year[proj.year] = expense_by_year.get(proj.year, Decimal("0")) + _d(
            proj.expense
        )

    capacity_inputs: list[CapacityYearInput] = []
    for year in range(1, horizon + 1):
        payment = next((r.payment for r in schedule if r.year == year), Decimal("0.00"))
        debt_year = debt_result["years"][year - 1] if year <= len(debt_result["years"]) else {
            "principal": Decimal("0"),
            "interest": Decimal("0"),
        }
        capacity_inputs.append(
            CapacityYearInput(
                year=year,
                total_revenue=revenue_by_year.get(year, Decimal("0")),
                activity_expense=expense_by_year.get(year, Decimal("0")),
                family_maintenance=_d(proposal.family_maintenance),
                proposal_payment=_d(payment),
                existing_debt_principal=_d(debt_year["principal"]),
                existing_debt_interest=_d(debt_year["interest"]),
            )
        )

    capacity = compute_payment_capacity(capacity_inputs)
    proposal.capacity_json = [
        {
            "year": row.year,
            "total_expense": str(row.total_expense),
            "surplus": str(row.surplus),
        }
        for row in capacity
    ]

    class_input = ClassificationInput(
        total_rba=_d(proposal.total_rba),
        agro_revenue_share=_d(proposal.agro_revenue_share),
    )
    rule_source = "spreadsheet_legacy"
    if proposal.ruleset_id and (proposal.ruleset.config or {}).get("classification") == "current_mcr":
        class_result = classify_producer_current_rule(class_input)
    else:
        class_result = classify_producer_spreadsheet_rule(class_input)
    rule_source = class_result.rule_source

    proposal.classification_json = {
        "group_code": class_result.group_code,
        "rule_source": rule_source,
        "total_rba": str(proposal.total_rba),
        "agro_revenue_share": str(proposal.agro_revenue_share),
    }
    proposal.calculated_at = timezone.now()
    proposal.save()
    return proposal

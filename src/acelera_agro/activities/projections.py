"""10-year activity projection stubs: agriculture, beef, dairy."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def _d(value) -> Decimal:
    return Decimal(str(value))


def agriculture_projection(
    *,
    base_revenue: Decimal,
    base_expense: Decimal,
    years: int = 10,
    revenue_growth: Decimal = Decimal("0.02"),
    expense_growth: Decimal = Decimal("0.015"),
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    revenue = _d(base_revenue)
    expense = _d(base_expense)
    for year in range(1, years + 1):
        rows.append(
            {
                "year": year,
                "activity_kind": "agriculture",
                "revenue": str(revenue.quantize(Decimal("0.01"))),
                "expense": str(expense.quantize(Decimal("0.01"))),
                "detail": {"module": "agriculture"},
            }
        )
        revenue = (revenue * (Decimal("1") + revenue_growth)).quantize(Decimal("0.01"))
        expense = (expense * (Decimal("1") + expense_growth)).quantize(Decimal("0.01"))
    return rows


def herd_evolution_stub(
    *,
    initial_herd: int = 50,
    years: int = 10,
    annual_growth_rate: Decimal = Decimal("0.05"),
) -> list[dict[str, Any]]:
    herd = Decimal(initial_herd)
    rows: list[dict[str, Any]] = []
    for year in range(1, years + 1):
        rows.append(
            {
                "year": year,
                "herd_size": int(herd.to_integral_value()),
            }
        )
        herd = herd * (Decimal("1") + annual_growth_rate)
    return rows


def forage_support_stub(
    *,
    herd_size: int,
    ha_per_head: Decimal = Decimal("1.5"),
) -> dict[str, Any]:
    required_ha = (Decimal(herd_size) * ha_per_head).quantize(Decimal("0.01"))
    return {
        "herd_size": herd_size,
        "ha_per_head": str(ha_per_head),
        "required_forage_ha": str(required_ha),
    }


def beef_investment_budget_defaults(
    *,
    financed_amount: Decimal | None = None,
) -> list[dict[str, Any]]:
    """Default investment budget lines for GTM beef cattle (BB Pronaf Investimento)."""
    total = _d(financed_amount or Decimal("22032.00"))
    pasture = (total * Decimal("0.45")).quantize(Decimal("0.01"))
    fencing = (total * Decimal("0.25")).quantize(Decimal("0.01"))
    corral = (total * Decimal("0.20")).quantize(Decimal("0.01"))
    at = (total - pasture - fencing - corral).quantize(Decimal("0.01"))
    return [
        {
            "description": "Reforma de pastagem / solo",
            "amount": str(pasture),
            "block": "fixed",
            "category": "pasture",
        },
        {
            "description": "Cercas",
            "amount": str(fencing),
            "block": "fixed",
            "category": "fencing",
        },
        {
            "description": "Curral / manejo",
            "amount": str(corral),
            "block": "semi_fixed",
            "category": "corral",
        },
        {
            "description": "Assistência técnica",
            "amount": str(at),
            "block": "other",
            "category": "technical_assistance",
        },
    ]


def beef_cattle_projection(
    *,
    base_revenue: Decimal,
    base_expense: Decimal,
    initial_herd: int = 50,
    years: int = 10,
    financed_amount: Decimal | None = None,
) -> list[dict[str, Any]]:
    """10-year beef cattle projection with herd, forage and investment budget detail."""
    herd = herd_evolution_stub(initial_herd=initial_herd, years=years)
    budget = beef_investment_budget_defaults(financed_amount=financed_amount)
    rows: list[dict[str, Any]] = []
    revenue = _d(base_revenue)
    expense = _d(base_expense)
    for year in range(1, years + 1):
        h = herd[year - 1]["herd_size"]
        rows.append(
            {
                "year": year,
                "activity_kind": "beef_cattle",
                "revenue": str(revenue.quantize(Decimal("0.01"))),
                "expense": str(expense.quantize(Decimal("0.01"))),
                "detail": {
                    "module": "beef_cattle",
                    "credit_purpose": "investment",
                    "herd_size": h,
                    "forage": forage_support_stub(herd_size=h),
                    "investment_budget": budget if year == 1 else None,
                },
            }
        )
        revenue = (revenue * Decimal("1.03")).quantize(Decimal("0.01"))
        expense = (expense * Decimal("1.02")).quantize(Decimal("0.01"))
    return rows


def dairy_cattle_projection(
    *,
    base_revenue: Decimal,
    base_expense: Decimal,
    initial_herd: int = 30,
    years: int = 10,
) -> list[dict[str, Any]]:
    herd = herd_evolution_stub(initial_herd=initial_herd, years=years)
    rows: list[dict[str, Any]] = []
    revenue = _d(base_revenue)
    expense = _d(base_expense)
    for year in range(1, years + 1):
        h = herd[year - 1]["herd_size"]
        rows.append(
            {
                "year": year,
                "activity_kind": "dairy_cattle",
                "revenue": str(revenue.quantize(Decimal("0.01"))),
                "expense": str(expense.quantize(Decimal("0.01"))),
                "detail": {
                    "herd_size": h,
                    "forage": forage_support_stub(herd_size=h, ha_per_head=Decimal("1.2")),
                    "vbp_factor": "0.70",
                },
            }
        )
        revenue = (revenue * Decimal("1.025")).quantize(Decimal("0.01"))
        expense = (expense * Decimal("1.018")).quantize(Decimal("0.01"))
    return rows


def attach_projections_to_proposal(proposal, rows: list[dict[str, Any]]) -> int:
    """Persist ActivityProjection rows; returns count created."""
    from acelera_agro.proposals.models import ActivityProjection

    created = 0
    for row in rows:
        _, was_created = ActivityProjection.objects.update_or_create(
            proposal=proposal,
            activity_kind=row["activity_kind"],
            year=row["year"],
            defaults={
                "revenue": Decimal(row["revenue"]),
                "expense": Decimal(row["expense"]),
                "detail": row.get("detail") or {},
            },
        )
        if was_created:
            created += 1
    return created

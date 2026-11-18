"""calculate_proposal service vs engine test_case_01 fixture."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from acelera_agro.proposals.models import (
    ActivityProjection,
    ExistingDebt,
    Proponent,
    Proposal,
)
from acelera_agro.proposals.services import calculate_proposal

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "engine" / "test_case_01.json"
)


def _d(value) -> Decimal:
    return Decimal(str(value))


@pytest.fixture
def case() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.django_db
def test_calculate_proposal_matches_test_case_01(
    organization, office, membership, catalog, tenant_ctx, case
):
    proponent = Proponent.objects.create(
        organization=organization,
        full_name=case["proponent"]["name"],
        document_number=case["proponent"]["cpf_masked"],
    )
    proposal = Proposal.objects.create(
        office=office,
        organization=organization,
        proponent=proponent,
        bank_profile=catalog["profiles"]["bb"],
        credit_line=catalog["credit_lines"]["pronaf_eco"],
        ruleset=catalog["ruleset"],
        financed_amount=_d(case["investment"]["financed_amount"]),
        annual_rate=_d(case["proposal_schedule"]["annual_rate"]),
        term_years=int(case["proposal_schedule"]["term_years"]),
        grace_years=int(case["proposal_schedule"]["grace_years"]),
        charge_interest_during_grace=bool(
            case["proposal_schedule"]["charge_interest_during_grace"]
        ),
        family_maintenance=_d("14400.00"),
        total_rba=_d(case["classification"]["total_rba"]),
        agro_revenue_share=_d(case["classification"]["agro_revenue_share"]),
        created_by=membership.user,
    )

    for debt in case["existing_debts"]:
        ExistingDebt.objects.create(
            proposal=proposal,
            outstanding_balance=_d(debt["outstanding_balance"]),
            annual_rate=_d(debt["annual_rate"]),
            remaining_term_years=int(debt["remaining_term_years"]),
            grace_years=int(debt["grace_years"]),
        )

    # Seed capacity years 1 and 4 activity rows from fixture
    for row in case["capacity_years"]:
        ActivityProjection.objects.create(
            proposal=proposal,
            activity_kind=ActivityProjection.ActivityKind.AGRICULTURE,
            year=int(row["year"]),
            revenue=_d(row["total_revenue"]),
            expense=_d(row["activity_expense"]),
        )

    calculate_proposal(proposal)
    proposal.refresh_from_db()

    expected = case["expected_schedule"]
    assert len(proposal.schedule_json) == len(expected["interest"])
    for row, exp_i, exp_p in zip(
        proposal.schedule_json, expected["interest"], expected["principal"], strict=True
    ):
        assert _d(row["interest"]) == _d(exp_i)
        assert _d(row["principal"]) == _d(exp_p)

    # Capacity for years present in fixture (1 and 4)
    by_year = {int(r["year"]): r for r in proposal.capacity_json}
    for row in case["capacity_years"]:
        year = int(row["year"])
        assert _d(by_year[year]["surplus"]) == _d(row["expected_surplus"])
        assert _d(by_year[year]["total_expense"]) == _d(row["expected_total_expense"])

    assert proposal.classification_json["group_code"] == case["classification"][
        "expected_spreadsheet_group"
    ]
    assert proposal.calculated_at is not None

"""Acceptance tests for engine test_case_01 (anonymized BB reference)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from acelera_agro.engine import (
    CapacityYearInput,
    ClassificationInput,
    DebtInput,
    ProposalScheduleInput,
    amortize_existing_debts,
    build_proposal_schedule,
    classify_producer_spreadsheet_rule,
    compute_payment_capacity,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "fixtures" / "engine" / "test_case_01.json"
)


@pytest.fixture(scope="module")
def case() -> dict:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _d(value: str | int | float) -> Decimal:
    return Decimal(str(value))


def test_proposal_schedule_matches_fixture_to_the_cent(case: dict) -> None:
    cfg = case["proposal_schedule"]
    schedule = build_proposal_schedule(
        ProposalScheduleInput(
            financed_amount=_d(cfg["financed_amount"]),
            annual_rate=_d(cfg["annual_rate"]),
            term_years=int(cfg["term_years"]),
            grace_years=int(cfg["grace_years"]),
            charge_interest_during_grace=bool(cfg["charge_interest_during_grace"]),
        )
    )
    expected = case["expected_schedule"]
    assert len(schedule) == len(expected["interest"]) == len(expected["principal"])

    for row, exp_interest, exp_principal in zip(
        schedule, expected["interest"], expected["principal"], strict=True
    ):
        assert row.interest == _d(exp_interest)
        assert row.principal == _d(exp_principal)

    assert sum((row.interest for row in schedule), Decimal("0.00")) == _d(
        expected["interest_sum"]
    )
    assert sum((row.principal for row in schedule), Decimal("0.00")) == _d(
        expected["principal_sum"]
    )
    assert schedule[-1].balance == Decimal("0.00")


def test_existing_debt_annual_principals_and_interest(case: dict) -> None:
    debts = [
        DebtInput(
            outstanding_balance=_d(item["outstanding_balance"]),
            annual_rate=_d(item["annual_rate"]),
            remaining_term_years=int(item["remaining_term_years"]),
            grace_years=int(item["grace_years"]),
        )
        for item in case["existing_debts"]
    ]
    result = amortize_existing_debts(debts, horizon_years=5)
    expected = case["expected_debt"]

    assert result["annual_principal_by_debt"] == [
        _d(v) for v in expected["annual_principal_by_debt"]
    ]
    for year in (1, 2, 3):
        assert result["years"][year - 1]["principal"] == _d(
            expected["principal_years_1_to_3"]
        )
    for year in (4, 5):
        assert result["years"][year - 1]["principal"] == _d(
            expected["principal_years_4_to_5"]
        )
    for year_row, exp_interest in zip(
        result["years"], expected["interest"], strict=True
    ):
        assert year_row["interest"] == _d(exp_interest)


def test_payment_capacity_years_i_and_iv(case: dict) -> None:
    years = [
        CapacityYearInput(
            year=int(row["year"]),
            total_revenue=_d(row["total_revenue"]),
            activity_expense=_d(row["activity_expense"]),
            family_maintenance=_d(row["family_maintenance"]),
            proposal_payment=_d(row["proposal_payment"]),
            existing_debt_principal=_d(row["existing_debt_principal"]),
            existing_debt_interest=_d(row["existing_debt_interest"]),
        )
        for row in case["capacity_years"]
    ]
    results = compute_payment_capacity(years)
    assert len(results) == 2

    for result, row in zip(results, case["capacity_years"], strict=True):
        assert result.year == int(row["year"])
        assert result.total_expense == _d(row["expected_total_expense"])
        assert result.surplus == _d(row["expected_surplus"])

    assert results[0].year == 1
    assert results[0].surplus == _d("62752.73")
    assert results[1].year == 4
    assert results[1].surplus == _d("101610.90")


def test_spreadsheet_classification_grupo_af(case: dict) -> None:
    cfg = case["classification"]
    result = classify_producer_spreadsheet_rule(
        ClassificationInput(
            total_rba=_d(cfg["total_rba"]),
            agro_revenue_share=_d(cfg["agro_revenue_share"]),
        )
    )
    assert result.group_code == cfg["expected_spreadsheet_group"]
    assert result.group_code == "AF"
    assert result.rule_source == "spreadsheet_legacy"

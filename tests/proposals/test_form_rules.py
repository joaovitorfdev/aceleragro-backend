"""Rule evaluator for the proposal form schema."""

from __future__ import annotations

import pytest

from acelera_agro.proposals import form_rules
from acelera_agro.proposals.form_rules import RuleContext, evaluate_rule


def _values(**overrides):
    values = {
        "proponent": {"person_type": "individual", "marital_status": "married"},
        "properties": [
            {"ownership_type": "registered_deed", "area_ha": "10.0000"},
            {"ownership_type": "lease"},
        ],
        "credit": {"credit_purpose": "investment"},
        "debts": [],
        "review": {},
    }
    values.update(overrides)
    return values


def test_schema_is_loaded_once():
    assert form_rules.load_schema() is form_rules.load_schema()
    assert form_rules.load_schema()["version"] == 1


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        ({"field": "proponent.marital_status", "op": "eq", "value": "married"}, True),
        ({"field": "proponent.marital_status", "op": "eq", "value": "single"}, False),
        ({"field": "proponent.marital_status", "op": "ne", "value": "single"}, True),
        ({"field": "proponent.marital_status", "op": "ne", "value": "married"}, False),
        ({"field": "proponent.marital_status", "op": "in", "value": ["married", "x"]}, True),
        ({"field": "proponent.marital_status", "op": "in", "value": ["single"]}, False),
        ({"field": "proponent.marital_status", "op": "not_in", "value": ["single"]}, True),
        ({"field": "proponent.marital_status", "op": "not_in", "value": ["married"]}, False),
        ({"field": "proponent.full_name", "op": "filled"}, False),
        ({"field": "proponent.full_name", "op": "empty"}, True),
        ({"field": "proponent.marital_status", "op": "filled"}, True),
        # Missing paths: eq/in are false, ne/not_in are true.
        ({"field": "proponent.nope", "op": "eq", "value": "x"}, False),
        ({"field": "proponent.nope", "op": "in", "value": ["x"]}, False),
        ({"field": "proponent.nope", "op": "ne", "value": "x"}, True),
        ({"field": "proponent.nope", "op": "not_in", "value": ["x"]}, True),
    ],
)
def test_basic_ops_with_absolute_paths(rule, expected):
    ctx = RuleContext(_values(), "proponent")
    assert evaluate_rule(rule, ctx) is expected


def test_all_and_any_combinators():
    ctx = RuleContext(_values(), "proponent")
    yes = {"field": "proponent.marital_status", "op": "eq", "value": "married"}
    no = {"field": "proponent.marital_status", "op": "eq", "value": "single"}
    assert evaluate_rule({"all": [yes, yes]}, ctx)
    assert not evaluate_rule({"all": [yes, no]}, ctx)
    assert evaluate_rule({"any": [no, yes]}, ctx)
    assert not evaluate_rule({"any": [no, no]}, ctx)
    assert evaluate_rule({"all": [{"any": [no, yes]}, yes]}, ctx)
    assert evaluate_rule(None, ctx)


def test_relative_paths_and_repeatable_indexes():
    values = _values()
    rule = {"field": "@.ownership_type", "op": "eq", "value": "lease"}
    assert not evaluate_rule(rule, RuleContext(values, "properties", 0))
    assert evaluate_rule(rule, RuleContext(values, "properties", 1))
    # Absolute paths with an index work from anywhere.
    absolute = {"field": "properties.0.area_ha", "op": "filled"}
    assert evaluate_rule(absolute, RuleContext(values, "credit"))
    assert not evaluate_rule(
        {"field": "properties.1.area_ha", "op": "filled"}, RuleContext(values, "credit")
    )
    # Out-of-range index resolves to "missing".
    assert not evaluate_rule(
        {"field": "properties.9.area_ha", "op": "filled"}, RuleContext(values, "credit")
    )


def test_filled_treats_blank_as_empty_but_not_false_or_zero():
    values = _values(review={"technician_declaration": False})
    ctx = RuleContext(values, "review")
    assert evaluate_rule({"field": "@.technician_declaration", "op": "filled"}, ctx)
    assert form_rules.is_empty("  ")
    assert not form_rules.is_empty(0)


def test_spouse_fields_visibility_follows_marital_status():
    spouse = form_rules.get_field("proponent", "spouse_name")
    for status, visible in [
        ("married", True),
        ("stable_union", True),
        ("single", False),
        ("divorced", False),
        (None, False),
    ]:
        proponent = {"person_type": "individual"}
        if status:
            proponent["marital_status"] = status
        ctx = RuleContext({"proponent": proponent}, "proponent")
        assert form_rules.is_visible(spouse, ctx) is visible
        assert form_rules.is_required(spouse, ctx) is visible


def test_marital_status_hidden_for_companies():
    field = form_rules.get_field("proponent", "marital_status")
    ctx = RuleContext({"proponent": {"person_type": "company"}}, "proponent")
    assert not form_rules.is_visible(field, ctx)
    assert not form_rules.is_required(field, ctx)


def test_repeatable_item_conditionals():
    values = _values()
    lease_owner = form_rules.get_field("properties", "lease_owner_name")
    matricula = form_rules.get_field("properties", "matricula")
    deed = RuleContext(values, "properties", 0)
    lease = RuleContext(values, "properties", 1)
    assert not form_rules.is_visible(lease_owner, deed)
    assert form_rules.is_required(lease_owner, lease)
    assert form_rules.is_visible(matricula, deed)
    assert not form_rules.is_visible(matricula, lease)
    # `matricula` is visible but optional.
    assert not form_rules.is_required(matricula, deed)


def test_grace_years_only_for_investment():
    field = form_rules.get_field("credit", "grace_years")
    inv = RuleContext({"credit": {"credit_purpose": "investment"}}, "credit")
    wc = RuleContext({"credit": {"credit_purpose": "working_capital"}}, "credit")
    assert form_rules.is_visible(field, inv)
    assert not form_rules.is_visible(field, wc)


def test_missing_required_lists_only_visible_required_fields():
    values = {
        "proponent": {"person_type": "individual", "marital_status": "single", "full_name": "A"},
        "properties": [{"ownership_type": "lease"}],
        "credit": {},
        "debts": [{}],
        "review": {},
    }
    missing = form_rules.missing_required(values)
    assert "proponent.document_number" in missing
    assert "proponent.full_name" not in missing
    assert "proponent.spouse_name" not in missing  # hidden for single
    assert "properties.0.lease_owner_name" in missing
    assert "properties.0.matricula" not in missing  # hidden for lease
    assert "debts.0.outstanding_balance" in missing
    assert "review.technician_declaration" in missing  # boolean needs True
    assert "credit.grace_years" not in missing

    values["review"] = {"technician_declaration": True}
    assert "review.technician_declaration" not in form_rules.missing_required(values)

"""Bank profile seeds and conditional checklist resolution."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from acelera_agro.catalog.bank_profiles import BB_DOCUMENT_CHECKLIST
from acelera_agro.catalog.models import BankProfile, CreditLine


@pytest.mark.django_db
def test_seed_catalog_creates_bb_and_stubs():
    call_command("seed_catalog")
    codes = set(BankProfile.objects.values_list("code", flat=True))
    assert codes == {"bb", "caixa", "basa", "sicredi", "sicoob"}

    bb = BankProfile.objects.get(code="bb")
    assert bb.is_active is True
    assert bb.document_checklist == BB_DOCUMENT_CHECKLIST
    assert "section_01_identification" in bb.pdf_sections
    assert CreditLine.objects.filter(bank_profile=bb).count() >= 1

    for code in ("caixa", "basa", "sicredi", "sicoob"):
        stub = BankProfile.objects.get(code=code)
        assert stub.extra_config.get("scaffold") is True
        assert stub.document_checklist == []


@pytest.mark.django_db
def test_bb_checklist_conditional_on_ownership_and_marital(catalog):
    bb = catalog["profiles"]["bb"]
    base = bb.required_document_kinds(ownership_type="lease", marital_status="single")
    assert "id_document" in base
    assert "public_deed" not in base
    assert "marriage_certificate" not in base

    deed = bb.required_document_kinds(
        ownership_type="registered_deed", marital_status="single"
    )
    assert "public_deed" in deed
    assert "land_registry" in deed
    assert "incra_ccir" in deed

    married = bb.required_document_kinds(
        ownership_type="lease", marital_status="married"
    )
    assert "marriage_certificate" in married

    union = bb.required_document_kinds(
        ownership_type="possession_incra", marital_status="stable_union"
    )
    assert "possession_title" in union
    assert "union_declaration" in union

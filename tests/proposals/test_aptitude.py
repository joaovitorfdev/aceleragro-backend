"""Bank aptitude evaluation — multi-bank tags for GTM export strip."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from acelera_agro.catalog.models import BankProfile
from acelera_agro.documents.models import Document, DocumentKind
from acelera_agro.proposals.aptitude import (
    STATUS_APTO,
    STATUS_EM_BREVE,
    STATUS_FORA,
    STATUS_PENDENTE,
    evaluate_all_banks,
    evaluate_bank_aptitude,
)
from acelera_agro.proposals.models import Proponent, Property, Proposal
from acelera_agro.proposals.services import calculate_proposal


def _attach_kind(proposal, office, kind: str, name: str) -> Document:
    return Document.objects.create(
        office=office,
        proposal=proposal,
        s3_key=f"k/{name}",
        original_filename=name,
        detected_kind=kind,
        detected_kind_confidence=Decimal("0.95"),
        extraction_status=Document.ExtractionStatus.EXTRACTED,
    )


@pytest.mark.django_db
def test_scaffold_banks_are_em_breve(catalog, office, organization, tenant_ctx):
    proposal = Proposal.objects.create(
        office=office,
        organization=organization,
        bank_profile=catalog["profiles"]["bb"],
        credit_purpose=Proposal.CreditPurpose.INVESTMENT,
        activity_kind=Proposal.ActivityKind.BEEF_CATTLE,
    )
    basa = catalog["profiles"]["basa"]
    result = evaluate_bank_aptitude(proposal, basa)
    assert result.status == STATUS_EM_BREVE
    assert result.exportable is False


@pytest.mark.django_db
def test_bb_pendente_without_docs(catalog, office, organization, tenant_ctx):
    proposal = Proposal.objects.create(
        office=office,
        organization=organization,
        bank_profile=catalog["profiles"]["bb"],
        credit_purpose=Proposal.CreditPurpose.INVESTMENT,
        activity_kind=Proposal.ActivityKind.BEEF_CATTLE,
        financed_amount=Decimal("22032.00"),
    )
    bb = catalog["profiles"]["bb"]
    result = evaluate_bank_aptitude(proposal, bb)
    assert result.status == STATUS_PENDENTE
    assert "id_document" in result.missing_document_kinds or any(
        r["code"].startswith("missing_") for r in result.reasons
    )


@pytest.mark.django_db
def test_bb_fora_enquadramento_when_group_other(
    catalog, office, organization, municipality, tenant_ctx
):
    proponent = Proponent.objects.create(
        organization=organization,
        full_name="Produtor Teste 01",
        document_number="000.000.000-00",
        marital_status=Proponent.MaritalStatus.SINGLE,
    )
    prop = Property.objects.create(
        organization=organization,
        proponent=proponent,
        name="Fazenda Stub",
        ownership_type=Property.OwnershipType.LEASE,
        municipality=municipality,
        area_ha=Decimal("25.5"),
    )
    proposal = Proposal.objects.create(
        office=office,
        organization=organization,
        proponent=proponent,
        property=prop,
        bank_profile=catalog["profiles"]["bb"],
        credit_line=catalog["credit_lines"]["pronaf_investimento"],
        credit_purpose=Proposal.CreditPurpose.INVESTMENT,
        activity_kind=Proposal.ActivityKind.BEEF_CATTLE,
        financed_amount=Decimal("22032.00"),
        term_years=10,
        grace_years=3,
        annual_rate=Decimal("0.03"),
        total_rba=Decimal("5000000.00"),
        agro_revenue_share=Decimal("0.50"),
        family_maintenance=Decimal("12000.00"),
    )
    for kind, name in [
        (DocumentKind.ID_DOCUMENT, "rg.pdf"),
        (DocumentKind.CPF, "cpf.pdf"),
        (DocumentKind.PROOF_OF_RESIDENCE, "residencia.pdf"),
        (DocumentKind.CAF, "caf.pdf"),
        (DocumentKind.CAR, "car.pdf"),
        (DocumentKind.ITR, "itr.pdf"),
        (DocumentKind.BUDGET_QUOTE, "orcamento.pdf"),
    ]:
        _attach_kind(proposal, office, kind, name)

    # High RBA + low agro share → OTHER under spreadsheet rule
    calculate_proposal(proposal)
    bb = catalog["profiles"]["bb"]
    result = evaluate_bank_aptitude(proposal, bb)
    assert result.group_code == "OTHER"
    assert result.status in {STATUS_FORA, STATUS_PENDENTE}
    assert any(r["code"] == "group_outside_product" for r in result.reasons)


@pytest.mark.django_db
def test_bb_apto_and_exportable_after_review(
    catalog, office, organization, municipality, tenant_ctx
):
    proponent = Proponent.objects.create(
        organization=organization,
        full_name="Produtor Teste 01",
        document_number="000.000.000-00",
        marital_status=Proponent.MaritalStatus.SINGLE,
        address="Rua Teste 100",
    )
    prop = Property.objects.create(
        organization=organization,
        proponent=proponent,
        name="Fazenda Stub",
        ownership_type=Property.OwnershipType.LEASE,
        lease_owner_name="Arrendador Stub",
        municipality=municipality,
        area_ha=Decimal("25.5"),
    )
    proposal = Proposal.objects.create(
        office=office,
        organization=organization,
        proponent=proponent,
        property=prop,
        bank_profile=catalog["profiles"]["bb"],
        credit_line=catalog["credit_lines"]["pronaf_investimento"],
        ruleset=catalog["ruleset"],
        credit_purpose=Proposal.CreditPurpose.INVESTMENT,
        activity_kind=Proposal.ActivityKind.BEEF_CATTLE,
        financed_amount=Decimal("22032.00"),
        term_years=10,
        grace_years=3,
        annual_rate=Decimal("0.03"),
        total_rba=Decimal("215418.00"),
        agro_revenue_share=Decimal("0.80"),
        family_maintenance=Decimal("12000.00"),
        form_extra={"review": {"technician_declaration": True}},
    )
    for kind, name in [
        (DocumentKind.ID_DOCUMENT, "rg.pdf"),
        (DocumentKind.CPF, "cpf.pdf"),
        (DocumentKind.PROOF_OF_RESIDENCE, "residencia.pdf"),
        (DocumentKind.CAF, "caf.pdf"),
        (DocumentKind.CAR, "car.pdf"),
        (DocumentKind.ITR, "itr.pdf"),
        (DocumentKind.BUDGET_QUOTE, "orcamento.pdf"),
    ]:
        _attach_kind(proposal, office, kind, name)

    from acelera_agro.proposals.models import ActivityProjection

    for year in range(1, 11):
        ActivityProjection.objects.create(
            proposal=proposal,
            activity_kind="beef_cattle",
            year=year,
            revenue=Decimal("80000.00"),
            expense=Decimal("40000.00"),
        )

    calculate_proposal(proposal)
    bb = catalog["profiles"]["bb"]
    before = evaluate_bank_aptitude(proposal, bb)
    assert before.status == STATUS_APTO, before.reasons
    assert before.exportable is False

    proposal.technician_reviewed_at = timezone.now()
    proposal.save(update_fields=["technician_reviewed_at"])
    after = evaluate_bank_aptitude(proposal, bb)
    assert after.status == STATUS_APTO
    assert after.exportable is True
    assert "bb" in after.export_formats


@pytest.mark.django_db
def test_seed_includes_caixa_and_pronaf_investimento():
    call_command("seed_catalog")
    codes = set(BankProfile.objects.values_list("code", flat=True))
    assert "caixa" in codes
    assert "bb" in codes
    bb = BankProfile.objects.get(code="bb")
    assert bb.extra_config.get("gtm_product", {}).get("activity_kind") == "beef_cattle"
    assert bb.credit_lines.filter(code="pronaf_investimento").exists()


@pytest.mark.django_db
def test_bank_aptitude_api(form_client, catalog, office, organization, tenant_ctx):
    proposal = Proposal.objects.create(
        office=office,
        organization=organization,
        bank_profile=catalog["profiles"]["bb"],
    )
    resp = form_client.get(f"/api/proposals/{proposal.id}/bank-aptitude")
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert "items" in body
    codes = {item["bank_code"] for item in body["items"]}
    assert "bb" in codes
    assert "basa" in codes

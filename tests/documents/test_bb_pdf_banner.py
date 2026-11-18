"""BB PDF formal layout + in-memory banner (not persisted)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.utils import timezone

from acelera_agro.documents.pdf import PdfGenerationError, generate_bb_proposal_pdf
from acelera_agro.proposals.models import Proponent, Property, Proposal
from acelera_agro.proposals.services import calculate_proposal


def _png_bytes() -> bytes:
    # Minimal valid 1x1 PNG
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


@pytest.mark.django_db
def test_bb_pdf_requires_review(catalog, office, organization, tenant_ctx):
    proposal = Proposal.objects.create(
        office=office,
        organization=organization,
        bank_profile=catalog["profiles"]["bb"],
        financed_amount=Decimal("1000.00"),
    )
    with pytest.raises(PdfGenerationError) as exc:
        generate_bb_proposal_pdf(proposal)
    assert exc.value.code == "not_reviewed"


@pytest.mark.django_db
def test_bb_pdf_with_in_memory_banner(
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
        technician_reviewed_at=timezone.now(),
    )
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

    pdf = generate_bb_proposal_pdf(proposal, banner_bytes=_png_bytes())
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 500

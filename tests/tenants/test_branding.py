"""Marco T2 — organization profile + logo/banner upload."""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from acelera_agro.documents.storage import get_object_bytes
from acelera_agro.tenants.services import create_office_for_organization, create_tenant


def _png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )


@pytest.mark.django_db
def test_update_org_profile_and_upload_banner(client, municipality, inside_coords):
    created = create_tenant(
        organization_name="Brand Org Stub",
        organization_trade_name="Brand Stub",
        organization_cnpj="11222333000181",
        owner_email="brand@example.com",
        owner_password="password123",
        owner_full_name="Brand Owner",
    )
    create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office Brand",
        municipality_ibge=municipality.ibge_code,
        address="Rua Brand 1",
        phone="(62) 1111-1111",
    )
    lat, lng = inside_coords
    login = client.post(
        "/api/auth/login",
        data={
            "email": "brand@example.com",
            "password": "password123",
            "device_fingerprint": "fp-brand",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {login.json()['access_token']}"

    patched = client.patch(
        "/api/tenants/me",
        data={"name": "Brand Org Updated", "trade_name": "Updated Stub"},
        content_type="application/json",
    )
    assert patched.status_code == 200, patched.content
    body = patched.json()
    assert body["name"] == "Brand Org Updated"
    assert body["trade_name"] == "Updated Stub"
    assert body["cnpj"] == "11222333000181"

    upload = client.post(
        "/api/tenants/me/banner",
        data={"file": SimpleUploadedFile("banner.png", _png(), content_type="image/png")},
    )
    assert upload.status_code == 200, upload.content
    banner_key = upload.json()["banner_key"]
    assert banner_key.startswith(f"orgs/{created.organization.id}/banner/")
    assert get_object_bytes(banner_key) == _png()

    cleared = client.delete("/api/tenants/me/banner")
    assert cleared.status_code == 200
    assert cleared.json()["banner_key"] == ""


@pytest.mark.django_db
def test_bb_export_uses_org_banner_when_no_override(
    client_factory,
    catalog,
    municipality,
    office,
    organization,
    membership,
    tenant_ctx,
):
    from decimal import Decimal

    from django.utils import timezone

    from acelera_agro.documents.storage import put_object_bytes
    from acelera_agro.proposals.models import (
        ActivityProjection,
        Proponent,
        Property,
        Proposal,
    )
    from acelera_agro.proposals.services import calculate_proposal

    key = f"orgs/{organization.id}/banner/test.png"
    put_object_bytes(key=key, data=_png(), content_type="image/png")
    organization.banner_key = key
    organization.save(update_fields=["banner_key"])

    proponent = Proponent.objects.create(
        organization=organization,
        full_name="Produtor Brand Stub",
        document_number="000.000.000-00",
        marital_status=Proponent.MaritalStatus.SINGLE,
        address="Rua Stub 1",
    )
    prop = Property.objects.create(
        organization=organization,
        proponent=proponent,
        name="Fazenda Brand",
        ownership_type=Property.OwnershipType.LEASE,
        lease_owner_name="Arrendador Stub",
        municipality=municipality,
        area_ha=Decimal("10.0"),
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
        financed_amount=Decimal("10000.00"),
        term_years=5,
        grace_years=1,
        annual_rate=Decimal("0.03"),
        form_extra={"review": {"technician_declaration": True}},
        technician_reviewed_at=timezone.now(),
    )
    for year in range(1, 6):
        ActivityProjection.objects.create(
            proposal=proposal,
            activity_kind="beef_cattle",
            year=year,
            revenue=Decimal("50000.00"),
            expense=Decimal("20000.00"),
        )
    calculate_proposal(proposal)

    client = client_factory("tech@example.com", fingerprint="fp-brand-pdf")
    response = client.get(f"/api/proposals/{proposal.id}/pdf/bb")
    assert response.status_code == 200, response.content
    assert response.content[:4] == b"%PDF"

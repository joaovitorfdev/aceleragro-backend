"""Batch upload without kind; stub classify sets detected_kind; ownership suggestion."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import Client

from acelera_agro.documents.models import Document
from acelera_agro.extraction.services import suggest_ownership_type
from acelera_agro.proposals.models import Property, Proponent, Proposal


@pytest.fixture
def auth_client(user, membership, office, inside_coords):
    lat, lng = inside_coords
    client = Client()
    login = client.post(
        "/api/auth/login",
        data={
            "email": "tech@example.com",
            "password": "test-password-123",
            "device_fingerprint": "fp-docs-1",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    token = login.json()["access_token"]
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    return client


@pytest.mark.django_db
def test_batch_presign_without_kind_then_classify_and_suggest_ownership(
    auth_client,
    organization,
    office,
    municipality,
    catalog,
    tenant_ctx,
):
    proponent = Proponent.objects.create(
        organization=organization,
        full_name="Produtor Docs Stub",
        marital_status="single",
    )
    prop = Property.objects.create(
        organization=organization,
        proponent=proponent,
        municipality=municipality,
        name="Fazenda Stub",
        ownership_type=Property.OwnershipType.OTHER,
        area_ha=Decimal("0"),
    )
    proposal = Proposal.objects.create(
        office=office,
        organization=organization,
        proponent=proponent,
        property=prop,
        bank_profile=catalog["profiles"]["bb"],
        credit_line=catalog["credit_lines"]["pronaf_eco"],
    )

    response = auth_client.post(
        "/api/documents/presign",
        data={
            "proposal_id": proposal.id,
            "files": [
                {
                    "filename": "escritura_publica.pdf",
                    "content_type": "application/pdf",
                    "size": 1200,
                },
                {
                    "filename": "car_reserva.pdf",
                    "content_type": "application/pdf",
                    "size": 800,
                },
            ],
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="batch-upload-1",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert len(body["items"]) == 2
    # Kind must not be required / set by client on create
    docs = list(Document.objects.filter(proposal=proposal).order_by("id"))
    assert len(docs) == 2
    assert all(d.detected_kind == "unknown" for d in docs)

    # Idempotent replay
    replay = auth_client.post(
        "/api/documents/presign",
        data={
            "proposal_id": proposal.id,
            "files": [
                {
                    "filename": "escritura_publica.pdf",
                    "content_type": "application/pdf",
                    "size": 1200,
                },
                {
                    "filename": "car_reserva.pdf",
                    "content_type": "application/pdf",
                    "size": 800,
                },
            ],
        },
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="batch-upload-1",
    )
    assert replay.status_code == 201
    assert Document.objects.filter(proposal=proposal).count() == 2

    run = auth_client.post(
        "/api/extractions/run",
        data={"proposal_id": proposal.id, "classify_only": False},
        content_type="application/json",
    )
    assert run.status_code == 200, run.content
    result = run.json()
    kinds = {d["detected_kind"] for d in result["documents"]}
    assert "public_deed" in kinds
    assert "car" in kinds
    assert result["ownership_type_suggestion"] == "registered_deed"

    prop.refresh_from_db()
    assert prop.ownership_type == Property.OwnershipType.REGISTERED_DEED


@pytest.mark.django_db
def test_suggest_ownership_type_from_kinds():
    assert suggest_ownership_type({"purchase_sale_contract"}) == "purchase_sale_contract"
    assert suggest_ownership_type({"possession_title", "car"}) == "possession_incra"
    assert suggest_ownership_type({"cpf", "id_document"}) is None

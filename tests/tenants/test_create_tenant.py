"""Marco T3 — create tenant (org+owner), add office, switch membership."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from acelera_agro.tenants.models import Membership, Municipality, Office, Organization
from acelera_agro.tenants.services import (
    TenantServiceError,
    create_office_for_organization,
    create_tenant,
)

User = get_user_model()


@pytest.fixture
def second_municipality(db):
    return Municipality.objects.create(
        ibge_code="5200050",
        name="Abadia de Goias Stub",
        state_uf="GO",
        fiscal_module_ha=Decimal("20.0000"),
        boundary=json.dumps(
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-49.5, -16.9],
                        [-49.4, -16.9],
                        [-49.4, -16.8],
                        [-49.5, -16.8],
                        [-49.5, -16.9],
                    ]
                ],
            }
        ),
    )


def _create_owner_tenant(**overrides):
    defaults = dict(
        organization_name="Agro Bioflora Stub LTDA",
        organization_trade_name="Agro Bioflora Stub",
        organization_cnpj="12.345.678/0001-95",
        owner_email="owner@example.com",
        owner_password="password123",
        owner_full_name="Owner Stub",
    )
    defaults.update(overrides)
    return create_tenant(**defaults)


@pytest.mark.django_db
def test_create_tenant_service_org_and_owner_only():
    created = _create_owner_tenant()
    assert created.organization.cnpj == "12345678000195"
    assert created.organization.owner_id == created.user.id
    assert Office.objects.filter(organization=created.organization).count() == 0
    assert Membership.objects.filter(user=created.user).count() == 0
    assert User.objects.filter(email="owner@example.com").exists()


@pytest.mark.django_db
def test_create_tenant_rejects_duplicate_cnpj():
    _create_owner_tenant(
        organization_name="Org A",
        organization_cnpj="12345678000195",
        owner_email="a@example.com",
    )
    with pytest.raises(TenantServiceError) as exc:
        _create_owner_tenant(
            organization_name="Org B",
            organization_cnpj="12.345.678/0001-95",
            owner_email="b@example.com",
        )
    assert exc.value.code == "cnpj_taken"


@pytest.mark.django_db
def test_create_tenant_api(client):
    response = client.post(
        "/api/tenants",
        data={
            "organization": {
                "name": "Org API Stub",
                "trade_name": "API Stub",
                "cnpj": "11222333000181",
            },
            "owner": {
                "email": "api-owner@example.com",
                "password": "password123",
                "full_name": "API Owner",
            },
        },
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["organization_id"]
    assert "office_id" not in body
    assert body["email"] == "api-owner@example.com"
    org = Organization.objects.get(pk=body["organization_id"])
    assert org.owner.email == "api-owner@example.com"
    assert Office.objects.filter(organization=org).count() == 0


@pytest.mark.django_db
def test_login_needs_office_then_create_first_office(
    client, municipality, inside_coords
):
    _create_owner_tenant(
        organization_cnpj="99888777000166",
        owner_email="multi@example.com",
    )
    login = client.post(
        "/api/auth/login",
        data={
            "email": "multi@example.com",
            "password": "password123",
            "device_fingerprint": "fp-needs",
        },
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    token_body = login.json()
    assert token_body["needs_office"] is True
    assert token_body["office_id"] is None
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token_body['access_token']}"

    me = client.get("/api/tenants/me")
    assert me.status_code == 200, me.content
    assert me.json()["needs_office"] is True
    assert me.json()["offices"] == []

    lat, lng = inside_coords
    create = client.post(
        "/api/tenants/offices",
        data={
            "name": "Office One",
            "municipality_ibge": municipality.ibge_code,
            "address": "Av One 10",
            "phone": "(62) 4444-4444",
            "device_fingerprint": "fp-first-office",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert create.status_code == 201, create.content
    created = create.json()
    assert created["office"]["id"]
    assert created["access_token"]
    assert created["office_id"] == created["office"]["id"]
    assert created["needs_office"] is False

    active = Membership.objects.get(user__email="multi@example.com", is_active=True)
    assert active.office_id == created["office"]["id"]


@pytest.mark.django_db
def test_add_office_and_switch_membership(
    client, municipality, second_municipality, inside_coords
):
    created = _create_owner_tenant(
        organization_name="Multi Office Org",
        organization_cnpj="88777666000155",
        owner_email="switch@example.com",
    )
    lat, lng = inside_coords
    office_one, _m = create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office One",
        municipality_ibge=municipality.ibge_code,
        address="Av One 10",
        phone="(62) 4444-4444",
    )
    login = client.post(
        "/api/auth/login",
        data={
            "email": "switch@example.com",
            "password": "password123",
            "device_fingerprint": "fp-multi",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {login.json()['access_token']}"

    create = client.post(
        "/api/tenants/offices",
        data={
            "name": "Office Two",
            "municipality_ibge": second_municipality.ibge_code,
            "address": "Av Two 20",
            "phone": "(62) 5555-5555",
        },
        content_type="application/json",
    )
    assert create.status_code == 201, create.content
    office_two_id = create.json()["office"]["id"]
    assert office_two_id != office_one.id

    memberships = client.get("/api/memberships")
    assert memberships.status_code == 200
    rows = memberships.json()
    assert len(rows) == 2
    target = next(m for m in rows if m["office_id"] == office_two_id)
    assert target["is_active"] is False

    switch_lat, switch_lng = Decimal("-16.850000"), Decimal("-49.450000")
    switched = client.post(
        "/api/memberships/switch",
        data={
            "membership_id": target["id"],
            "device_fingerprint": "fp-multi-2",
            "lat": str(switch_lat),
            "lng": str(switch_lng),
        },
        content_type="application/json",
    )
    assert switched.status_code == 200, switched.content
    token_body = switched.json()
    assert token_body["office_id"] == office_two_id
    assert token_body["role"] == Membership.Role.OWNER

    active = Membership.objects.get(user__email="switch@example.com", is_active=True)
    assert active.office_id == office_two_id
    assert Membership.objects.filter(user__email="switch@example.com", is_active=True).count() == 1


@pytest.mark.django_db
def test_add_office_requires_address_and_phone(municipality, second_municipality):
    created = _create_owner_tenant(
        organization_name="Addr Org",
        organization_cnpj="66777888000111",
        owner_email="addr@example.com",
    )
    create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office A",
        municipality_ibge=municipality.ibge_code,
        address="Rua Addr 1",
        phone="(62) 8888-8888",
    )
    with pytest.raises(TenantServiceError) as exc:
        create_office_for_organization(
            organization=created.organization,
            acting_user=created.user,
            name="Office B",
            municipality_ibge=second_municipality.ibge_code,
            address="",
            phone="(62) 9999-9999",
        )
    assert exc.value.code == "office_address_required"


@pytest.mark.django_db
def test_cannot_two_offices_same_municipality(municipality):
    created = _create_owner_tenant(
        organization_name="Same Mun Org",
        organization_cnpj="55444333000122",
        owner_email="same-mun@example.com",
    )
    create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office A",
        municipality_ibge=municipality.ibge_code,
        address="Rua Same 1",
        phone="(62) 6666-6666",
    )
    with pytest.raises(TenantServiceError) as exc:
        create_office_for_organization(
            organization=created.organization,
            acting_user=created.user,
            name="Office B",
            municipality_ibge=municipality.ibge_code,
            address="Rua Same 2",
            phone="(62) 7777-7777",
        )
    assert exc.value.code == "office_municipality_taken"
    assert Office.objects.filter(organization=created.organization).count() == 1

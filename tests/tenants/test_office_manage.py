"""Marco T4 — edit and suspend/reactivate offices."""

from __future__ import annotations

import pytest

from acelera_agro.tenants.models import Office
from acelera_agro.tenants.services import (
    TenantServiceError,
    create_office_for_organization,
    create_tenant,
    set_office_status,
    update_office,
)


@pytest.mark.django_db
def test_update_and_suspend_office_api(client, municipality, inside_coords):
    created = create_tenant(
        organization_name="Manage Org",
        organization_trade_name="",
        organization_cnpj="22333444000155",
        owner_email="manage@example.com",
        owner_password="password123",
        owner_full_name="",
    )
    office, _m = create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office A",
        municipality_ibge=municipality.ibge_code,
        address="Rua A 1",
        phone="(62) 1111-1111",
    )
    lat, lng = inside_coords
    login = client.post(
        "/api/auth/login",
        data={
            "email": "manage@example.com",
            "password": "password123",
            "device_fingerprint": "fp-manage",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {login.json()['access_token']}"

    patched = client.patch(
        f"/api/tenants/offices/{office.id}",
        data={
            "name": "Office A Updated",
            "address": "Rua A 99",
            "phone": "(62) 9999-9999",
            "technical_responsible_name": "Tech Stub",
        },
        content_type="application/json",
    )
    assert patched.status_code == 200, patched.content
    body = patched.json()
    assert body["name"] == "Office A Updated"
    assert body["address"] == "Rua A 99"
    assert body["phone"] == "(62) 9999-9999"
    assert body["municipality"]["ibge_code"] == municipality.ibge_code

    suspended = client.post(
        f"/api/tenants/offices/{office.id}/status",
        data={"status": "suspended"},
        content_type="application/json",
    )
    assert suspended.status_code == 200, suspended.content
    assert suspended.json()["status"] == Office.Status.SUSPENDED

    # Owner can still reactivate while office is suspended (tenant admin path).
    active = client.post(
        f"/api/tenants/offices/{office.id}/status",
        data={"status": "active"},
        content_type="application/json",
    )
    assert active.status_code == 200, active.content
    assert active.json()["status"] == Office.Status.ACTIVE


@pytest.mark.django_db
def test_set_office_status_rejects_invalid(municipality):
    created = create_tenant(
        organization_name="Status Org",
        organization_trade_name="",
        organization_cnpj="33444555000166",
        owner_email="status@example.com",
        owner_password="password123",
        owner_full_name="",
    )
    office, _m = create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office S",
        municipality_ibge=municipality.ibge_code,
        address="Rua S 1",
        phone="(62) 2222-2222",
    )
    with pytest.raises(TenantServiceError) as exc:
        set_office_status(
            organization=created.organization,
            acting_user=created.user,
            office_id=office.id,
            status="inactive",
        )
    assert exc.value.code == "invalid_office_status"


@pytest.mark.django_db
def test_update_office_requires_address(municipality):
    created = create_tenant(
        organization_name="Addr Edit Org",
        organization_trade_name="",
        organization_cnpj="44555666000177",
        owner_email="edit-addr@example.com",
        owner_password="password123",
        owner_full_name="",
    )
    office, _m = create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office E",
        municipality_ibge=municipality.ibge_code,
        address="Rua E 1",
        phone="(62) 3333-3333",
    )
    with pytest.raises(TenantServiceError) as exc:
        update_office(
            organization=created.organization,
            acting_user=created.user,
            office_id=office.id,
            address="   ",
        )
    assert exc.value.code == "office_address_required"

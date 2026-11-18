"""Marco T5 — invite / list / remove office members."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from acelera_agro.tenants.models import Membership
from acelera_agro.tenants.services import create_office_for_organization, create_tenant

User = get_user_model()


@pytest.mark.django_db
def test_invite_list_remove_and_login(client, municipality, inside_coords):
    created = create_tenant(
        organization_name="Team Org",
        organization_trade_name="",
        organization_cnpj="55666777000188",
        owner_email="team-owner@example.com",
        owner_password="password123",
        owner_full_name="Team Owner",
    )
    office, _m = create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office Team",
        municipality_ibge=municipality.ibge_code,
        address="Rua Team 1",
        phone="(62) 4444-4444",
    )
    lat, lng = inside_coords
    login = client.post(
        "/api/auth/login",
        data={
            "email": "team-owner@example.com",
            "password": "password123",
            "device_fingerprint": "fp-team-owner",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {login.json()['access_token']}"

    invited = client.post(
        f"/api/tenants/offices/{office.id}/members",
        data={
            "email": "tech@team.example.com",
            "role": "technician",
            "full_name": "Tech Invitee",
        },
        content_type="application/json",
    )
    assert invited.status_code == 201, invited.content
    body = invited.json()
    assert body["created_user"] is True
    assert body["temporary_password"]
    membership_id = body["membership"]["id"]
    assert body["membership"]["is_active"] is False
    assert body["membership"]["user_email"] == "tech@team.example.com"

    listed = client.get(f"/api/tenants/offices/{office.id}/members")
    assert listed.status_code == 200
    assert len(listed.json()) == 2  # owner + tech

    # Invited user can log in; inactive membership is activated.
    tech_client = client.__class__()
    tech_login = tech_client.post(
        "/api/auth/login",
        data={
            "email": "tech@team.example.com",
            "password": body["temporary_password"],
            "device_fingerprint": "fp-team-tech",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert tech_login.status_code == 200, tech_login.content
    assert tech_login.json()["office_id"] == office.id
    assert tech_login.json()["role"] == Membership.Role.TECHNICIAN
    assert Membership.objects.get(pk=membership_id).is_active is True

    removed = client.delete(
        f"/api/tenants/offices/{office.id}/members/{membership_id}",
    )
    assert removed.status_code == 204
    assert not Membership.objects.filter(pk=membership_id).exists()


@pytest.mark.django_db
def test_cannot_invite_owner_role(client, municipality, inside_coords):
    created = create_tenant(
        organization_name="No Owner Invite",
        organization_trade_name="",
        organization_cnpj="66777888000199",
        owner_email="no-owner-invite@example.com",
        owner_password="password123",
        owner_full_name="",
    )
    office, _m = create_office_for_organization(
        organization=created.organization,
        acting_user=created.user,
        name="Office X",
        municipality_ibge=municipality.ibge_code,
        address="Rua X 1",
        phone="(62) 5555-5555",
    )
    lat, lng = inside_coords
    login = client.post(
        "/api/auth/login",
        data={
            "email": "no-owner-invite@example.com",
            "password": "password123",
            "device_fingerprint": "fp-no-owner",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {login.json()['access_token']}"
    bad = client.post(
        f"/api/tenants/offices/{office.id}/members",
        data={"email": "x@example.com", "role": "owner"},
        content_type="application/json",
    )
    assert bad.status_code == 400

"""Shared pytest fixtures for Django app tests."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from acelera_agro.catalog.bank_profiles import BANK_PROFILE_SEEDS, DEFAULT_CREDIT_LINES
from acelera_agro.catalog.models import BankProfile, CreditLine, CropYear, RuleSet
from acelera_agro.tenants import context as tenant_context
from acelera_agro.tenants.models import Membership, Municipality, Office, Organization

User = get_user_model()

# Simple square around a point in GO for territorial tests (lng/lat GeoJSON).
SQUARE_BOUNDARY = json.dumps(
    {
        "type": "Polygon",
        "coordinates": [
            [
                [-49.3, -16.8],
                [-49.1, -16.8],
                [-49.1, -16.6],
                [-49.3, -16.6],
                [-49.3, -16.8],
            ]
        ],
    }
)


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Org Teste Stub", trade_name="Org Stub")


@pytest.fixture
def municipality(db):
    return Municipality.objects.create(
        ibge_code="5208707",
        name="Goiania Stub",
        state_uf="GO",
        fiscal_module_ha=Decimal("20.0000"),
        boundary=SQUARE_BOUNDARY,
    )


@pytest.fixture
def office(organization, municipality):
    return Office.objects.create(
        organization=organization,
        municipality=municipality,
        name="Escritorio Stub",
        status=Office.Status.ACTIVE,
        referral_code="REF-STUB-01",
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(
        username="tech@example.com",
        email="tech@example.com",
        password="test-password-123",
    )


@pytest.fixture
def membership(user, office):
    return Membership.objects.create(
        user=user,
        office=office,
        role=Membership.Role.TECHNICIAN,
        is_active=True,
    )


@pytest.fixture
def tenant_ctx(organization, office, membership):
    tenant_context.set_tenant_context(
        organization_id=organization.id,
        office_id=office.id,
        membership=membership,
        role=membership.role,
        read_only=False,
    )
    yield
    tenant_context.clear_tenant_context()


@pytest.fixture
def catalog(db):
    from datetime import date

    crop_year = CropYear.objects.create(
        code="2025_2026",
        label="Safra 2025/2026",
        starts_on=date(2025, 7, 1),
        ends_on=date(2026, 6, 30),
        is_active=True,
    )
    ruleset = RuleSet.objects.create(
        code="pronaf_spreadsheet",
        version="1",
        name="Pronaf spreadsheet",
        is_active=True,
        config={"classification": "spreadsheet_legacy"},
    )
    profiles = {}
    for seed in BANK_PROFILE_SEEDS:
        profiles[seed["code"]] = BankProfile.objects.create(
            code=seed["code"],
            name=seed["name"],
            is_active=seed["is_active"],
            document_checklist=seed["document_checklist"],
            pdf_sections=seed["pdf_sections"],
            extra_config=seed["extra_config"],
        )
    bb = profiles["bb"]
    lines = {}
    for line in DEFAULT_CREDIT_LINES:
        lines[line["code"]] = CreditLine.objects.create(
            bank_profile=bb,
            crop_year=crop_year,
            ruleset=ruleset,
            code=line["code"],
            name=line["name"],
            annual_rate=line["annual_rate"],
            term_years=line["term_years"],
            grace_years=line["grace_years"],
            charge_interest_during_grace=line["charge_interest_during_grace"],
            is_active=True,
            extra_config=line.get("extra_config") or {},
        )
    return {
        "crop_year": crop_year,
        "ruleset": ruleset,
        "profiles": profiles,
        "credit_lines": lines,
    }


@pytest.fixture
def inside_coords():
    return Decimal("-16.700000"), Decimal("-49.200000")


@pytest.fixture
def outside_coords():
    return Decimal("-15.000000"), Decimal("-48.000000")


@pytest.fixture
def client_factory(inside_coords):
    """Build a logged-in test client for an existing user (user must have a membership)."""
    from django.test import Client

    def make(email: str, password: str = "test-password-123", fingerprint: str = "fp-1"):
        lat, lng = inside_coords
        client = Client()
        login = client.post(
            "/api/auth/login",
            data={
                "email": email,
                "password": password,
                "device_fingerprint": fingerprint,
                "lat": str(lat),
                "lng": str(lng),
            },
            content_type="application/json",
        )
        assert login.status_code == 200, login.content
        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {login.json()['access_token']}"
        return client

    return make


@pytest.fixture
def form_client(user, membership, client_factory):
    """Technician client of the default office."""
    return client_factory("tech@example.com", fingerprint="fp-form-tech")

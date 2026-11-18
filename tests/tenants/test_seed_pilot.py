"""Marco T7 — pilot seed command."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from acelera_agro.tenants.models import Membership, Municipality, Office, Organization


@pytest.mark.django_db
def test_seed_pilot_creates_bioflora_stub_offices():
    call_command("seed_pilot")

    assert Municipality.objects.filter(ibge_code="1100940").exists()  # Cujubim
    assert Municipality.objects.filter(ibge_code="1100205").exists()  # Porto Velho

    org = Organization.objects.get(cnpj="11244777000191")
    assert "Stub" in org.name
    assert org.owner is not None
    assert org.owner.email == "leandro.owner@bioflora.stub.local"

    offices = list(Office.objects.filter(organization=org).order_by("name"))
    assert len(offices) == 2
    assert {o.municipality.ibge_code for o in offices} == {"1100940", "1100205"}

    active = Membership.objects.get(
        user__email="leandro.owner@bioflora.stub.local", is_active=True
    )
    assert active.office.municipality.ibge_code == "1100940"

    tech = Membership.objects.get(
        user__email="tech.cujubim@bioflora.stub.local", is_active=True
    )
    assert tech.role == Membership.Role.TECHNICIAN
    assert tech.office.municipality.ibge_code == "1100940"

    # Idempotent
    call_command("seed_pilot", "--skip-catalog")
    assert Organization.objects.filter(cnpj="11244777000191").count() == 1

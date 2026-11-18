"""Multi-tenant query isolation tests."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from acelera_agro.proposals.models import Proponent
from acelera_agro.tenants import context as tenant_context
from acelera_agro.tenants.models import Membership, Office, Organization

User = get_user_model()


@pytest.mark.django_db
def test_organization_scoped_queryset_isolates_tenants(
    organization, office, membership, municipality
):
    other_org = Organization.objects.create(name="Other Org")
    other_office = Office.objects.create(
        organization=other_org,
        municipality=municipality,
        name="Other Office",
        referral_code="REF-OTHER",
    )
    other_user = User.objects.create_user(
        username="other@example.com",
        email="other@example.com",
        password="x",
    )
    Membership.objects.create(
        user=other_user,
        office=other_office,
        role=Membership.Role.TECHNICIAN,
        is_active=True,
    )

    tenant_context.set_tenant_context(
        organization_id=organization.id,
        office_id=office.id,
        membership=membership,
        role=membership.role,
    )
    mine = Proponent.objects.create(
        organization=organization,
        full_name="Produtor Tenant A",
    )
    # Bypass manager to plant cross-tenant row
    Proponent.all_objects.create(
        organization=other_org,
        full_name="Produtor Tenant B",
    )

    visible = list(Proponent.objects.all())
    assert len(visible) == 1
    assert visible[0].id == mine.id
    assert Proponent.all_objects.count() == 2

    tenant_context.clear_tenant_context()


@pytest.mark.django_db
def test_office_scoped_proposals_do_not_leak(organization, office, membership, municipality, catalog):
    from decimal import Decimal

    from acelera_agro.proposals.models import Proposal

    other_org = Organization.objects.create(name="Leak Org")
    other_office = Office.objects.create(
        organization=other_org,
        municipality=municipality,
        name="Leak Office",
        referral_code="REF-LEAK",
    )

    tenant_context.set_tenant_context(
        organization_id=organization.id,
        office_id=office.id,
        membership=membership,
        role=membership.role,
    )
    proponent = Proponent.objects.create(
        organization=organization, full_name="Produtor Isolation"
    )
    Proposal.objects.create(
        office=office,
        organization=organization,
        proponent=proponent,
        financed_amount=Decimal("1000.00"),
    )
    foreign_proponent = Proponent.all_objects.create(
        organization=other_org, full_name="Foreign Proponent"
    )
    Proposal.all_objects.create(
        office=other_office,
        organization=other_org,
        proponent=foreign_proponent,
        financed_amount=Decimal("9999.00"),
    )

    assert Proposal.objects.count() == 1
    assert Proposal.all_objects.count() == 2
    tenant_context.clear_tenant_context()

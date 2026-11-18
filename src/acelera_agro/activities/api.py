"""Activity projection stub API attached to proposals."""

from __future__ import annotations

from decimal import Decimal

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from acelera_agro.accounts.auth import jwt_auth
from acelera_agro.accounts.rbac import assert_role_and_mutate
from acelera_agro.activities.projections import (
    agriculture_projection,
    attach_projections_to_proposal,
    beef_cattle_projection,
    dairy_cattle_projection,
)
from acelera_agro.proposals.models import Proposal
from acelera_agro.tenants.models import Membership

router = Router(tags=["activities"], auth=jwt_auth)

_WRITE = (
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.TECHNICIAN,
)


class ProjectionAttachIn(Schema):
    activity_kind: str = "agriculture"
    base_revenue: str = "100000.00"
    base_expense: str = "60000.00"
    initial_herd: int = 50
    years: int = 10


class ProjectionAttachOut(Schema):
    proposal_id: int
    activity_kind: str
    rows_created: int
    sample: list[dict]


@router.post(
    "/proposals/{proposal_id}/activities/projections",
    response=ProjectionAttachOut,
)
def attach_projections(request, proposal_id: int, payload: ProjectionAttachIn):
    assert_role_and_mutate(request, *_WRITE)
    proposal = get_object_or_404(Proposal, pk=proposal_id)
    revenue = Decimal(payload.base_revenue)
    expense = Decimal(payload.base_expense)
    kind = payload.activity_kind

    if kind == "beef_cattle":
        rows = beef_cattle_projection(
            base_revenue=revenue,
            base_expense=expense,
            initial_herd=payload.initial_herd,
            years=payload.years,
            financed_amount=proposal.financed_amount,
        )
    elif kind == "dairy_cattle":
        rows = dairy_cattle_projection(
            base_revenue=revenue,
            base_expense=expense,
            initial_herd=payload.initial_herd,
            years=payload.years,
        )
    else:
        rows = agriculture_projection(
            base_revenue=revenue,
            base_expense=expense,
            years=payload.years,
        )

    created = attach_projections_to_proposal(proposal, rows)
    return ProjectionAttachOut(
        proposal_id=proposal.id,
        activity_kind=kind,
        rows_created=created,
        sample=rows[:2],
    )

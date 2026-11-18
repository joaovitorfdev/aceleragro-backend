"""Proposal CRUD, calculate, issues, mark reviewed."""

from __future__ import annotations

from decimal import Decimal

from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from acelera_agro.accounts.auth import jwt_auth
from acelera_agro.accounts.rbac import assert_role, assert_role_and_mutate
from acelera_agro.proposals.models import Property, Proponent, Proposal
from acelera_agro.proposals.aptitude import evaluate_all_banks
from acelera_agro.proposals.schemas import (
    BankAptitudeListOut,
    BankAptitudeOut,
    IssueOut,
    MessageOut,
    ProposalCreateIn,
    ProposalOut,
)
from acelera_agro.proposals.services import calculate_proposal
from acelera_agro.proposals.validation import validate_proposal
from acelera_agro.tenants.models import Membership

router = Router(tags=["proposals"], auth=jwt_auth)

_ALL = (
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.TECHNICIAN,
    Membership.Role.VIEWER,
)
_WRITE = (
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.TECHNICIAN,
)


def _proposal_out(p: Proposal) -> ProposalOut:
    return ProposalOut(
        id=p.id,
        office_id=p.office_id,
        organization_id=p.organization_id,
        proponent_id=p.proponent_id,
        property_id=p.property_id,
        bank_profile_id=p.bank_profile_id,
        credit_line_id=p.credit_line_id,
        status=p.status,
        financed_amount=str(p.financed_amount),
        schedule_json=p.schedule_json or [],
        capacity_json=p.capacity_json or [],
        classification_json=p.classification_json or {},
        technician_reviewed_at=(
            p.technician_reviewed_at.isoformat() if p.technician_reviewed_at else None
        ),
        calculated_at=p.calculated_at.isoformat() if p.calculated_at else None,
    )


def _get_office_proposal(proposal_id: int) -> Proposal:
    return get_object_or_404(
        Proposal.objects.select_related(
            "proponent",
            "property",
            "property__municipality",
            "bank_profile",
            "credit_line",
            "ruleset",
            "office",
            "office__municipality",
            "organization",
        ),
        pk=proposal_id,
    )


@router.get("/proposals", response=list[ProposalOut])
def list_proposals(request):
    assert_role(*_ALL)
    return [_proposal_out(p) for p in Proposal.objects.all()[:100]]


@router.post("/proposals", response={201: ProposalOut})
def create_proposal(request, payload: ProposalCreateIn):
    assert_role_and_mutate(request, *_WRITE)
    ctx = request.auth
    proponent = get_object_or_404(Proponent, pk=payload.proponent_id)
    property_obj = None
    if payload.property_id:
        property_obj = get_object_or_404(Property, pk=payload.property_id)

    proposal = Proposal.objects.create(
        office_id=ctx.office_id,
        organization_id=ctx.tenant_id,
        proponent=proponent,
        property=property_obj,
        bank_profile_id=payload.bank_profile_id,
        credit_line_id=payload.credit_line_id,
        crop_year_id=payload.crop_year_id,
        ruleset_id=payload.ruleset_id,
        financed_amount=Decimal(payload.financed_amount or "0"),
        annual_rate=Decimal(payload.annual_rate) if payload.annual_rate else None,
        term_years=payload.term_years,
        grace_years=payload.grace_years,
        family_maintenance=Decimal(payload.family_maintenance or "0"),
        total_rba=Decimal(payload.total_rba or "0"),
        agro_revenue_share=Decimal(payload.agro_revenue_share or "1"),
        referral_code=payload.referral_code or "",
        created_by=request.user,
    )
    return Status(201, _proposal_out(proposal))


@router.get("/proposals/{proposal_id}", response=ProposalOut)
def get_proposal(request, proposal_id: int):
    assert_role(*_ALL)
    return _proposal_out(_get_office_proposal(proposal_id))


@router.post("/proposals/{proposal_id}/calculate", response=ProposalOut)
def post_calculate(request, proposal_id: int):
    assert_role_and_mutate(request, *_WRITE)
    proposal = _get_office_proposal(proposal_id)
    calculate_proposal(proposal)
    validate_proposal(proposal)
    proposal.refresh_from_db()
    return _proposal_out(proposal)


@router.get("/proposals/{proposal_id}/issues", response=list[IssueOut])
def get_issues(request, proposal_id: int, refresh: bool = False):
    assert_role(*_ALL)
    proposal = _get_office_proposal(proposal_id)
    if refresh:
        validate_proposal(proposal)
    issues = proposal.issues.filter(resolved_at__isnull=True)
    return [
        IssueOut(
            id=i.id,
            code=i.code,
            message=i.message,
            severity=i.severity,
            field_path=i.field_path,
            resolved_at=i.resolved_at.isoformat() if i.resolved_at else None,
        )
        for i in issues
    ]


@router.get("/proposals/{proposal_id}/bank-aptitude", response=BankAptitudeListOut)
def get_bank_aptitude(request, proposal_id: int, refresh: bool = True):
    """Per-bank aptitude tags for the same-screen export strip (BB first, others scaffold)."""
    assert_role(*_ALL)
    proposal = _get_office_proposal(proposal_id)
    items = evaluate_all_banks(proposal, refresh_validation=refresh)
    return BankAptitudeListOut(
        items=[BankAptitudeOut(**row.to_dict()) for row in items]
    )


@router.post("/proposals/{proposal_id}/mark-reviewed", response={200: ProposalOut, 400: MessageOut})
def mark_reviewed(request, proposal_id: int):
    assert_role_and_mutate(request, *_WRITE)
    proposal = _get_office_proposal(proposal_id)
    validate_proposal(proposal)
    errors = proposal.issues.filter(
        resolved_at__isnull=True, severity="error"
    ).exists()
    if errors:
        raise HttpError(400, "Cannot mark reviewed while error issues remain")
    proposal.technician_reviewed_at = timezone.now()
    proposal.status = Proposal.Status.IN_REVIEW
    proposal.save(update_fields=["technician_reviewed_at", "status", "updated_at"])
    return _proposal_out(proposal)

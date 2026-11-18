"""Extraction / classification API."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from acelera_agro.accounts.auth import jwt_auth
from acelera_agro.accounts.rbac import assert_role_and_mutate
from acelera_agro.extraction.services import run_extraction, suggest_ownership_type
from acelera_agro.proposals.models import Proposal
from acelera_agro.tenants.models import Membership

router = Router(tags=["extraction"], auth=jwt_auth)

_WRITE = (
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.TECHNICIAN,
)


class ExtractionRunIn(Schema):
    proposal_id: int | None = None
    document_ids: list[int] | None = None
    classify_only: bool = False


class ExtractionDocOut(Schema):
    id: int
    detected_kind: str
    detected_kind_confidence: str | None
    extraction_status: str
    ownership_type_suggestion: str | None = None


class ExtractionRunOut(Schema):
    documents: list[ExtractionDocOut]
    ownership_type_suggestion: str | None = None


@router.post("/extractions/run", response=ExtractionRunOut)
def run(request, payload: ExtractionRunIn):
    assert_role_and_mutate(request, *_WRITE)
    proposal = None
    if payload.proposal_id:
        proposal = get_object_or_404(Proposal, pk=payload.proposal_id)

    docs = run_extraction(
        proposal=proposal,
        document_ids=payload.document_ids,
        classify_only=payload.classify_only,
    )

    kinds = {(d.user_override_kind or d.detected_kind) for d in docs}
    suggestion = suggest_ownership_type(kinds)

    return ExtractionRunOut(
        documents=[
            ExtractionDocOut(
                id=d.id,
                detected_kind=d.detected_kind,
                detected_kind_confidence=(
                    str(d.detected_kind_confidence)
                    if d.detected_kind_confidence is not None
                    else None
                ),
                extraction_status=d.extraction_status,
            )
            for d in docs
        ],
        ownership_type_suggestion=suggestion,
    )

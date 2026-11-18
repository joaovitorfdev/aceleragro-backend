"""Proposal form contract endpoints (docs/form-contract.md)."""

from __future__ import annotations

from typing import Any

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from ninja.errors import HttpError
from ninja.responses import Status

from acelera_agro.accounts.auth import jwt_auth
from acelera_agro.accounts.rbac import assert_role, assert_role_and_mutate
from acelera_agro.audit.services import log_audit
from acelera_agro.extraction.services import start_reading
from acelera_agro.proposals import form_rules, form_state
from acelera_agro.proposals.form_state import FormError
from acelera_agro.proposals.models import Proposal
from acelera_agro.tenants.models import Membership

router = Router(tags=["proposal-form"], auth=jwt_auth)

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

MAX_CHANGES_PER_REQUEST = 200


class FormDocumentOut(Schema):
    id: int
    filename: str
    detected_kind: str
    status: str


class FormOut(Schema):
    values: dict[str, Any]
    provenance: dict[str, Any]
    suggestions: dict[str, Any]
    documents: list[FormDocumentOut]
    reading: bool
    # Display labels for values that are codes (e.g. municipality paths).
    labels: dict[str, str] = {}


class DraftOut(FormOut):
    id: int
    status: str
    office_id: int
    organization_id: int


class FormPatchIn(Schema):
    # Each change: {"path": str, "value"?: any, "dismiss_suggestion"?: bool}.
    changes: list[dict[str, Any]]


class FormErrorOut(Schema):
    detail: str
    code: str
    path: str = ""


def _get_proposal(proposal_id: int) -> Proposal:
    # `Proposal.objects` is scoped to the active office: other offices get 404.
    return get_object_or_404(Proposal.objects.select_related("proponent"), pk=proposal_id)


@router.get("/forms/proposal")
def get_proposal_form_schema(request):
    assert_role(*_ALL)
    return HttpResponse(form_rules.schema_bytes(), content_type="application/json")


@router.post("/proposals/drafts", response={201: DraftOut})
def create_draft(request):
    assert_role_and_mutate(request, *_WRITE)
    ctx = request.auth
    proposal = Proposal.objects.create(
        office_id=ctx.office_id,
        organization_id=ctx.tenant_id,
        created_by=request.user,
        status=Proposal.Status.DRAFT,
    )
    return Status(
        201,
        {
            "id": proposal.id,
            "status": proposal.status,
            "office_id": proposal.office_id,
            "organization_id": proposal.organization_id,
            **form_state.get_form(proposal),
        },
    )


@router.get("/proposals/{proposal_id}/form", response=FormOut)
def get_form(request, proposal_id: int):
    assert_role(*_ALL)
    return form_state.get_form(_get_proposal(proposal_id))


@router.patch("/proposals/{proposal_id}/form", response={200: FormOut, 422: FormErrorOut})
def patch_form(request, proposal_id: int, payload: FormPatchIn):
    assert_role_and_mutate(request, *_WRITE)
    proposal = _get_proposal(proposal_id)
    if proposal.status not in form_state.EDITABLE_STATUSES:
        raise HttpError(409, "Proposal is no longer editable")
    if len(payload.changes) > MAX_CHANGES_PER_REQUEST:
        raise HttpError(413, "Too many changes in one request")
    try:
        form_state.apply_user_changes(proposal, payload.changes)
    except FormError as exc:
        return Status(422, {"detail": exc.message, "code": exc.code, "path": exc.path})
    return form_state.get_form(proposal)


@router.post("/proposals/{proposal_id}/read-documents", response={202: FormOut})
def read_documents(request, proposal_id: int):
    """Queue unread documents; classification + extraction + autofill run in background."""
    assert_role_and_mutate(request, *_WRITE)
    proposal = _get_proposal(proposal_id)
    if proposal.status not in form_state.EDITABLE_STATUSES:
        raise HttpError(409, "Proposal is no longer editable")
    queued = start_reading(proposal)
    log_audit(
        action="proposals.read_documents",
        resource_type="proposal",
        resource_id=proposal.id,
        detail={"queued": len(queued)},
        user=request.user,
    )
    proposal.refresh_from_db()
    return Status(202, form_state.get_form(proposal))

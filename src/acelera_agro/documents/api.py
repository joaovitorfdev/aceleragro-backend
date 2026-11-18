"""Document batch presign upload + PDF generation endpoints."""

from __future__ import annotations

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.responses import Status

from acelera_agro.accounts.auth import jwt_auth
from acelera_agro.accounts.rbac import assert_role, assert_role_and_mutate
from acelera_agro.audit.services import log_audit
from acelera_agro.documents.models import Document, DocumentKind
from acelera_agro.documents.pdf import (
    PdfGenerationError,
    generate_anexo2_pdf,
    generate_bb_proposal_pdf,
    generate_croqui_pdf,
    generate_declaracao_atni_pdf,
    generate_laudo_pdf,
)
from acelera_agro.documents.storage import (
    build_object_key,
    create_presigned_upload,
    get_object_bytes,
)
from acelera_agro.proposals.models import Proposal
from acelera_agro.tenants.models import Membership

_BANNER_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB — in-memory only, never stored
_BANNER_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}

router = Router(tags=["documents"], auth=jwt_auth)

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


class FileMetaIn(Schema):
    filename: str
    content_type: str = "application/octet-stream"
    size: int = 0


class BatchPresignIn(Schema):
    proposal_id: int
    files: list[FileMetaIn]


class PresignItemOut(Schema):
    document_id: int
    s3_key: str
    original_filename: str
    upload: dict


class BatchPresignOut(Schema):
    items: list[PresignItemOut]


class DocumentOut(Schema):
    id: int
    proposal_id: int
    original_filename: str
    detected_kind: str
    detected_kind_confidence: str | None
    user_override_kind: str
    extraction_status: str


@router.post("/documents/presign", response={201: BatchPresignOut})
def batch_presign(request, payload: BatchPresignIn):
    """Batch presign upload — kind is NOT required from the client."""
    assert_role_and_mutate(request, *_WRITE)
    if not payload.files:
        raise HttpError(400, "files list is required")

    proposal = get_object_or_404(Proposal, pk=payload.proposal_id)
    ctx = request.auth
    items: list[PresignItemOut] = []

    for meta in payload.files:
        key = build_object_key(
            office_id=ctx.office_id,
            proposal_id=proposal.id,
            filename=meta.filename,
        )
        doc = Document.objects.create(
            office_id=ctx.office_id,
            proposal=proposal,
            s3_key=key,
            content_type=meta.content_type,
            size=meta.size,
            original_filename=meta.filename,
            uploaded_by=request.user,
        )
        upload = create_presigned_upload(key=key, content_type=meta.content_type)
        items.append(
            PresignItemOut(
                document_id=doc.id,
                s3_key=key,
                original_filename=meta.filename,
                upload=upload,
            )
        )

    log_audit(
        action="documents.presign_batch",
        resource_type="proposal",
        resource_id=proposal.id,
        detail={"count": len(items)},
        user=request.user,
    )
    return Status(201, BatchPresignOut(items=items))


@router.get("/documents/{document_id}", response=DocumentOut)
def get_document(request, document_id: int):
    assert_role(*_ALL)
    doc = get_object_or_404(Document, pk=document_id)
    return DocumentOut(
        id=doc.id,
        proposal_id=doc.proposal_id,
        original_filename=doc.original_filename,
        detected_kind=doc.detected_kind,
        detected_kind_confidence=(
            str(doc.detected_kind_confidence)
            if doc.detected_kind_confidence is not None
            else None
        ),
        user_override_kind=doc.user_override_kind,
        extraction_status=doc.extraction_status,
    )


class DocumentKindIn(Schema):
    user_override_kind: str


@router.patch("/documents/{document_id}", response=DocumentOut)
def set_document_kind(request, document_id: int, payload: DocumentKindIn):
    """Label an `unrecognized` document (the only case where the user picks a kind)."""
    assert_role_and_mutate(request, *_WRITE)
    if payload.user_override_kind and payload.user_override_kind not in DocumentKind.values:
        raise HttpError(422, "Unknown document kind")
    doc = get_object_or_404(Document, pk=document_id)
    doc.user_override_kind = payload.user_override_kind
    doc.save(update_fields=["user_override_kind", "updated_at"])
    return get_document(request, document_id)


def _pdf_response(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _load_proposal_for_pdf(proposal_id: int) -> Proposal:
    return get_object_or_404(
        Proposal.objects.select_related(
            "proponent",
            "property",
            "property__municipality",
            "technical_opinion",
            "credit_line",
            "office",
            "office__municipality",
            "organization",
        ),
        pk=proposal_id,
    )


def _read_banner(banner: UploadedFile | None) -> bytes | None:
    """Read banner into memory for this request only — never written to disk/S3."""
    if banner is None:
        return None
    content_type = (getattr(banner, "content_type", None) or "").lower()
    if content_type and content_type not in _BANNER_CONTENT_TYPES:
        raise HttpError(400, "Banner must be PNG, JPEG or WebP")
    data = banner.read()
    if len(data) > _BANNER_MAX_BYTES:
        raise HttpError(400, "Banner exceeds 2 MiB limit")
    return data or None


def _resolve_banner_bytes(
    proposal: Proposal, override: bytes | None
) -> bytes | None:
    """Request override wins; otherwise Organization.banner_key from storage."""
    if override:
        return override
    org = getattr(proposal, "organization", None)
    key = getattr(org, "banner_key", "") or ""
    if not key:
        return None
    return get_object_bytes(key)


def _render_proposal_pdf(
    request,
    proposal: Proposal,
    doc_type: str,
    *,
    banner_bytes: bytes | None = None,
) -> HttpResponse:
    if doc_type == "bb":
        try:
            content = generate_bb_proposal_pdf(
                proposal,
                banner_bytes=_resolve_banner_bytes(proposal, banner_bytes),
            )
        except PdfGenerationError as exc:
            raise HttpError(400, str(exc)) from exc
        log_audit(
            action="documents.pdf_bb",
            resource_type="proposal",
            resource_id=proposal.id,
            user=request.user,
        )
        return _pdf_response(content, f"proposal_{proposal.id}_bb.pdf")

    generators = {
        "laudo": generate_laudo_pdf,
        "declaracao_atni": generate_declaracao_atni_pdf,
        "croqui": generate_croqui_pdf,
        "anexo2": generate_anexo2_pdf,
    }
    gen = generators.get(doc_type)
    if gen is None:
        raise HttpError(404, "Unknown PDF type")
    return _pdf_response(gen(proposal), f"proposal_{proposal.id}_{doc_type}.pdf")


@router.get("/proposals/{proposal_id}/pdf/{doc_type}")
def download_proposal_pdf(request, proposal_id: int, doc_type: str):
    """GET export without banner (backward compatible)."""
    assert_role(*_ALL)
    proposal = _load_proposal_for_pdf(proposal_id)
    return _render_proposal_pdf(request, proposal, doc_type)


@router.post("/proposals/{proposal_id}/pdf/{doc_type}")
def download_proposal_pdf_with_banner(
    request,
    proposal_id: int,
    doc_type: str,
    banner: UploadedFile | None = File(None),
):
    """POST export; optional ``banner`` file is used only in memory for this PDF."""
    assert_role(*_ALL)
    proposal = _load_proposal_for_pdf(proposal_id)
    banner_bytes = _read_banner(banner)
    return _render_proposal_pdf(
        request, proposal, doc_type, banner_bytes=banner_bytes
    )

"""Classify / extract / autofill the proposal form (docs/form-contract.md).

Autofill behaves like a user acting on the form controls, subject to the contract rules:

1. A path with ``source = user`` is locked and never overwritten.
2. A value is applied only if ``confidence >= min_confidence`` (field override or schema
   default), the path is unlocked and the field is not a ``declaration``.
3. Anything else that differs from the current value becomes a suggestion.
4. Two documents disagreeing on an unlocked field: the higher confidence stays applied and
   the other one is exposed as a suggestion.
5. Hidden fields keep their values (nothing is deleted here).
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings
from django.db import close_old_connections, connections, transaction
from django.utils import timezone

from acelera_agro.documents.models import Document
from acelera_agro.extraction.providers import get_extraction_provider
from acelera_agro.extraction.schemas import OWNERSHIP_FROM_KIND
from acelera_agro.proposals import form_rules, form_state
from acelera_agro.proposals.form_state import FormError, ParsedPath
from acelera_agro.proposals.models import Proposal

logger = logging.getLogger(__name__)

AUTOFILL_OUTCOMES = ("applied", "suggested", "skipped")

# Extracted key -> form path template ({i} = item index, filled by the caller).
PROPONENT_KEYS = {
    "full_name": "proponent.full_name",
    "document_number": "proponent.document_number",
    "address": "proponent.address",
    "marital_status": "proponent.marital_status",
    "spouse_name": "proponent.spouse_name",
    "partner_name": "proponent.spouse_name",
    "spouse_document_number": "proponent.spouse_document_number",
}
PROPERTY_KEYS = {
    "car_code": "car_code",
    "matricula": "matricula",
    "nirf": "nirf",
    "area_ha": "area_ha",
    "ownership_type": "ownership_type",
    "municipality": "municipality",
    "municipality_name": "municipality",
}
DEBT_KEYS = ("creditor", "outstanding_balance", "annual_rate")
CREDIT_KEYS = {"activity_kind": "credit.activity_kind"}


# --------------------------------------------------------------- classification


def classify_document(document: Document) -> Document:
    provider = get_extraction_provider()
    kind, confidence = provider.classify(document)
    document.detected_kind = kind
    document.detected_kind_confidence = confidence
    document.classified_at = timezone.now()
    document.extraction_status = Document.ExtractionStatus.CLASSIFIED
    document.save(
        update_fields=[
            "detected_kind",
            "detected_kind_confidence",
            "classified_at",
            "extraction_status",
            "updated_at",
        ]
    )
    return document


def classify_documents(documents: list[Document]) -> list[Document]:
    return [classify_document(doc) for doc in documents]


def suggest_ownership_type(kinds: set[str]) -> str | None:
    for kind, ownership in OWNERSHIP_FROM_KIND.items():
        if kind in kinds:
            return ownership
    return None


# --------------------------------------------------------------------- autofill


def _confidence(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def min_confidence(parsed: ParsedPath) -> Decimal:
    raw = parsed.field.get("autofill_min_confidence") or form_rules.default_min_confidence()
    return Decimal(str(raw))


def _is_unset(parsed: ParsedPath, current: Any, provenance: dict[str, Any] | None) -> bool:
    if current is None:
        return True
    # Legacy rows defaulted ownership to "other"; without provenance that means "unknown".
    return parsed.field_id == "ownership_type" and current == "other" and not provenance


def _suggest(
    proposal: Proposal, parsed: ParsedPath, canonical: Any, entry: dict[str, Any]
) -> None:
    suggestions = dict(proposal.form_suggestions or {})
    existing = suggestions.get(parsed.path)
    candidate = {
        "value": canonical,
        "document_id": entry.get("document_id"),
        "document_kind": entry.get("document_kind"),
        "confidence": entry.get("confidence"),
    }
    stronger_exists = (
        existing is not None
        and existing.get("value") != canonical
        and _confidence(existing.get("confidence")) > _confidence(candidate["confidence"])
    )
    if stronger_exists:
        return  # keep the stronger candidate for the same path
    suggestions[parsed.path] = candidate
    proposal.form_suggestions = suggestions
    form_state.save_state(proposal)


@transaction.atomic
def apply_autofill(
    proposal: Proposal, path: str, value: Any, entry: dict[str, Any]
) -> str:
    """Apply (or suggest) one extracted ``value`` for ``path``.

    ``entry`` is the provenance entry (``source``, ``document_id``, ``document_kind``,
    ``confidence`` ...). Returns ``"applied"``, ``"suggested"`` or ``"skipped"``.
    Missing rows (Proponent, Property, debts) are created lazily on the first applied value.
    """
    form_state.lock_proposal(proposal)
    if isinstance(value, Decimal):
        value = format(value, "f")  # decimals travel as strings
    try:
        parsed = form_state.parse_path(path)
        canonical = form_state.normalize_value(parsed, value, lenient=True)
    except FormError:
        return "skipped"
    if canonical is None:
        return "skipped"
    if parsed.field.get("declaration"):
        return "skipped"  # rule: declarations are never autofilled

    entry = {"source": "document", **entry}
    confidence = _confidence(entry.get("confidence"))
    current = form_state.read_value(proposal, parsed)
    provenance = (proposal.form_provenance or {}).get(parsed.path)

    if current == canonical:
        return "skipped"

    locked = (provenance or {}).get("source") == "user"
    if locked or confidence < min_confidence(parsed):
        _suggest(proposal, parsed, canonical, entry)
        return "suggested"

    if not _is_unset(parsed, current, provenance):
        source = (provenance or {}).get("source")
        if source == "document":
            existing_conf = _confidence(provenance.get("confidence"))
            if confidence <= existing_conf:
                _suggest(proposal, parsed, canonical, entry)
                return "suggested"
            # The new value wins; the displaced one stays visible as a suggestion.
            _suggest(
                proposal,
                parsed,
                current,
                {
                    "document_id": provenance.get("document_id"),
                    "document_kind": provenance.get("document_kind"),
                    "confidence": provenance.get("confidence"),
                },
            )
        elif source != "derived":
            # A value with unknown origin (legacy row) is protected like a manual edit.
            _suggest(proposal, parsed, canonical, entry)
            return "suggested"

    form_state.write_value(proposal, parsed, canonical, entry)
    return "applied"


def _unwrap(raw: Any, default_confidence: str) -> tuple[Any, str]:
    if isinstance(raw, dict) and "value" in raw:
        return raw["value"], str(raw.get("confidence") or default_confidence)
    return raw, default_confidence


def _document_confidence(document: Document) -> str:
    """Fallback confidence for fields the provider did not score individually.

    A kind labelled by the user is trusted; otherwise the classification confidence is used.
    """
    if document.user_override_kind:
        return "1.0000"
    return str(document.detected_kind_confidence or "0")


def _debt_index(proposal: Proposal, fields: dict[str, Any]) -> int:
    creditor = _unwrap(fields.get("creditor"), "0")[0]
    debts = form_state.get_debts(proposal)
    for i, debt in enumerate(debts):
        if creditor and debt.creditor.strip().lower() == str(creditor).strip().lower():
            return i
    for i, debt in enumerate(debts):
        if not debt.creditor and debt.outstanding_balance == 0:
            return i
    return len(debts)


def autofill_document(proposal: Proposal, document: Document, fields: dict[str, Any]) -> dict:
    """Run ``apply_autofill`` for every extracted field of ``document``."""
    default_conf = _document_confidence(document)
    outcomes: dict[str, str] = {}

    def run(path: str, raw: Any) -> None:
        value, conf = _unwrap(raw, default_conf)
        if value is None:
            return
        entry = {
            "document_id": document.id,
            "document_kind": document.effective_kind,
            "confidence": conf,
        }
        outcomes[path] = apply_autofill(proposal, path, value, entry)

    for key, raw in fields.items():
        if key in PROPONENT_KEYS:
            run(PROPONENT_KEYS[key], raw)
        elif key in PROPERTY_KEYS:
            run(f"properties.0.{PROPERTY_KEYS[key]}", raw)
        elif key in CREDIT_KEYS:
            run(CREDIT_KEYS[key], raw)
    if any(k in fields for k in DEBT_KEYS):
        idx = _debt_index(proposal, fields)
        for key in DEBT_KEYS:
            if key in fields:
                run(f"debts.{idx}.{key}", fields[key])
    return outcomes


def _derive_ownership(proposal: Proposal, kinds: set[str]) -> None:
    """Ownership suggestion from the document kinds, only on an unset/legacy field."""
    suggested = suggest_ownership_type({k for k in kinds if k})
    if not suggested:
        return
    parsed = form_state.parse_path("properties.0.ownership_type")
    form_state.lock_proposal(proposal)
    provenance = (proposal.form_provenance or {}).get(parsed.path)
    if not _is_unset(parsed, form_state.read_value(proposal, parsed), provenance):
        return
    if form_state.get_target(proposal, parsed, create=False) is None:
        return  # no property yet; nothing to derive for
    form_state.write_value(
        proposal,
        parsed,
        suggested,
        {"source": "derived", "document_kinds": sorted(k for k in kinds if k)},
    )


# --------------------------------------------------------------------- pipeline


def extract_and_merge(document: Document) -> Document:
    provider = get_extraction_provider()
    if document.detected_kind == "unknown" and not document.user_override_kind:
        classify_document(document)
        document.refresh_from_db()

    fields = provider.extract(document)
    default_conf = _document_confidence(document)
    document.field_provenance = {
        key: {"document_id": document.id, "confidence": _unwrap(raw, default_conf)[1]}
        for key, raw in fields.items()
    }
    document.save(update_fields=["field_provenance", "updated_at"])

    autofill_document(document.proposal, document, fields)
    # Only now is the document done: `reading` must not flip before values are applied.
    document.extraction_status = Document.ExtractionStatus.EXTRACTED
    document.save(update_fields=["extraction_status", "updated_at"])
    return document


@transaction.atomic
def run_extraction(
    *,
    proposal: Proposal | None = None,
    document_ids: list[int] | None = None,
    classify_only: bool = False,
) -> list[Document]:
    qs = Document.objects.all()
    if proposal is not None:
        qs = qs.filter(proposal=proposal)
    if document_ids:
        qs = qs.filter(id__in=document_ids)
    docs = list(qs)
    results: list[Document] = []
    for doc in docs:
        classify_document(doc)
        if not classify_only:
            extract_and_merge(doc)
        doc.refresh_from_db()
        results.append(doc)

    if proposal is not None:
        kinds = {d.effective_kind for d in proposal.documents.all()}
        _derive_ownership(proposal, kinds)

    return results


# ---------------------------------------------------------------- async-ish read

_READABLE = (
    Document.ExtractionStatus.PENDING,
    Document.ExtractionStatus.FAILED,
)
# A queued/reading document untouched for this long lost its worker (e.g. restart).
STALE_READING = timedelta(minutes=10)


def queue_documents(proposal: Proposal) -> list[int]:
    """Mark every document that still needs reading as ``queued``; return their ids."""
    S = Document.ExtractionStatus
    docs = Document.all_objects.filter(proposal_id=proposal.pk).order_by("id")
    stale_before = timezone.now() - STALE_READING
    ids: list[int] = []
    for doc in docs:
        relabelled = doc.extraction_status == S.CLASSIFIED and doc.user_override_kind
        stale = (
            doc.extraction_status in (S.QUEUED, S.READING) and doc.updated_at < stale_before
        )
        if doc.extraction_status in _READABLE or relabelled or stale:
            ids.append(doc.id)
    if ids:
        Document.all_objects.filter(id__in=ids).update(
            extraction_status=S.QUEUED, updated_at=timezone.now()
        )
    return ids


def process_queued_documents(proposal_id: int, document_ids: list[int]) -> None:
    """classify -> extract -> autofill each document, updating its status as it goes."""
    S = Document.ExtractionStatus
    provider = get_extraction_provider()
    for doc_id in document_ids:
        document = Document.all_objects.select_related("proposal").filter(pk=doc_id).first()
        if document is None or document.proposal_id != proposal_id:
            continue
        try:
            document.extraction_status = S.READING
            document.save(update_fields=["extraction_status", "updated_at"])

            if not document.user_override_kind:
                kind, confidence = provider.classify(document)
                document.detected_kind = kind
                document.detected_kind_confidence = confidence
                document.classified_at = timezone.now()
                document.save(
                    update_fields=[
                        "detected_kind",
                        "detected_kind_confidence",
                        "classified_at",
                        "updated_at",
                    ]
                )
            if document.effective_kind in ("", "unknown"):
                document.extraction_status = S.CLASSIFIED  # reported as `unrecognized`
                document.save(update_fields=["extraction_status", "updated_at"])
                continue

            extract_and_merge(document)
        except Exception:
            logger.exception("Reading document %s failed", doc_id)
            Document.all_objects.filter(pk=doc_id).update(
                extraction_status=S.FAILED, updated_at=timezone.now()
            )

    proposal = Proposal.all_objects.filter(pk=proposal_id).first()
    if proposal is not None:
        try:
            kinds = {d.effective_kind for d in proposal.documents.all()}
            with transaction.atomic():
                _derive_ownership(proposal, kinds)
        except Exception:
            logger.exception("Ownership derivation failed for proposal %s", proposal_id)


def _read_in_thread(proposal_id: int, document_ids: list[int]) -> None:
    close_old_connections()
    try:
        process_queued_documents(proposal_id, document_ids)
    except Exception:
        logger.exception("Background reading failed for proposal %s", proposal_id)
        Document.all_objects.filter(
            id__in=document_ids,
            extraction_status__in=[
                Document.ExtractionStatus.QUEUED,
                Document.ExtractionStatus.READING,
            ],
        ).update(extraction_status=Document.ExtractionStatus.FAILED)
    finally:
        connections.close_all()


def start_reading(proposal: Proposal) -> list[int]:
    """Queue unread documents and process them (inline under TESTING, else in a thread)."""
    ids = queue_documents(proposal)
    if not ids:
        return ids
    if getattr(settings, "TESTING", False):
        process_queued_documents(proposal.pk, ids)
        return ids
    transaction.on_commit(
        lambda: threading.Thread(
            target=_read_in_thread, args=(proposal.pk, ids), daemon=True
        ).start()
    )
    return ids

"""Proposal validation Issues: checklist conditional on bank profile + docs."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from acelera_agro.proposals import form_rules
from acelera_agro.proposals.form_state import build_values
from acelera_agro.proposals.models import Issue, Proposal


def _effective_kinds(proposal: Proposal) -> set[str]:
    """Detected kinds with user override preferred."""
    kinds: set[str] = set()
    for doc in proposal.documents.all():
        kind = doc.user_override_kind or doc.detected_kind
        if kind and kind != "unknown":
            kinds.add(kind)
    return kinds


@transaction.atomic
def validate_proposal(proposal: Proposal) -> list[Issue]:
    """Replace open issues with a fresh validation run. Returns all open issues."""
    proposal.issues.filter(resolved_at__isnull=True).update(resolved_at=timezone.now())

    created: list[Issue] = []

    def add(code: str, message: str, severity: str = Issue.Severity.ERROR, field_path: str = ""):
        created.append(
            Issue.objects.create(
                proposal=proposal,
                code=code,
                message=message,
                severity=severity,
                field_path=field_path,
            )
        )

    if not proposal.proponent_id:
        add("missing_proponent", "Proponent is required.", field_path="proponent")

    if not proposal.property_id:
        add("missing_property", "Property is required.", field_path="property")

    if not proposal.bank_profile_id:
        add("missing_bank_profile", "Bank profile is required.", field_path="bank_profile")

    if not proposal.credit_line_id:
        add(
            "missing_credit_line",
            "Credit line is required.",
            severity=Issue.Severity.WARNING,
            field_path="credit_line",
        )

    if (
        (proposal.financed_amount is None or proposal.financed_amount <= 0)
        and not proposal.budget_items.exists()
    ):
        add(
            "missing_financed_amount",
            "Financed amount or budget items are required.",
            field_path="credit.financed_amount",
        )

    ownership_type = None
    marital_status = None
    if proposal.property_id:
        ownership_type = proposal.property.ownership_type or None
    if proposal.proponent_id:
        marital_status = proposal.proponent.marital_status or None

    detected = _effective_kinds(proposal)

    if proposal.bank_profile_id:
        required = proposal.bank_profile.required_document_kinds(
            ownership_type=ownership_type,
            marital_status=marital_status,
        )
        for kind in required:
            if kind not in detected:
                add(
                    f"missing_document_{kind}",
                    f"Required document kind '{kind}' is missing.",
                    severity=Issue.Severity.ERROR,
                    field_path=f"documents.{kind}",
                )

    # Form contract: visible + required + empty fields, keyed by the schema path.
    for path in form_rules.missing_required(build_values(proposal)):
        if path == "credit.financed_amount":
            # Covered by `missing_financed_amount` (which also accepts budget items).
            continue
        add(
            "field_required",
            f"Field '{path}' is required.",
            severity=Issue.Severity.ERROR,
            field_path=path,
        )

    if proposal.calculated_at is None:
        add(
            "not_calculated",
            "Proposal has not been calculated yet.",
            severity=Issue.Severity.WARNING,
            field_path="calculated_at",
        )
    else:
        capacity = proposal.capacity_json or []
        negative = [row for row in capacity if str(row.get("surplus", "0")).startswith("-")]
        if negative:
            add(
                "negative_capacity",
                "Payment capacity has negative surplus in one or more years.",
                severity=Issue.Severity.ERROR,
                field_path="capacity_json",
            )

    return created


def has_error_issues(proposal: Proposal) -> bool:
    return proposal.issues.filter(
        resolved_at__isnull=True, severity=Issue.Severity.ERROR
    ).exists()

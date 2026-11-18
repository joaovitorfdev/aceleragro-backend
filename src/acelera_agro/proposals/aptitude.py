"""Bank aptitude evaluation — bank-agnostic, driven by BankProfile.

Statuses (system aptitude, never agency approval):
- ``apto``: checklist + form + capacity OK; enquadramento compatible with bank product.
- ``pendente``: missing docs/fields, not calculated, or blocking Issues.
- ``fora_enquadramento``: producer group incompatible with the bank's product band.
- ``em_breve``: profile inactive or scaffold (no exporter yet).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from acelera_agro.catalog.models import BankProfile
from acelera_agro.proposals import form_rules
from acelera_agro.proposals.form_state import build_values
from acelera_agro.proposals.models import Issue, Proposal
from acelera_agro.proposals.validation import validate_proposal

STATUS_APTO = "apto"
STATUS_PENDENTE = "pendente"
STATUS_FORA = "fora_enquadramento"
STATUS_EM_BREVE = "em_breve"

# Spreadsheet legacy + current_mcr codes that can sit on Pronaf investment products.
_DEFAULT_PRONAF_GROUPS = frozenset({"B", "AF", "PRONAF_B", "PRONAF"})


@dataclass
class BankAptitudeResult:
    bank_code: str
    bank_name: str
    status: str
    exportable: bool
    export_formats: list[str] = field(default_factory=list)
    reasons: list[dict[str, str]] = field(default_factory=list)
    missing_document_kinds: list[str] = field(default_factory=list)
    group_code: str | None = None
    full_support: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _effective_kinds(proposal: Proposal) -> set[str]:
    kinds: set[str] = set()
    for doc in proposal.documents.all():
        kind = doc.user_override_kind or doc.detected_kind
        if kind and kind != "unknown":
            kinds.add(kind)
    return kinds


def _gtm_config(profile: BankProfile) -> dict[str, Any]:
    return dict((profile.extra_config or {}).get("gtm_product") or {})


def _export_formats(profile: BankProfile) -> list[str]:
    cfg = profile.extra_config or {}
    formats = cfg.get("export_formats")
    if isinstance(formats, list) and formats:
        return [str(f) for f in formats]
    if cfg.get("full_support") and profile.code == BankProfile.Code.BB:
        return ["bb"]
    return []


def _accepted_groups(profile: BankProfile) -> frozenset[str]:
    gtm = _gtm_config(profile)
    raw = gtm.get("accepted_group_codes")
    if isinstance(raw, list) and raw:
        return frozenset(str(x) for x in raw)
    if profile.code == BankProfile.Code.BB:
        return _DEFAULT_PRONAF_GROUPS
    return frozenset()


def _reason(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def evaluate_bank_aptitude(
    proposal: Proposal,
    profile: BankProfile,
    *,
    open_issues: list[Issue] | None = None,
) -> BankAptitudeResult:
    """Score one BankProfile against the shared proposal payload."""
    cfg = profile.extra_config or {}
    formats = _export_formats(profile)
    full_support = bool(cfg.get("full_support"))
    scaffold = bool(cfg.get("scaffold")) or not profile.is_active

    group_code = (proposal.classification_json or {}).get("group_code")
    group_code = str(group_code) if group_code else None

    if scaffold or not formats:
        return BankAptitudeResult(
            bank_code=profile.code,
            bank_name=profile.name,
            status=STATUS_EM_BREVE,
            exportable=False,
            export_formats=[],
            reasons=[
                _reason(
                    "exporter_scaffold",
                    "Bank profile is not export-ready yet.",
                )
            ],
            group_code=group_code,
            full_support=False,
        )

    reasons: list[dict[str, str]] = []
    missing_docs: list[str] = []

    ownership_type = (
        proposal.property.ownership_type if proposal.property_id else None
    ) or None
    marital_status = (
        proposal.proponent.marital_status if proposal.proponent_id else None
    ) or None
    detected = _effective_kinds(proposal)
    required = profile.required_document_kinds(
        ownership_type=ownership_type,
        marital_status=marital_status,
    )
    for kind in required:
        if kind not in detected:
            missing_docs.append(kind)
            reasons.append(
                _reason(
                    f"missing_document_{kind}",
                    f"Required document kind '{kind}' is missing.",
                )
            )

    if not proposal.proponent_id:
        reasons.append(_reason("missing_proponent", "Proponent is required."))
    if not proposal.property_id:
        reasons.append(_reason("missing_property", "Property is required."))

    for path in form_rules.missing_required(build_values(proposal)):
        if path == "credit.financed_amount" and proposal.budget_items.exists():
            continue
        reasons.append(
            _reason("field_required", f"Field '{path}' is required.")
        )

    gtm = _gtm_config(profile)
    purpose = (proposal.credit_purpose or "").strip()
    activity = (proposal.activity_kind or "").strip()
    expected_purpose = gtm.get("credit_purpose")
    expected_activity = gtm.get("activity_kind")
    if expected_purpose and purpose and purpose != expected_purpose:
        reasons.append(
            _reason(
                "product_purpose_mismatch",
                f"credit_purpose '{purpose}' does not match bank GTM product "
                f"'{expected_purpose}'.",
            )
        )
    if expected_activity and activity and activity != expected_activity:
        reasons.append(
            _reason(
                "product_activity_mismatch",
                f"activity_kind '{activity}' does not match bank GTM product "
                f"'{expected_activity}'.",
            )
        )
    if expected_purpose and not purpose:
        reasons.append(
            _reason("missing_credit_purpose", "credit_purpose is required.")
        )
    if expected_activity and not activity:
        reasons.append(
            _reason("missing_activity_kind", "activity_kind is required.")
        )

    if proposal.calculated_at is None:
        reasons.append(
            _reason("not_calculated", "Proposal has not been calculated yet.")
        )
    else:
        capacity = proposal.capacity_json or []
        if any(str(row.get("surplus", "0")).startswith("-") for row in capacity):
            reasons.append(
                _reason(
                    "negative_capacity",
                    "Payment capacity has negative surplus in one or more years.",
                )
            )

    if open_issues is None:
        open_issues = list(
            proposal.issues.filter(resolved_at__isnull=True, severity=Issue.Severity.ERROR)
        )
    for issue in open_issues:
        # Document gaps already listed per-profile; skip duplicates from last validate.
        if issue.code.startswith("missing_document_"):
            continue
        if issue.code in {r["code"] for r in reasons}:
            continue
        if issue.field_path.startswith("documents."):
            continue
        reasons.append(_reason(issue.code, issue.message))

    accepted = _accepted_groups(profile)
    fora = False
    if group_code and accepted and group_code not in accepted:
        fora = True
        reasons.append(
            _reason(
                "group_outside_product",
                f"Producer group '{group_code}' is outside this bank product band.",
            )
        )
    elif proposal.calculated_at and not group_code and accepted:
        reasons.append(
            _reason("missing_classification", "Classification group_code is missing.")
        )

    if fora and not missing_docs:
        # Prefer fora when the only hard product mismatch is enquadramento;
        # still report pendente if checklist/form gaps remain.
        blocking_non_group = [
            r
            for r in reasons
            if r["code"]
            not in {"group_outside_product", "product_purpose_mismatch", "product_activity_mismatch"}
        ]
        if not blocking_non_group:
            status = STATUS_FORA
        else:
            status = STATUS_PENDENTE
    elif reasons:
        status = STATUS_PENDENTE
    else:
        status = STATUS_APTO

    exportable = status == STATUS_APTO and proposal.technician_reviewed_at is not None
    if status == STATUS_APTO and proposal.technician_reviewed_at is None:
        reasons.append(
            _reason(
                "awaiting_technician_review",
                "Technician review is required before export.",
            )
        )

    return BankAptitudeResult(
        bank_code=profile.code,
        bank_name=profile.name,
        status=status,
        exportable=exportable,
        export_formats=formats if status == STATUS_APTO else formats,
        reasons=reasons,
        missing_document_kinds=missing_docs,
        group_code=group_code,
        full_support=full_support,
    )


def evaluate_all_banks(
    proposal: Proposal,
    *,
    refresh_validation: bool = True,
) -> list[BankAptitudeResult]:
    """Evaluate every known BankProfile (active and scaffold) for the UI strip."""
    if refresh_validation:
        validate_proposal(proposal)
        proposal.refresh_from_db()

    open_errors = list(
        proposal.issues.filter(resolved_at__isnull=True, severity=Issue.Severity.ERROR)
    )
    profiles = list(BankProfile.objects.all().order_by("code"))
    return [
        evaluate_bank_aptitude(proposal, profile, open_issues=open_errors)
        for profile in profiles
    ]

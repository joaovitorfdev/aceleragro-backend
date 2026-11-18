"""Form state service: maps the form schema paths onto the proposal models.

Mapping (see docs/form-contract.md):

- ``proponent.*``      -> ``Proponent`` (created lazily, linked via ``Proposal.proponent``)
- ``properties.<i>.*`` -> ``Property`` rows of the proposal ordered by id
- ``credit.*``         -> ``Proposal`` columns
- ``debts.<i>.*``      -> ``ExistingDebt`` rows ordered by id
- ``review.*``         -> ``Proposal.form_extra["review"]``

Provenance and suggestions live in ``Proposal.form_provenance`` / ``form_suggestions``.
Money, rates and decimals are exchanged as strings (never floats). Nothing is ever deleted
when a block becomes hidden (rule 5).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.db import transaction

from acelera_agro.documents.models import Document
from acelera_agro.proposals import form_rules
from acelera_agro.proposals.models import ExistingDebt, Property, Proponent, Proposal
from acelera_agro.tenants.models import Municipality

DECIMAL_TYPES = frozenset({"decimal", "money", "percent"})
TEXT_TYPES = frozenset({"text", "document_number"})
CHOICE_TYPES = frozenset({"select", "radio"})

# (section, field) -> (max_digits, decimal_places) matching the model columns.
DECIMAL_SPEC: dict[tuple[str, str], tuple[int, int]] = {
    ("properties", "area_ha"): (14, 4),
    ("credit", "financed_amount"): (14, 2),
    ("debts", "outstanding_balance"): (14, 2),
    ("debts", "annual_rate"): (10, 6),
}

# Non-null numeric columns whose zero default means "not informed yet".
ZERO_AS_EMPTY = frozenset(
    {
        ("properties", "area_ha"),
        ("credit", "financed_amount"),
        ("debts", "outstanding_balance"),
        ("debts", "annual_rate"),
        ("debts", "remaining_term_years"),
        ("debts", "grace_years"),
    }
)

MAX_SMALL_INT = 32767

EDITABLE_STATUSES = (
    Proposal.Status.DRAFT,
    Proposal.Status.IN_REVIEW,
    Proposal.Status.PENDING_DOCS,
)

READING_STATUSES = (Document.ExtractionStatus.QUEUED, Document.ExtractionStatus.READING)


class FormError(Exception):
    """Invalid form change (bad path, bad value, limit exceeded)."""

    def __init__(self, code: str, message: str, path: str = "") -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class ParsedPath:
    path: str
    section: str
    index: int | None
    field_id: str
    field: dict[str, Any]

    @property
    def key(self) -> tuple[str, str]:
        return (self.section, self.field_id)


def parse_path(path: str) -> ParsedPath:
    """Validate ``section.field`` / ``section.<i>.field`` against the schema."""
    parts = path.split(".") if isinstance(path, str) else []
    section = form_rules.get_section(parts[0]) if parts else None
    if section is None:
        raise FormError("unknown_path", f"Unknown form path: {path}", path)
    repeatable = section["repeatable"]
    index: int | None = None
    if repeatable is None:
        if len(parts) != 2:
            raise FormError("unknown_path", f"Unknown form path: {path}", path)
        field_id = parts[1]
    else:
        if len(parts) != 3 or not parts[1].isdigit():
            raise FormError("unknown_path", f"Unknown form path: {path}", path)
        index = int(parts[1])
        field_id = parts[2]
        if index >= repeatable["max"]:
            raise FormError(
                "max_items_exceeded",
                f"Section '{section['id']}' allows at most {repeatable['max']} items.",
                path,
            )
    field = form_rules.get_field(section["id"], field_id)
    if field is None:
        raise FormError("unknown_path", f"Unknown form path: {path}", path)
    return ParsedPath(path, section["id"], index, field_id, field)


# --------------------------------------------------------------------------- rows


def get_properties(proposal: Proposal) -> list[Property]:
    """Properties of the draft by id; a legacy primary property (no FK) comes first."""
    rows = list(Property.all_objects.filter(proposal_id=proposal.pk).order_by("id"))
    if proposal.property_id and all(r.pk != proposal.property_id for r in rows):
        legacy = Property.all_objects.filter(pk=proposal.property_id).first()
        if legacy is not None:
            rows.insert(0, legacy)
    return rows


def get_debts(proposal: Proposal) -> list[ExistingDebt]:
    return list(ExistingDebt.objects.filter(proposal_id=proposal.pk).order_by("id"))


def _ensure_proponent(proposal: Proposal) -> Proponent:
    if proposal.proponent_id:
        return proposal.proponent
    proponent = Proponent.all_objects.create(
        organization_id=proposal.organization_id,
        full_name="",
        person_type=Proponent.PersonType.INDIVIDUAL,
    )
    proposal.proponent = proponent
    proposal.save(update_fields=["proponent", "updated_at"])
    for prop in get_properties(proposal):
        if prop.proponent_id is None:
            prop.proponent = proponent
            prop.save(update_fields=["proponent", "updated_at"])
    return proponent


def _create_property(proposal: Proposal) -> Property:
    prop = Property.all_objects.create(
        organization_id=proposal.organization_id,
        proposal=proposal,
        proponent_id=proposal.proponent_id,
    )
    if proposal.property_id is None:
        proposal.property = prop
        proposal.save(update_fields=["property", "updated_at"])
    return prop


def get_target(proposal: Proposal, parsed: ParsedPath, *, create: bool) -> Any | None:
    """Row backing a path; with ``create`` the missing rows are created on demand."""
    if parsed.section in ("credit", "review"):
        return proposal
    if parsed.section == "proponent":
        if proposal.proponent_id:
            return proposal.proponent
        return _ensure_proponent(proposal) if create else None
    idx = parsed.index or 0
    if parsed.section == "properties":
        rows = get_properties(proposal)
        while create and len(rows) <= idx:
            rows.append(_create_property(proposal))
    else:
        rows = get_debts(proposal)
        while create and len(rows) <= idx:
            rows.append(ExistingDebt.objects.create(proposal=proposal))
    return rows[idx] if idx < len(rows) else None


# ------------------------------------------------------------------ value codecs


def _places(spec: tuple[int, int]) -> Decimal:
    return Decimal(1).scaleb(-spec[1])


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def normalize_value(parsed: ParsedPath, raw: Any, *, lenient: bool = False) -> Any:
    """Validate ``raw`` and return the canonical JSON value (``None`` clears the field).

    ``lenient`` (autofill) additionally resolves municipalities by name.
    """
    field = parsed.field
    ftype = field["type"]
    path = parsed.path

    if raw is None:
        return None

    if ftype in TEXT_TYPES:
        if not isinstance(raw, str):
            raise FormError("invalid_value", "Expected a string.", path)
        text = raw.strip()
        model_field = _model_field(parsed)
        max_length = getattr(model_field, "max_length", None)
        if max_length and len(text) > max_length:
            raise FormError("value_too_long", f"At most {max_length} characters.", path)
        return text or None

    if ftype in CHOICE_TYPES:
        if not isinstance(raw, str):
            raise FormError("invalid_value", "Expected a string.", path)
        if raw == "":
            return None
        allowed = {o["value"] for o in field.get("options", [])}
        if raw not in allowed:
            raise FormError("invalid_option", f"Invalid option '{raw}'.", path)
        return raw

    if ftype == "boolean":
        if not isinstance(raw, bool):
            raise FormError("invalid_value", "Expected a boolean.", path)
        return raw

    if ftype in DECIMAL_TYPES:
        if isinstance(raw, bool | float) or not isinstance(raw, str | int):
            raise FormError("invalid_value", "Decimals must be sent as strings.", path)
        text = str(raw).strip()
        if text == "":
            return None
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise FormError("invalid_value", "Invalid decimal.", path) from exc
        if not number.is_finite() or number < 0:
            raise FormError("invalid_value", "Expected a non-negative decimal.", path)
        spec = DECIMAL_SPEC.get(parsed.key, (14, 4))
        quantized = number.quantize(_places(spec), rounding=ROUND_HALF_UP)
        if quantized >= Decimal(10) ** (spec[0] - spec[1]):
            raise FormError("invalid_value", "Value out of range.", path)
        return _format_decimal(quantized)

    if ftype == "integer":
        if isinstance(raw, bool) or not isinstance(raw, str | int):
            raise FormError("invalid_value", "Expected an integer.", path)
        text = str(raw).strip()
        if text == "":
            return None
        if not text.isdigit() or int(text) > MAX_SMALL_INT:
            raise FormError("invalid_value", "Expected an integer in range.", path)
        return int(text)

    if ftype == "municipality":
        if not isinstance(raw, str | int) or isinstance(raw, bool):
            raise FormError("invalid_value", "Expected an IBGE code.", path)
        text = str(raw).strip()
        if text == "":
            return None
        muni = Municipality.objects.filter(ibge_code=text).first()
        if muni is None and lenient:
            muni = Municipality.objects.filter(name__iexact=text).first()
        if muni is None:
            raise FormError("unknown_municipality", "Unknown municipality.", path)
        return muni.ibge_code

    raise FormError("invalid_value", f"Unsupported field type {ftype}.", path)


def _model_for(parsed: ParsedPath):
    return {
        "proponent": Proponent,
        "properties": Property,
        "credit": Proposal,
        "debts": ExistingDebt,
    }.get(parsed.section)


def _model_field(parsed: ParsedPath):
    model = _model_for(parsed)
    if model is None:
        return None
    try:
        return model._meta.get_field(parsed.field_id)
    except FieldDoesNotExist:
        return None


def _is_user_locked(proposal: Proposal, path: str) -> bool:
    return (proposal.form_provenance or {}).get(path, {}).get("source") == "user"


def read_value(proposal: Proposal, parsed: ParsedPath) -> Any:
    """Canonical value currently stored for ``parsed`` (``None`` when empty)."""
    target = get_target(proposal, parsed, create=False)
    if target is None:
        return None
    ftype = parsed.field["type"]

    if parsed.section == "review":
        return (proposal.form_extra or {}).get("review", {}).get(parsed.field_id)

    if ftype == "municipality":
        return target.municipality.ibge_code if target.municipality_id else None

    raw = getattr(target, parsed.field_id)
    if raw is None:
        return None

    if ftype in DECIMAL_TYPES:
        if parsed.key in ZERO_AS_EMPTY and raw == 0 and not _is_user_locked(proposal, parsed.path):
            return None
        return _format_decimal(Decimal(raw))
    if ftype == "integer":
        if parsed.key in ZERO_AS_EMPTY and raw == 0 and not _is_user_locked(proposal, parsed.path):
            return None
        return int(raw)
    if ftype == "boolean":
        return bool(raw)
    return raw or None


def write_value(
    proposal: Proposal,
    parsed: ParsedPath,
    canonical: Any,
    entry: dict[str, Any],
) -> None:
    """Persist ``canonical`` for the path, record ``entry`` as provenance, drop a
    suggestion that equals the new value. Rows are created on demand."""
    target = get_target(proposal, parsed, create=True)
    ftype = parsed.field["type"]
    update_fields: list[str] = []

    if parsed.section == "review":
        extra = dict(proposal.form_extra or {})
        review = dict(extra.get("review") or {})
        review[parsed.field_id] = bool(canonical)
        extra["review"] = review
        proposal.form_extra = extra
        update_fields.append("form_extra")
    else:
        attr = parsed.field_id
        model_field = _model_field(parsed)
        nullable = bool(getattr(model_field, "null", False))
        if ftype == "municipality":
            target.municipality = (
                Municipality.objects.get(ibge_code=canonical) if canonical is not None else None
            )
            update_fields.append("municipality")
        else:
            if canonical is None:
                if ftype in DECIMAL_TYPES:
                    value: Any = None if nullable else Decimal(0)
                elif ftype == "integer":
                    value = None if nullable else 0
                elif attr == "person_type":
                    value = Proponent.PersonType.INDIVIDUAL
                elif ftype == "boolean":
                    value = False
                else:
                    value = ""
            elif ftype in DECIMAL_TYPES:
                value = Decimal(canonical)
            else:
                value = canonical
            setattr(target, attr, value)
            update_fields.append(attr)

    provenance = dict(proposal.form_provenance or {})
    provenance[parsed.path] = entry
    proposal.form_provenance = provenance

    suggestions = dict(proposal.form_suggestions or {})
    pending = suggestions.get(parsed.path)
    if pending is not None and pending.get("value") == canonical:
        suggestions.pop(parsed.path)
    proposal.form_suggestions = suggestions

    if target is not proposal:
        if hasattr(target, "field_provenance"):
            target.field_provenance = {**(target.field_provenance or {}), parsed.field_id: entry}
            update_fields.append("field_provenance")
        if hasattr(target, "updated_at"):
            update_fields.append("updated_at")
        target.save(update_fields=update_fields)
        proposal.save(update_fields=["form_provenance", "form_suggestions", "updated_at"])
    else:
        proposal.save(
            update_fields=[*update_fields, "form_provenance", "form_suggestions", "updated_at"]
        )


def save_state(proposal: Proposal) -> None:
    proposal.save(update_fields=["form_provenance", "form_suggestions", "updated_at"])


# ------------------------------------------------------------------- build form


def build_values(proposal: Proposal) -> dict[str, Any]:
    """Form values keyed by section; empty fields are omitted (schema defaults applied)."""
    values: dict[str, Any] = {}
    for section in form_rules.load_schema()["sections"]:
        sid = section["id"]
        if section["repeatable"] is None:
            values[sid] = _section_values(proposal, sid, None)
        else:
            rows = get_properties(proposal) if sid == "properties" else get_debts(proposal)
            values[sid] = [_section_values(proposal, sid, i) for i in range(len(rows))]
    return values


def _section_values(proposal: Proposal, sid: str, index: int | None) -> dict[str, Any]:
    section = form_rules.get_section(sid)
    assert section is not None
    out: dict[str, Any] = {}
    for field in section["fields"]:
        base = sid if index is None else f"{sid}.{index}"
        parsed = parse_path(f"{base}.{field['id']}")
        value = read_value(proposal, parsed)
        if value is None and "default" in field:
            value = field["default"]
        if value is not None:
            out[field["id"]] = value
    return out


def document_status(document: Document) -> str:
    """Contract-level status derived from ``extraction_status`` and the detected kind."""
    status = document.extraction_status
    S = Document.ExtractionStatus
    if status == S.READING:
        return "reading"
    if status == S.FAILED:
        return "failed"
    if status in (S.PENDING, S.QUEUED):
        return "queued"
    kind = document.effective_kind
    if not kind or kind == "unknown":
        return "unrecognized"
    return "recognized"


def is_reading(proposal: Proposal) -> bool:
    return Document.all_objects.filter(
        proposal_id=proposal.pk, extraction_status__in=READING_STATUSES
    ).exists()


def _labels(proposal: Proposal) -> dict[str, str]:
    labels: dict[str, str] = {}
    for i, prop in enumerate(get_properties(proposal)):
        if prop.municipality_id:
            muni = prop.municipality
            labels[f"properties.{i}.municipality"] = f"{muni.name}/{muni.state_uf}"
    return labels


def get_form(proposal: Proposal) -> dict[str, Any]:
    documents = Document.all_objects.filter(proposal_id=proposal.pk).order_by("id")
    return {
        "values": build_values(proposal),
        "provenance": dict(proposal.form_provenance or {}),
        "suggestions": dict(proposal.form_suggestions or {}),
        "documents": [
            {
                "id": d.id,
                "filename": d.original_filename,
                "detected_kind": d.effective_kind,
                "status": document_status(d),
            }
            for d in documents
        ],
        "reading": is_reading(proposal),
        "labels": _labels(proposal),
    }


# ---------------------------------------------------------------- user changes


def lock_proposal(proposal: Proposal) -> None:
    """Row-lock (where supported) and reload so concurrent writers do not clobber state."""
    Proposal.all_objects.select_for_update().filter(pk=proposal.pk).first()
    proposal.refresh_from_db()


@transaction.atomic
def apply_user_changes(proposal: Proposal, changes: list[dict[str, Any]]) -> Proposal:
    """Apply ``[{path, value?, dismiss_suggestion?}]`` as user edits (locks).

    All changes are applied atomically; the first invalid change aborts with ``FormError``.
    """
    lock_proposal(proposal)
    for change in changes:
        parsed = parse_path(change.get("path", ""))
        if change.get("dismiss_suggestion"):
            suggestions = dict(proposal.form_suggestions or {})
            suggestions.pop(parsed.path, None)
            proposal.form_suggestions = suggestions
            save_state(proposal)
        if "value" in change:
            canonical = normalize_value(parsed, change["value"])
            write_value(proposal, parsed, canonical, {"source": "user"})
    return proposal

from __future__ import annotations

from ninja import Schema


class ProposalCreateIn(Schema):
    proponent_id: int
    property_id: int | None = None
    bank_profile_id: int | None = None
    credit_line_id: int | None = None
    crop_year_id: int | None = None
    ruleset_id: int | None = None
    financed_amount: str | None = None
    annual_rate: str | None = None
    term_years: int | None = None
    grace_years: int | None = None
    family_maintenance: str | None = None
    total_rba: str | None = None
    agro_revenue_share: str | None = None
    referral_code: str | None = None


class ProposalOut(Schema):
    id: int
    office_id: int
    organization_id: int
    proponent_id: int | None = None
    property_id: int | None = None
    bank_profile_id: int | None = None
    credit_line_id: int | None = None
    status: str
    financed_amount: str
    schedule_json: list
    capacity_json: list
    classification_json: dict
    technician_reviewed_at: str | None = None
    calculated_at: str | None = None


class IssueOut(Schema):
    id: int
    code: str
    message: str
    severity: str
    field_path: str
    resolved_at: str | None = None


class MessageOut(Schema):
    detail: str


class AptitudeReasonOut(Schema):
    code: str
    message: str


class BankAptitudeOut(Schema):
    bank_code: str
    bank_name: str
    status: str
    exportable: bool
    export_formats: list[str]
    reasons: list[AptitudeReasonOut]
    missing_document_kinds: list[str]
    group_code: str | None = None
    full_support: bool = False


class BankAptitudeListOut(Schema):
    items: list[BankAptitudeOut]

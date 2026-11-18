from __future__ import annotations

from decimal import Decimal

from ninja import Schema


class OrganizationIn(Schema):
    name: str
    trade_name: str = ""
    cnpj: str


class OwnerIn(Schema):
    email: str
    password: str
    full_name: str = ""


class CreateTenantIn(Schema):
    """Signup: organization + owner only (office comes later)."""

    organization: OrganizationIn
    owner: OwnerIn


class CreateTenantOut(Schema):
    organization_id: int
    user_id: int
    email: str
    detail: str = (
        "Tenant created. Sign in, then add your first office to unlock the app."
    )


class CreateOfficeIn(Schema):
    """Owner/admin adds an office — address and phone required (PDF + contact)."""

    name: str
    municipality_ibge: str
    address: str
    phone: str
    technical_responsible_name: str = ""
    technical_council_id: str = ""
    referral_code: str | None = None
    # Optional: activate device when this becomes the active membership.
    device_fingerprint: str | None = None
    lat: Decimal | None = None
    lng: Decimal | None = None


class MunicipalityOut(Schema):
    ibge_code: str
    name: str
    state_uf: str


class OfficeOut(Schema):
    id: int
    name: str
    status: str
    address: str
    phone: str
    referral_code: str | None
    technical_responsible_name: str
    technical_council_id: str
    municipality: MunicipalityOut


class CreateOfficeOut(Schema):
    office: OfficeOut
    access_token: str | None = None
    tenant_id: int | None = None
    office_id: int | None = None
    role: str | None = None
    device_id: int | None = None
    needs_office: bool = False


class OrganizationOut(Schema):
    id: int
    name: str
    trade_name: str
    cnpj: str
    is_active: bool
    logo_key: str
    banner_key: str
    needs_office: bool
    offices: list[OfficeOut]


class UpdateOrganizationIn(Schema):
    """Owner updates tenant brand profile (CNPJ immutable)."""

    name: str | None = None
    trade_name: str | None = None


class UpdateOfficeIn(Schema):
    """Edit office contact/label fields. Municipality is immutable (territorial lock)."""

    name: str | None = None
    address: str | None = None
    phone: str | None = None
    technical_responsible_name: str | None = None
    technical_council_id: str | None = None


class OfficeStatusIn(Schema):
    """active | suspended (inactive reserved for billing/ops later)."""

    status: str


class MembershipOut(Schema):
    id: int
    role: str
    is_active: bool
    office_id: int
    office_name: str
    organization_id: int
    organization_name: str
    municipality_ibge: str
    municipality_name: str
    user_id: int | None = None
    user_email: str | None = None
    user_full_name: str | None = None


class SwitchMembershipIn(Schema):
    membership_id: int
    device_fingerprint: str
    lat: Decimal | None = None
    lng: Decimal | None = None


class InviteMemberIn(Schema):
    email: str
    role: str
    full_name: str = ""
    password: str | None = None


class InviteMemberOut(Schema):
    membership: MembershipOut
    created_user: bool
    temporary_password: str | None = None
    detail: str = "Member invited. Share credentials out of band if a new user was created."


class DeviceOut(Schema):
    id: int
    office_id: int
    office_name: str
    device_fingerprint: str
    is_active: bool
    needs_revalidation: bool
    activated_at: str | None
    last_seen_at: str | None

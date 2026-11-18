"""Tenant lifecycle: create organization, add offices, switch membership, team."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q

from acelera_agro.tenants.models import Device, Membership, Municipality, Office, Organization

User = get_user_model()

_CNPJ_DIGITS = re.compile(r"\D+")

INVITABLE_ROLES = frozenset(
    {
        Membership.Role.ADMIN,
        Membership.Role.TECHNICIAN,
        Membership.Role.VIEWER,
    }
)


class TenantServiceError(Exception):
    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def normalize_cnpj(raw: str) -> str:
    return _CNPJ_DIGITS.sub("", raw or "")


def validate_cnpj(raw: str) -> str:
    digits = normalize_cnpj(raw)
    if len(digits) != 14:
        raise TenantServiceError("invalid_cnpj", "CNPJ must have 14 digits.")
    if digits == digits[0] * 14:
        raise TenantServiceError("invalid_cnpj", "CNPJ is invalid.")
    return digits


def _referral_code(prefix: str = "REF") -> str:
    return f"{prefix}-{secrets.token_hex(4).upper()}"


@dataclass(frozen=True)
class CreatedTenant:
    organization: Organization
    user: object


def get_owned_organization(user) -> Organization | None:
    if user is None:
        return None
    return (
        Organization.objects.filter(owner=user, is_active=True)
        .order_by("id")
        .first()
    )


@transaction.atomic
def create_tenant(
    *,
    organization_name: str,
    organization_trade_name: str,
    organization_cnpj: str,
    owner_email: str,
    owner_password: str,
    owner_full_name: str,
) -> CreatedTenant:
    """Signup: Organization + owner user only (no office yet — Marco T3)."""
    name = (organization_name or "").strip()
    if not name:
        raise TenantServiceError("organization_name_required")

    cnpj = validate_cnpj(organization_cnpj)
    if Organization.objects.filter(cnpj=cnpj).exists():
        raise TenantServiceError("cnpj_taken", "CNPJ already registered.")

    email = (owner_email or "").strip().lower()
    if not email or "@" not in email:
        raise TenantServiceError("invalid_email")
    if len(owner_password or "") < 8:
        raise TenantServiceError("weak_password", "Password must be at least 8 characters.")
    if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exists():
        raise TenantServiceError("email_taken")

    first, *rest = (owner_full_name or "").strip().split(" ", 1)
    user = User.objects.create_user(
        username=email,
        email=email,
        password=owner_password,
        first_name=first[:150],
        last_name=(rest[0] if rest else "")[:150],
    )
    org = Organization.objects.create(
        name=name,
        trade_name=(organization_trade_name or "").strip(),
        cnpj=cnpj,
        owner=user,
        is_active=True,
    )
    return CreatedTenant(organization=org, user=user)


def user_is_org_owner_or_admin(user, organization_id: int) -> bool:
    if Organization.objects.filter(pk=organization_id, owner=user).exists():
        return True
    return Membership.objects.filter(
        user=user,
        office__organization_id=organization_id,
        role__in=[Membership.Role.OWNER, Membership.Role.ADMIN],
    ).exists()


@transaction.atomic
def update_organization_profile(
    *,
    organization: Organization,
    acting_user,
    name: str | None = None,
    trade_name: str | None = None,
) -> Organization:
    if not user_is_org_owner_or_admin(acting_user, organization.id):
        raise TenantServiceError("forbidden", "Owner or admin role required.")
    fields: list[str] = []
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise TenantServiceError("organization_name_required")
        organization.name = cleaned
        fields.append("name")
    if trade_name is not None:
        organization.trade_name = trade_name.strip()
        fields.append("trade_name")
    if fields:
        fields.append("updated_at")
        organization.save(update_fields=fields)
    return organization


@transaction.atomic
def create_office_for_organization(
    *,
    organization: Organization,
    acting_user,
    name: str,
    municipality_ibge: str,
    address: str = "",
    phone: str = "",
    technical_responsible_name: str = "",
    technical_council_id: str = "",
    referral_code: str | None = None,
) -> tuple[Office, Membership]:
    if not user_is_org_owner_or_admin(acting_user, organization.id):
        raise TenantServiceError("forbidden", "Owner or admin role required.")

    office_label = (name or "").strip()
    if not office_label:
        raise TenantServiceError("office_name_required")
    office_address = (address or "").strip()
    office_phone = (phone or "").strip()
    if not office_address:
        raise TenantServiceError("office_address_required")
    if not office_phone:
        raise TenantServiceError("office_phone_required")

    municipality = Municipality.objects.filter(ibge_code=municipality_ibge.strip()).first()
    if municipality is None:
        raise TenantServiceError("municipality_not_found")

    if Office.objects.filter(
        organization=organization, municipality=municipality
    ).exists():
        raise TenantServiceError(
            "office_municipality_taken",
            "This organization already has an office in that municipality.",
        )

    code = (referral_code or "").strip() or _referral_code()
    if Office.objects.filter(referral_code=code).exists():
        raise TenantServiceError("referral_code_taken")

    office = Office.objects.create(
        organization=organization,
        municipality=municipality,
        name=office_label,
        address=office_address,
        phone=office_phone,
        status=Office.Status.ACTIVE,
        referral_code=code,
        technical_responsible_name=(technical_responsible_name or "").strip(),
        technical_council_id=(technical_council_id or "").strip(),
    )

    has_active = Membership.objects.filter(user=acting_user, is_active=True).exists()
    # First office for this user becomes the active membership (unlocks the app).
    membership = Membership.objects.create(
        user=acting_user,
        office=office,
        role=Membership.Role.OWNER,
        is_active=not has_active,
    )
    return office, membership


@transaction.atomic
def update_office(
    *,
    organization: Organization,
    acting_user,
    office_id: int,
    name: str | None = None,
    address: str | None = None,
    phone: str | None = None,
    technical_responsible_name: str | None = None,
    technical_council_id: str | None = None,
) -> Office:
    if not user_is_org_owner_or_admin(acting_user, organization.id):
        raise TenantServiceError("forbidden", "Owner or admin role required.")

    office = (
        Office.objects.select_related("municipality")
        .filter(pk=office_id, organization=organization)
        .first()
    )
    if office is None:
        raise TenantServiceError("office_not_found")

    fields: list[str] = []
    if name is not None:
        cleaned = name.strip()
        if not cleaned:
            raise TenantServiceError("office_name_required")
        office.name = cleaned
        fields.append("name")
    if address is not None:
        cleaned = address.strip()
        if not cleaned:
            raise TenantServiceError("office_address_required")
        office.address = cleaned
        fields.append("address")
    if phone is not None:
        cleaned = phone.strip()
        if not cleaned:
            raise TenantServiceError("office_phone_required")
        office.phone = cleaned
        fields.append("phone")
    if technical_responsible_name is not None:
        office.technical_responsible_name = technical_responsible_name.strip()
        fields.append("technical_responsible_name")
    if technical_council_id is not None:
        office.technical_council_id = technical_council_id.strip()
        fields.append("technical_council_id")

    if fields:
        fields.append("updated_at")
        office.save(update_fields=fields)
    return office


@transaction.atomic
def set_office_status(
    *,
    organization: Organization,
    acting_user,
    office_id: int,
    status: str,
) -> Office:
    if not user_is_org_owner_or_admin(acting_user, organization.id):
        raise TenantServiceError("forbidden", "Owner or admin role required.")

    office = (
        Office.objects.select_related("municipality")
        .filter(pk=office_id, organization=organization)
        .first()
    )
    if office is None:
        raise TenantServiceError("office_not_found")

    allowed = {Office.Status.ACTIVE, Office.Status.SUSPENDED}
    if status not in allowed:
        raise TenantServiceError(
            "invalid_office_status",
            "Status must be active or suspended.",
        )

    if office.status == status:
        return office

    office.status = status
    office.save(update_fields=["status", "updated_at"])
    return office


@dataclass(frozen=True)
class InvitedMember:
    membership: Membership
    user: object
    created_user: bool
    temporary_password: str | None


@transaction.atomic
def invite_office_member(
    *,
    organization: Organization,
    acting_user,
    office_id: int,
    email: str,
    role: str,
    full_name: str = "",
    password: str | None = None,
) -> InvitedMember:
    """Add a user to an office. New users get a temp password (returned once)."""
    if not user_is_org_owner_or_admin(acting_user, organization.id):
        raise TenantServiceError("forbidden", "Owner or admin role required.")

    office = Office.objects.filter(pk=office_id, organization=organization).first()
    if office is None:
        raise TenantServiceError("office_not_found")

    role_clean = (role or "").strip().lower()
    if role_clean not in INVITABLE_ROLES:
        raise TenantServiceError(
            "invalid_role",
            "Role must be admin, technician, or viewer.",
        )

    email_clean = (email or "").strip().lower()
    if not email_clean or "@" not in email_clean:
        raise TenantServiceError("invalid_email")

    user = User.objects.filter(
        Q(email__iexact=email_clean) | Q(username__iexact=email_clean)
    ).first()
    created_user = False
    temporary_password: str | None = None

    if user is None:
        temporary_password = (password or "").strip() or secrets.token_urlsafe(10)
        if len(temporary_password) < 8:
            raise TenantServiceError("weak_password", "Password must be at least 8 characters.")
        first, *rest = (full_name or "").strip().split(" ", 1)
        user = User.objects.create_user(
            username=email_clean,
            email=email_clean,
            password=temporary_password,
            first_name=first[:150],
            last_name=(rest[0] if rest else "")[:150],
        )
        created_user = True
    elif Membership.objects.filter(user=user, office=office).exists():
        raise TenantServiceError("membership_exists", "User is already a member of this office.")

    # Invited membership starts inactive so it does not steal the invitee's active office.
    membership = Membership.objects.create(
        user=user,
        office=office,
        role=role_clean,
        is_active=False,
    )
    membership = (
        Membership.objects.select_related(
            "user",
            "office",
            "office__organization",
            "office__municipality",
        ).get(pk=membership.pk)
    )
    return InvitedMember(
        membership=membership,
        user=user,
        created_user=created_user,
        temporary_password=temporary_password,
    )


@transaction.atomic
def remove_office_member(
    *,
    organization: Organization,
    acting_user,
    office_id: int,
    membership_id: int,
) -> None:
    if not user_is_org_owner_or_admin(acting_user, organization.id):
        raise TenantServiceError("forbidden", "Owner or admin role required.")

    membership = (
        Membership.objects.select_related("office", "user")
        .filter(pk=membership_id, office_id=office_id, office__organization=organization)
        .first()
    )
    if membership is None:
        raise TenantServiceError("membership_not_found")
    if membership.role == Membership.Role.OWNER:
        raise TenantServiceError("cannot_remove_owner", "Owner memberships cannot be removed.")
    if membership.user_id == acting_user.id:
        raise TenantServiceError("cannot_remove_self", "You cannot remove your own membership.")

    membership.delete()


@transaction.atomic
def activate_first_inactive_membership(*, user) -> Membership | None:
    """For invited users with only inactive memberships — pick the first and activate."""
    if Membership.objects.filter(user=user, is_active=True).exists():
        return None
    target = (
        Membership.objects.select_related(
            "office", "office__organization", "office__municipality"
        )
        .filter(user=user, office__status=Office.Status.ACTIVE)
        .order_by("id")
        .first()
    )
    if target is None:
        return None
    target.is_active = True
    target.save(update_fields=["is_active", "updated_at"])
    return target


@transaction.atomic
def revoke_device(*, user, device_id: int) -> Device:
    device = Device.objects.filter(pk=device_id, user=user).first()
    if device is None:
        raise TenantServiceError("device_not_found")
    device.is_active = False
    device.needs_revalidation = True
    device.save(update_fields=["is_active", "needs_revalidation"])
    return device


@transaction.atomic
def switch_active_membership(*, user, membership_id: int) -> Membership:
    target = (
        Membership.objects.select_related(
            "office", "office__organization", "office__municipality"
        )
        .filter(pk=membership_id, user=user)
        .first()
    )
    if target is None:
        raise TenantServiceError("membership_not_found")
    if not target.office.organization.is_active:
        raise TenantServiceError("organization_inactive")
    if target.office.status == Office.Status.INACTIVE:
        raise TenantServiceError("office_inactive")

    Membership.objects.filter(user=user, is_active=True).exclude(pk=target.pk).update(
        is_active=False
    )
    if not target.is_active:
        target.is_active = True
        target.save(update_fields=["is_active", "updated_at"])
    return target

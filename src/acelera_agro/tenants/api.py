"""Tenant onboarding and membership APIs (Marco T1 / T3 / T2)."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from ninja import File, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja.responses import Status

from acelera_agro.accounts.auth import jwt_auth
from acelera_agro.accounts.jwt_utils import issue_access_token, issue_refresh_token
from acelera_agro.accounts.schemas import TokenOut
from acelera_agro.audit.services import log_audit
from acelera_agro.documents.storage import build_org_brand_key, put_object_bytes
from acelera_agro.tenants.models import (
    Device,
    Membership,
    Office,
    Organization,
    get_active_membership,
)
from acelera_agro.tenants.schemas import (
    CreateOfficeIn,
    CreateOfficeOut,
    CreateTenantIn,
    CreateTenantOut,
    DeviceOut,
    InviteMemberIn,
    InviteMemberOut,
    MembershipOut,
    MunicipalityOut,
    OfficeOut,
    OfficeStatusIn,
    OrganizationOut,
    SwitchMembershipIn,
    UpdateOfficeIn,
    UpdateOrganizationIn,
)
from acelera_agro.tenants.services import (
    TenantServiceError,
    create_office_for_organization,
    create_tenant,
    get_owned_organization,
    invite_office_member,
    remove_office_member,
    revoke_device,
    set_office_status,
    switch_active_membership,
    update_office,
    update_organization_profile,
    user_is_org_owner_or_admin,
)
from acelera_agro.tenants.territorial import TerritorialLockError, activate_device_in_municipality

router = Router(tags=["tenants"])

_BRAND_MAX_BYTES = 2 * 1024 * 1024
_BRAND_CONTENT_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}


def _client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _set_refresh_cookie(response: HttpResponse, token: str) -> None:
    from django.conf import settings

    response.set_cookie(
        key=settings.JWT_REFRESH_COOKIE_NAME,
        value=token,
        max_age=int(settings.JWT_REFRESH_TTL.total_seconds()),
        path=settings.JWT_REFRESH_COOKIE_PATH,
        httponly=settings.JWT_REFRESH_COOKIE_HTTPONLY,
        secure=settings.JWT_REFRESH_COOKIE_SECURE,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
    )


def _office_out(office: Office) -> OfficeOut:
    mun = office.municipality
    return OfficeOut(
        id=office.id,
        name=office.name,
        status=office.status,
        address=office.address,
        phone=office.phone,
        referral_code=office.referral_code,
        technical_responsible_name=office.technical_responsible_name,
        technical_council_id=office.technical_council_id,
        municipality=MunicipalityOut(
            ibge_code=mun.ibge_code,
            name=mun.name,
            state_uf=mun.state_uf,
        ),
    )


def _membership_out(m: Membership) -> MembershipOut:
    office = m.office
    org = office.organization
    mun = office.municipality
    user = m.user
    full_name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
    return MembershipOut(
        id=m.id,
        role=m.role,
        is_active=m.is_active,
        office_id=office.id,
        office_name=office.name,
        organization_id=org.id,
        organization_name=org.name,
        municipality_ibge=mun.ibge_code,
        municipality_name=f"{mun.name}/{mun.state_uf}",
        user_id=user.id,
        user_email=getattr(user, "email", "") or "",
        user_full_name=full_name or None,
    )


def _device_out(d: Device) -> DeviceOut:
    office = d.office
    return DeviceOut(
        id=d.id,
        office_id=office.id,
        office_name=office.name,
        device_fingerprint=d.device_fingerprint,
        is_active=d.is_active,
        needs_revalidation=d.needs_revalidation,
        activated_at=d.activated_at.isoformat() if d.activated_at else None,
        last_seen_at=d.last_seen_at.isoformat() if d.last_seen_at else None,
    )


def _map_service_error(exc: TenantServiceError) -> HttpError:
    status = {
        "forbidden": 403,
        "membership_not_found": 404,
        "office_not_found": 404,
        "device_not_found": 404,
        "municipality_not_found": 400,
        "cnpj_taken": 409,
        "email_taken": 409,
        "membership_exists": 409,
        "referral_code_taken": 409,
        "office_municipality_taken": 409,
        "organization_inactive": 403,
        "office_inactive": 403,
        "invalid_office_status": 400,
        "invalid_role": 400,
        "cannot_remove_owner": 400,
        "cannot_remove_self": 400,
    }.get(exc.code, 400)
    return HttpError(status, str(exc) or exc.code)


@router.post("/tenants", response={201: CreateTenantOut})
def create_tenant_endpoint(request: HttpRequest, payload: CreateTenantIn):
    """Public: create Organization + owner user (office added later)."""
    try:
        created = create_tenant(
            organization_name=payload.organization.name,
            organization_trade_name=payload.organization.trade_name,
            organization_cnpj=payload.organization.cnpj,
            owner_email=payload.owner.email,
            owner_password=payload.owner.password,
            owner_full_name=payload.owner.full_name,
        )
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc

    log_audit(
        action="tenants.create",
        resource_type="organization",
        resource_id=created.organization.id,
        user=created.user,
        organization_id=created.organization.id,
        office_id=None,
        ip=_client_ip(request),
        detail={"email": created.user.email},
    )
    return Status(
        201,
        CreateTenantOut(
            organization_id=created.organization.id,
            user_id=created.user.id,
            email=created.user.email,
        ),
    )


def _resolve_org_for_user(user) -> Organization:
    membership = get_active_membership(user)
    if membership is not None:
        return membership.office.organization
    org = get_owned_organization(user)
    if org is None:
        raise HttpError(403, "No organization")
    return org


def _organization_out(org: Organization, user) -> OrganizationOut:
    membership = get_active_membership(user)
    role = membership.role if membership else Membership.Role.OWNER
    if role in (Membership.Role.OWNER, Membership.Role.ADMIN) or org.owner_id == user.id:
        offices = list(
            Office.objects.select_related("municipality")
            .filter(organization=org)
            .order_by("name")
        )
    else:
        offices = [membership.office] if membership else []
    return OrganizationOut(
        id=org.id,
        name=org.name,
        trade_name=org.trade_name,
        cnpj=org.cnpj,
        is_active=org.is_active,
        logo_key=org.logo_key,
        banner_key=org.banner_key,
        needs_office=len(offices) == 0,
        offices=[_office_out(o) for o in offices],
    )


def _assert_can_edit_org(user, org: Organization) -> None:
    if not user_is_org_owner_or_admin(user, org.id):
        raise HttpError(403, "Owner or admin role required")


def _read_brand_image(upload: UploadedFile | None) -> tuple[bytes, str]:
    if upload is None:
        raise HttpError(400, "file is required")
    content_type = (getattr(upload, "content_type", None) or "").lower()
    if content_type and content_type not in _BRAND_CONTENT_TYPES:
        raise HttpError(400, "Image must be PNG, JPEG or WebP")
    data = upload.read()
    if not data:
        raise HttpError(400, "Empty file")
    if len(data) > _BRAND_MAX_BYTES:
        raise HttpError(400, "Image exceeds 2 MiB limit")
    return data, content_type or "application/octet-stream"


@router.get("/tenants/me", auth=jwt_auth, response=OrganizationOut)
def tenant_me(request: HttpRequest):
    org = _resolve_org_for_user(request.user)
    return _organization_out(org, request.user)


@router.patch("/tenants/me", auth=jwt_auth, response=OrganizationOut)
def update_tenant_me(request: HttpRequest, payload: UpdateOrganizationIn):
    org = _resolve_org_for_user(request.user)
    _assert_can_edit_org(request.user, org)
    try:
        org = update_organization_profile(
            organization=org,
            acting_user=request.user,
            name=payload.name,
            trade_name=payload.trade_name,
        )
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc
    log_audit(
        action="tenants.profile_update",
        resource_type="organization",
        resource_id=org.id,
        user=request.user,
        organization_id=org.id,
        office_id=None,
        ip=_client_ip(request),
    )
    return _organization_out(org, request.user)


@router.post("/tenants/me/logo", auth=jwt_auth, response=OrganizationOut)
def upload_tenant_logo(
    request: HttpRequest, file: UploadedFile = File(...),  # noqa: B008
):
    org = _resolve_org_for_user(request.user)
    _assert_can_edit_org(request.user, org)
    data, content_type = _read_brand_image(file)
    key = build_org_brand_key(
        organization_id=org.id,
        kind="logo",
        filename=getattr(file, "name", None) or "logo.png",
    )
    put_object_bytes(key=key, data=data, content_type=content_type)
    org.logo_key = key
    org.save(update_fields=["logo_key", "updated_at"])
    log_audit(
        action="tenants.logo_upload",
        resource_type="organization",
        resource_id=org.id,
        user=request.user,
        organization_id=org.id,
        office_id=None,
        ip=_client_ip(request),
        detail={"key": key},
    )
    return _organization_out(org, request.user)


@router.post("/tenants/me/banner", auth=jwt_auth, response=OrganizationOut)
def upload_tenant_banner(
    request: HttpRequest, file: UploadedFile = File(...),  # noqa: B008
):
    org = _resolve_org_for_user(request.user)
    _assert_can_edit_org(request.user, org)
    data, content_type = _read_brand_image(file)
    key = build_org_brand_key(
        organization_id=org.id,
        kind="banner",
        filename=getattr(file, "name", None) or "banner.png",
    )
    put_object_bytes(key=key, data=data, content_type=content_type)
    org.banner_key = key
    org.save(update_fields=["banner_key", "updated_at"])
    log_audit(
        action="tenants.banner_upload",
        resource_type="organization",
        resource_id=org.id,
        user=request.user,
        organization_id=org.id,
        office_id=None,
        ip=_client_ip(request),
        detail={"key": key},
    )
    return _organization_out(org, request.user)


@router.delete("/tenants/me/logo", auth=jwt_auth, response=OrganizationOut)
def clear_tenant_logo(request: HttpRequest):
    org = _resolve_org_for_user(request.user)
    _assert_can_edit_org(request.user, org)
    org.logo_key = ""
    org.save(update_fields=["logo_key", "updated_at"])
    log_audit(
        action="tenants.logo_clear",
        resource_type="organization",
        resource_id=org.id,
        user=request.user,
        organization_id=org.id,
        ip=_client_ip(request),
    )
    return _organization_out(org, request.user)


@router.delete("/tenants/me/banner", auth=jwt_auth, response=OrganizationOut)
def clear_tenant_banner(request: HttpRequest):
    org = _resolve_org_for_user(request.user)
    _assert_can_edit_org(request.user, org)
    org.banner_key = ""
    org.save(update_fields=["banner_key", "updated_at"])
    log_audit(
        action="tenants.banner_clear",
        resource_type="organization",
        resource_id=org.id,
        user=request.user,
        organization_id=org.id,
        ip=_client_ip(request),
    )
    return _organization_out(org, request.user)


@router.post("/tenants/offices", auth=jwt_auth, response={201: CreateOfficeOut})
def create_office_endpoint(
    request: HttpRequest, payload: CreateOfficeIn, response: HttpResponse
):
    org = _resolve_org_for_user(request.user)
    try:
        office, membership = create_office_for_organization(
            organization=org,
            acting_user=request.user,
            name=payload.name,
            municipality_ibge=payload.municipality_ibge,
            address=payload.address,
            phone=payload.phone,
            technical_responsible_name=payload.technical_responsible_name,
            technical_council_id=payload.technical_council_id,
            referral_code=payload.referral_code,
        )
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc

    log_audit(
        action="tenants.office_create",
        resource_type="office",
        resource_id=office.id,
        user=request.user,
        organization_id=org.id,
        office_id=office.id,
        ip=_client_ip(request),
    )

    out = CreateOfficeOut(office=_office_out(office), needs_office=False)
    if membership.is_active and payload.device_fingerprint:
        try:
            device = activate_device_in_municipality(
                user=request.user,
                office=office,
                device_fingerprint=payload.device_fingerprint,
                lat=payload.lat,
                lng=payload.lng,
            )
        except TerritorialLockError as exc:
            raise HttpError(403, str(exc)) from exc
        access = issue_access_token(
            user_id=request.user.id,
            tenant_id=org.id,
            office_id=office.id,
            role=membership.role,
            device_id=device.id,
        )
        refresh, _session = issue_refresh_token(
            user_id=request.user.id,
            office_id=office.id,
            device_id=device.id,
        )
        _set_refresh_cookie(response, refresh)
        out.access_token = access
        out.tenant_id = org.id
        out.office_id = office.id
        out.role = membership.role
        out.device_id = device.id

    return Status(201, out)


@router.patch("/tenants/offices/{office_id}", auth=jwt_auth, response=OfficeOut)
def update_office_endpoint(
    request: HttpRequest, office_id: int, payload: UpdateOfficeIn
):
    """Owner/admin edit office fields in-place (municipality immutable)."""
    org = _resolve_org_for_user(request.user)
    try:
        office = update_office(
            organization=org,
            acting_user=request.user,
            office_id=office_id,
            name=payload.name,
            address=payload.address,
            phone=payload.phone,
            technical_responsible_name=payload.technical_responsible_name,
            technical_council_id=payload.technical_council_id,
        )
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc

    log_audit(
        action="tenants.office_update",
        resource_type="office",
        resource_id=office.id,
        user=request.user,
        organization_id=org.id,
        office_id=office.id,
        ip=_client_ip(request),
    )
    return _office_out(office)


@router.post("/tenants/offices/{office_id}/status", auth=jwt_auth, response=OfficeOut)
def set_office_status_endpoint(
    request: HttpRequest, office_id: int, payload: OfficeStatusIn
):
    """Suspend (read-only) or reactivate an office. Does not depend on office mutate RBAC."""
    org = _resolve_org_for_user(request.user)
    try:
        office = set_office_status(
            organization=org,
            acting_user=request.user,
            office_id=office_id,
            status=payload.status,
        )
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc

    log_audit(
        action="tenants.office_status",
        resource_type="office",
        resource_id=office.id,
        user=request.user,
        organization_id=org.id,
        office_id=office.id,
        ip=_client_ip(request),
        detail={"status": office.status},
    )
    return _office_out(office)


@router.get(
    "/tenants/offices/{office_id}/members",
    auth=jwt_auth,
    response=list[MembershipOut],
)
def list_office_members(request: HttpRequest, office_id: int):
    org = _resolve_org_for_user(request.user)
    _assert_can_edit_org(request.user, org)
    office = Office.objects.filter(pk=office_id, organization=org).first()
    if office is None:
        raise HttpError(404, "office_not_found")
    rows = (
        Membership.objects.select_related(
            "user",
            "office",
            "office__organization",
            "office__municipality",
        )
        .filter(office=office)
        .order_by("role", "user__email")
    )
    return [_membership_out(m) for m in rows]


@router.post(
    "/tenants/offices/{office_id}/members",
    auth=jwt_auth,
    response={201: InviteMemberOut},
)
def invite_office_member_endpoint(
    request: HttpRequest, office_id: int, payload: InviteMemberIn
):
    org = _resolve_org_for_user(request.user)
    try:
        invited = invite_office_member(
            organization=org,
            acting_user=request.user,
            office_id=office_id,
            email=payload.email,
            role=payload.role,
            full_name=payload.full_name,
            password=payload.password,
        )
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc

    log_audit(
        action="tenants.member_invite",
        resource_type="membership",
        resource_id=invited.membership.id,
        user=request.user,
        organization_id=org.id,
        office_id=office_id,
        ip=_client_ip(request),
        detail={"email": invited.user.email, "role": invited.membership.role},
    )
    return Status(
        201,
        InviteMemberOut(
            membership=_membership_out(invited.membership),
            created_user=invited.created_user,
            temporary_password=invited.temporary_password,
        ),
    )


@router.delete(
    "/tenants/offices/{office_id}/members/{membership_id}",
    auth=jwt_auth,
    response={204: None},
)
def remove_office_member_endpoint(
    request: HttpRequest, office_id: int, membership_id: int
):
    org = _resolve_org_for_user(request.user)
    try:
        remove_office_member(
            organization=org,
            acting_user=request.user,
            office_id=office_id,
            membership_id=membership_id,
        )
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc

    log_audit(
        action="tenants.member_remove",
        resource_type="membership",
        resource_id=membership_id,
        user=request.user,
        organization_id=org.id,
        office_id=office_id,
        ip=_client_ip(request),
    )
    return Status(204, None)


@router.get("/memberships", auth=jwt_auth, response=list[MembershipOut])
def list_memberships(request: HttpRequest):
    rows = (
        Membership.objects.select_related(
            "user",
            "office",
            "office__organization",
            "office__municipality",
        )
        .filter(user=request.user)
        .order_by("-is_active", "office__name")
    )
    return [_membership_out(m) for m in rows]


@router.get("/devices", auth=jwt_auth, response=list[DeviceOut])
def list_devices(request: HttpRequest):
    rows = (
        Device.objects.select_related("office")
        .filter(user=request.user)
        .order_by("-is_active", "-last_seen_at", "-id")
    )
    return [_device_out(d) for d in rows]


@router.post("/devices/{device_id}/revoke", auth=jwt_auth, response=DeviceOut)
def revoke_device_endpoint(request: HttpRequest, device_id: int):
    try:
        device = revoke_device(user=request.user, device_id=device_id)
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc
    log_audit(
        action="tenants.device_revoke",
        resource_type="device",
        resource_id=device.id,
        user=request.user,
        organization_id=device.office.organization_id,
        office_id=device.office_id,
        ip=_client_ip(request),
    )
    return _device_out(device)


@router.post(
    "/memberships/switch",
    auth=jwt_auth,
    response={200: TokenOut, 403: dict},
)
def switch_membership(
    request: HttpRequest, payload: SwitchMembershipIn, response: HttpResponse
):
    try:
        membership = switch_active_membership(
            user=request.user, membership_id=payload.membership_id
        )
    except TenantServiceError as exc:
        raise _map_service_error(exc) from exc

    office = membership.office
    try:
        device = activate_device_in_municipality(
            user=request.user,
            office=office,
            device_fingerprint=payload.device_fingerprint,
            lat=payload.lat,
            lng=payload.lng,
        )
    except TerritorialLockError as exc:
        raise HttpError(403, str(exc)) from exc

    access = issue_access_token(
        user_id=request.user.id,
        tenant_id=office.organization_id,
        office_id=office.id,
        role=membership.role,
        device_id=device.id,
    )
    refresh, _session = issue_refresh_token(
        user_id=request.user.id,
        office_id=office.id,
        device_id=device.id,
    )
    _set_refresh_cookie(response, refresh)

    log_audit(
        action="tenants.membership_switch",
        resource_type="membership",
        resource_id=membership.id,
        user=request.user,
        organization_id=office.organization_id,
        office_id=office.id,
        ip=_client_ip(request),
    )
    return TokenOut(
        access_token=access,
        tenant_id=office.organization_id,
        office_id=office.id,
        role=membership.role,
        device_id=device.id,
        needs_office=False,
    )

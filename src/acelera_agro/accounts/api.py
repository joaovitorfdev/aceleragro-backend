"""Auth endpoints: login, refresh, logout."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.http import HttpRequest, HttpResponse
from ninja import Router
from ninja.errors import HttpError

from acelera_agro.accounts.auth import jwt_auth
from acelera_agro.accounts.jwt_utils import (
    decode_token,
    get_valid_refresh_session,
    issue_access_token,
    issue_refresh_token,
    revoke_refresh_jti,
)
from acelera_agro.accounts.schemas import (
    AccountMeOut,
    LoginIn,
    MessageOut,
    TokenOut,
    UpdateProfileIn,
)
from acelera_agro.tenants.models import LoginEvent, Membership, get_active_membership
from acelera_agro.tenants.services import (
    activate_first_inactive_membership,
    get_owned_organization,
)
from acelera_agro.tenants.territorial import TerritorialLockError, activate_device_in_municipality

User = get_user_model()
router = Router(tags=["auth"])


def _client_ip(request: HttpRequest) -> str | None:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _set_refresh_cookie(response: HttpResponse, token: str) -> None:
    response.set_cookie(
        key=settings.JWT_REFRESH_COOKIE_NAME,
        value=token,
        max_age=int(settings.JWT_REFRESH_TTL.total_seconds()),
        path=settings.JWT_REFRESH_COOKIE_PATH,
        httponly=settings.JWT_REFRESH_COOKIE_HTTPONLY,
        secure=settings.JWT_REFRESH_COOKIE_SECURE,
        samesite=settings.JWT_REFRESH_COOKIE_SAMESITE,
    )


def _clear_refresh_cookie(response: HttpResponse) -> None:
    response.delete_cookie(
        key=settings.JWT_REFRESH_COOKIE_NAME,
        path=settings.JWT_REFRESH_COOKIE_PATH,
    )


@router.post("/auth/login", response={200: TokenOut, 401: MessageOut, 403: MessageOut})
def login(request: HttpRequest, payload: LoginIn, response: HttpResponse):
    user = authenticate(
        request,
        username=payload.email,
        password=payload.password,
    )
    if user is None:
        candidate = User.objects.filter(email__iexact=payload.email).first()
        if candidate is not None:
            user = authenticate(
                request,
                username=candidate.get_username(),
                password=payload.password,
            )
    if user is None:
        LoginEvent.objects.create(
            user=None,
            success=False,
            reason="invalid_credentials",
            lat=payload.lat,
            lng=payload.lng,
            ip=_client_ip(request),
        )
        raise HttpError(401, "Invalid credentials")

    membership = get_active_membership(user)
    if membership is None:
        membership = activate_first_inactive_membership(user=user)

    if membership is None:
        org = get_owned_organization(user)
        if org is None:
            LoginEvent.objects.create(
                user=user,
                success=False,
                reason="no_active_membership",
                lat=payload.lat,
                lng=payload.lng,
                ip=_client_ip(request),
            )
            raise HttpError(403, "No active membership")

        # Owner before first office: no geofence yet.
        access = issue_access_token(
            user_id=user.id,
            tenant_id=org.id,
            office_id=None,
            role=Membership.Role.OWNER,
            device_id=None,
        )
        refresh, _session = issue_refresh_token(
            user_id=user.id,
            office_id=None,
            device_id=None,
        )
        LoginEvent.objects.create(
            user=user,
            success=True,
            reason="ok_needs_office",
            lat=payload.lat,
            lng=payload.lng,
            ip=_client_ip(request),
        )
        _set_refresh_cookie(response, refresh)
        return TokenOut(
            access_token=access,
            tenant_id=org.id,
            office_id=None,
            role=Membership.Role.OWNER,
            device_id=None,
            needs_office=True,
        )

    office = membership.office
    try:
        device = activate_device_in_municipality(
            user=user,
            office=office,
            device_fingerprint=payload.device_fingerprint,
            lat=payload.lat,
            lng=payload.lng,
        )
    except TerritorialLockError as exc:
        LoginEvent.objects.create(
            user=user,
            office=office,
            success=False,
            reason=exc.code,
            lat=payload.lat,
            lng=payload.lng,
            ip=_client_ip(request),
        )
        raise HttpError(403, str(exc)) from exc

    access = issue_access_token(
        user_id=user.id,
        tenant_id=office.organization_id,
        office_id=office.id,
        role=membership.role,
        device_id=device.id,
    )
    refresh, _session = issue_refresh_token(
        user_id=user.id,
        office_id=office.id,
        device_id=device.id,
    )

    LoginEvent.objects.create(
        user=user,
        office=office,
        device=device,
        success=True,
        reason="ok",
        lat=payload.lat,
        lng=payload.lng,
        ip=_client_ip(request),
    )

    _set_refresh_cookie(response, refresh)
    return TokenOut(
        access_token=access,
        tenant_id=office.organization_id,
        office_id=office.id,
        role=membership.role,
        device_id=device.id,
        needs_office=False,
    )


@router.post("/auth/refresh", response={200: TokenOut, 401: MessageOut})
def refresh(request: HttpRequest, response: HttpResponse):
    raw = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
    if not raw:
        raise HttpError(401, "Missing refresh token")

    try:
        payload = decode_token(raw, expected_type="refresh")
    except Exception as exc:
        raise HttpError(401, "Invalid refresh token") from exc

    jti = payload.get("jti")
    session = get_valid_refresh_session(jti) if jti else None
    if session is None:
        raise HttpError(401, "Refresh session revoked or expired")

    user = User.objects.filter(pk=int(payload["sub"]), is_active=True).first()
    if user is None:
        raise HttpError(401, "User inactive")

    membership = get_active_membership(user)
    device_id = session.device_id

    if membership is None:
        org = get_owned_organization(user)
        if org is None or session.office_id is not None:
            raise HttpError(401, "Membership mismatch")
        revoke_refresh_jti(jti)
        access = issue_access_token(
            user_id=user.id,
            tenant_id=org.id,
            office_id=None,
            role=Membership.Role.OWNER,
            device_id=None,
        )
        new_refresh, _session = issue_refresh_token(
            user_id=user.id,
            office_id=None,
            device_id=None,
        )
        _set_refresh_cookie(response, new_refresh)
        return TokenOut(
            access_token=access,
            tenant_id=org.id,
            office_id=None,
            role=Membership.Role.OWNER,
            device_id=None,
            needs_office=True,
        )

    if membership.office_id != session.office_id:
        raise HttpError(401, "Membership mismatch")

    office = membership.office
    revoke_refresh_jti(jti)
    access = issue_access_token(
        user_id=user.id,
        tenant_id=office.organization_id,
        office_id=office.id,
        role=membership.role,
        device_id=device_id,
    )
    new_refresh, _session = issue_refresh_token(
        user_id=user.id,
        office_id=office.id,
        device_id=device_id,
    )

    _set_refresh_cookie(response, new_refresh)
    return TokenOut(
        access_token=access,
        tenant_id=office.organization_id,
        office_id=office.id,
        role=membership.role,
        device_id=device_id,
        needs_office=False,
    )


@router.post("/auth/logout", auth=jwt_auth, response={200: MessageOut})
def logout(request: HttpRequest, response: HttpResponse):
    raw = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
    if raw:
        try:
            payload = decode_token(raw, expected_type="refresh")
            jti = payload.get("jti")
            if jti:
                revoke_refresh_jti(jti)
        except Exception:
            pass

    _clear_refresh_cookie(response)
    return MessageOut(detail="Logged out")


def _full_name(user) -> str:
    return f"{user.first_name} {user.last_name}".strip()


@router.get("/auth/me", auth=jwt_auth, response=AccountMeOut)
def me(request: HttpRequest):
    ctx = request.auth
    user = request.user
    return AccountMeOut(
        user_id=user.id,
        email=user.email or user.get_username(),
        full_name=_full_name(user),
        tenant_id=ctx.tenant_id,
        office_id=ctx.office_id,
        role=ctx.role,
        device_id=ctx.device_id,
        needs_office=bool(getattr(ctx, "needs_office", False)),
    )


@router.patch("/auth/me", auth=jwt_auth, response=AccountMeOut)
def update_profile(request: HttpRequest, payload: UpdateProfileIn):
    user = request.user
    parts = (payload.full_name or "").strip().split(" ", 1)
    user.first_name = (parts[0] if parts else "")[:150]
    user.last_name = (parts[1] if len(parts) > 1 else "")[:150]
    user.save(update_fields=["first_name", "last_name"])
    ctx = request.auth
    return AccountMeOut(
        user_id=user.id,
        email=user.email or user.get_username(),
        full_name=_full_name(user),
        tenant_id=ctx.tenant_id,
        office_id=ctx.office_id,
        role=ctx.role,
        device_id=ctx.device_id,
        needs_office=bool(getattr(ctx, "needs_office", False)),
    )

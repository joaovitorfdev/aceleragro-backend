"""JWT issue / verify helpers (access + refresh with rotation)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import jwt
from django.conf import settings
from django.utils import timezone

from acelera_agro.accounts.models import RefreshSession


def _now() -> datetime:
    return timezone.now()


def issue_access_token(
    *,
    user_id: int,
    tenant_id: int,
    office_id: int | None,
    role: str,
    device_id: int | None,
) -> str:
    now = _now()
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "office_id": office_id,
        "role": role,
        "device_id": device_id,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + settings.JWT_ACCESS_TTL).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def issue_refresh_token(
    *,
    user_id: int,
    office_id: int | None,
    device_id: int | None,
) -> tuple[str, RefreshSession]:
    """Issue a refresh JWT and persist a single session (revoking previous)."""
    now = _now()
    jti = uuid.uuid4().hex
    expires_at = now + settings.JWT_REFRESH_TTL
    payload = {
        "sub": str(user_id),
        "office_id": office_id,
        "device_id": device_id,
        "jti": jti,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

    RefreshSession.objects.filter(user_id=user_id, revoked_at__isnull=True).update(
        revoked_at=now
    )
    session = RefreshSession.objects.create(
        user_id=user_id,
        jti=jti,
        device_id=device_id,
        office_id=office_id,
        expires_at=expires_at,
    )
    return token, session


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"Expected token type {expected_type}")
    return payload


def revoke_refresh_jti(jti: str) -> None:
    RefreshSession.objects.filter(jti=jti, revoked_at__isnull=True).update(
        revoked_at=_now()
    )


def get_valid_refresh_session(jti: str) -> RefreshSession | None:
    session = RefreshSession.objects.filter(jti=jti).first()
    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at < _now():
        return None
    return session


def utc_timestamp(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())

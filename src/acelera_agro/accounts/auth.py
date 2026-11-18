"""Ninja authentication that populates tenant context from JWT."""

from __future__ import annotations

from dataclasses import dataclass

import jwt
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from ninja.security import HttpBearer

from acelera_agro.accounts.jwt_utils import decode_token
from acelera_agro.tenants import context as tenant_context
from acelera_agro.tenants.models import Membership, Office, Organization, get_active_membership

User = get_user_model()


@dataclass
class AuthContext:
    user: object
    tenant_id: int
    office_id: int | None
    role: str
    device_id: int | None
    read_only: bool
    needs_office: bool = False


class JWTAuth(HttpBearer):
    def authenticate(self, request: HttpRequest, token: str) -> AuthContext | None:
        try:
            payload = decode_token(token, expected_type="access")
        except jwt.PyJWTError:
            return None

        user_id = int(payload["sub"])
        user = User.objects.filter(pk=user_id, is_active=True).first()
        if user is None:
            return None

        tenant_id = int(payload["tenant_id"])
        raw_office = payload.get("office_id")
        office_id = int(raw_office) if raw_office not in (None, "", 0, "0") else None
        role = payload.get("role") or Membership.Role.OWNER
        device_id = payload.get("device_id")

        if office_id is None:
            org = Organization.objects.filter(pk=tenant_id, owner=user, is_active=True).first()
            if org is None:
                return None
            tenant_context.set_tenant_context(
                organization_id=org.id,
                office_id=None,
                membership=None,
                role=Membership.Role.OWNER,
                device_id=None,
                read_only=True,
            )
            ctx = AuthContext(
                user=user,
                tenant_id=org.id,
                office_id=None,
                role=Membership.Role.OWNER,
                device_id=None,
                read_only=True,
                needs_office=True,
            )
            request.auth_context = ctx
            request.user = user
            return ctx

        office = Office.objects.select_related("organization").filter(pk=office_id).first()
        if office is None or office.organization_id != tenant_id:
            return None

        membership = get_active_membership(user)
        if membership is None or membership.office_id != office_id:
            return None

        role = payload.get("role") or membership.role
        read_only = office.is_read_only

        tenant_context.set_tenant_context(
            organization_id=office.organization_id,
            office_id=office.id,
            membership=membership,
            role=role,
            device_id=device_id,
            read_only=read_only,
        )
        ctx = AuthContext(
            user=user,
            tenant_id=office.organization_id,
            office_id=office.id,
            role=role,
            device_id=device_id,
            read_only=read_only,
            needs_office=False,
        )
        request.auth_context = ctx
        request.user = user
        return ctx


jwt_auth = JWTAuth()

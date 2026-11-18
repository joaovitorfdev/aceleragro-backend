"""Helpers to persist audit events."""

from __future__ import annotations

from typing import Any

from acelera_agro.audit.models import AuditLog
from acelera_agro.tenants import context as tenant_context


def log_audit(
    *,
    action: str,
    resource_type: str = "",
    resource_id: str | int = "",
    detail: dict[str, Any] | None = None,
    user=None,
    organization_id: int | None = None,
    office_id: int | None = None,
    ip: str | None = None,
) -> AuditLog:
    return AuditLog.objects.create(
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id != "" else "",
        detail=detail or {},
        user=user,
        organization_id=organization_id
        if organization_id is not None
        else tenant_context.get_organization_id(),
        office_id=office_id if office_id is not None else tenant_context.get_office_id(),
        ip=ip,
    )

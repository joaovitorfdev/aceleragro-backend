"""Request-scoped tenant context via contextvars."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from acelera_agro.tenants.models import Membership, Office, Organization

_organization_id: ContextVar[int | None] = ContextVar("organization_id", default=None)
_office_id: ContextVar[int | None] = ContextVar("office_id", default=None)
_membership: ContextVar[Membership | None] = ContextVar("membership", default=None)
_role: ContextVar[str | None] = ContextVar("role", default=None)
_device_id: ContextVar[int | None] = ContextVar("device_id", default=None)
_read_only: ContextVar[bool] = ContextVar("read_only", default=False)


def set_tenant_context(
    *,
    organization_id: int | None = None,
    office_id: int | None = None,
    membership: Membership | None = None,
    role: str | None = None,
    device_id: int | None = None,
    read_only: bool = False,
) -> None:
    _organization_id.set(organization_id)
    _office_id.set(office_id)
    _membership.set(membership)
    _role.set(role)
    _device_id.set(device_id)
    _read_only.set(read_only)


def clear_tenant_context() -> None:
    set_tenant_context()


def get_organization_id() -> int | None:
    return _organization_id.get()


def get_office_id() -> int | None:
    return _office_id.get()


def get_membership() -> Membership | None:
    return _membership.get()


def get_role() -> str | None:
    return _role.get()


def get_device_id() -> int | None:
    return _device_id.get()


def is_read_only() -> bool:
    return _read_only.get()


def get_office() -> Office | None:
    office_id = get_office_id()
    if office_id is None:
        return None
    from acelera_agro.tenants.models import Office

    return Office.objects.filter(pk=office_id).first()


def get_organization() -> Organization | None:
    org_id = get_organization_id()
    if org_id is None:
        return None
    from acelera_agro.tenants.models import Organization

    return Organization.objects.filter(pk=org_id).first()

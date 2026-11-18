"""RBAC helpers for Ninja endpoints."""

from __future__ import annotations

from ninja.errors import HttpError

from acelera_agro.tenants import context as tenant_context
from acelera_agro.tenants.models import Membership

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def assert_role(*roles: str) -> None:
    """Ensure the active membership role is allowed."""
    role = tenant_context.get_role()
    if role is None:
        raise HttpError(401, "Authentication required")
    if roles and role not in roles:
        raise HttpError(403, "Insufficient role")


def assert_can_mutate(request=None) -> None:
    if tenant_context.is_read_only():
        raise HttpError(403, "Office is suspended (read-only)")
    if request is not None and request.method not in MUTATING_METHODS:
        return


def assert_role_and_mutate(request, *roles: str) -> None:
    assert_role(*roles)
    if request.method in MUTATING_METHODS:
        assert_can_mutate(request)


def role_at_least(role: str, minimum: str) -> bool:
    order = [
        Membership.Role.VIEWER,
        Membership.Role.TECHNICIAN,
        Membership.Role.ADMIN,
        Membership.Role.OWNER,
    ]
    try:
        return order.index(role) >= order.index(minimum)
    except ValueError:
        return False


# Back-compat alias used during migration of call sites
def require_role(*roles: str):
    """Deprecated decorator stub — prefer assert_role_and_mutate in views."""

    def decorator(func):
        return func

    return decorator

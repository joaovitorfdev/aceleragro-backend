"""Managers that filter by office/organization from contextvars."""

from __future__ import annotations

from django.db import models

from acelera_agro.tenants import context as tenant_context


class OrganizationScopedQuerySet(models.QuerySet):
    def for_current_organization(self) -> OrganizationScopedQuerySet:
        org_id = tenant_context.get_organization_id()
        if org_id is None:
            return self.none()
        return self.filter(organization_id=org_id)


class OrganizationScopedManager(models.Manager.from_queryset(OrganizationScopedQuerySet)):
    def get_queryset(self) -> OrganizationScopedQuerySet:
        qs = super().get_queryset()
        org_id = tenant_context.get_organization_id()
        if org_id is not None:
            return qs.filter(organization_id=org_id)
        return qs


class OfficeScopedQuerySet(models.QuerySet):
    def for_current_office(self) -> OfficeScopedQuerySet:
        office_id = tenant_context.get_office_id()
        if office_id is None:
            return self.none()
        return self.filter(office_id=office_id)


class OfficeScopedManager(models.Manager.from_queryset(OfficeScopedQuerySet)):
    def get_queryset(self) -> OfficeScopedQuerySet:
        qs = super().get_queryset()
        office_id = tenant_context.get_office_id()
        if office_id is not None:
            return qs.filter(office_id=office_id)
        return qs


class UnscopedManager(models.Manager):
    """Bypass tenant filters for admin / system tasks."""

    pass

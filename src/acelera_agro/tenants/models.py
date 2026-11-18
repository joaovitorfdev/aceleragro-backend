"""Tenant domain models: Organization, Municipality, Office, Membership, Device."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

from acelera_agro.tenants.managers import (
    OfficeScopedManager,
    OrganizationScopedManager,
    UnscopedManager,
)


class Organization(models.Model):
    name = models.CharField(max_length=255)
    trade_name = models.CharField(max_length=255, blank=True, default="")
    cnpj = models.CharField(max_length=18, blank=True, default="")
    logo_key = models.CharField(max_length=512, blank=True, default="")
    banner_key = models.CharField(max_length=512, blank=True, default="")
    # Set at signup; office memberships may come later (Marco T3).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owned_organizations",
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["cnpj"],
                condition=~Q(cnpj="") & Q(cnpj__isnull=False),
                name="uniq_organization_cnpj_when_set",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Municipality(models.Model):
    ibge_code = models.CharField(max_length=7, unique=True)
    name = models.CharField(max_length=255)
    state_uf = models.CharField(max_length=2)
    fiscal_module_ha = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal("0")
    )
    # GeoJSON polygon or Feature for shapely territorial checks
    boundary = models.TextField(blank=True, default="")

    class Meta:
        verbose_name_plural = "municipalities"
        ordering = ["state_uf", "name"]

    def __str__(self) -> str:
        return f"{self.name}/{self.state_uf}"


class Office(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        INACTIVE = "inactive", "Inactive"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="offices"
    )
    municipality = models.ForeignKey(
        Municipality, on_delete=models.PROTECT, related_name="offices"
    )
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=512, blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.ACTIVE
    )
    monthly_price = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("150.00")
    )
    referral_code = models.CharField(max_length=64, unique=True, null=True, blank=True)
    technical_responsible_name = models.CharField(max_length=255, blank=True, default="")
    technical_council_id = models.CharField(max_length=64, blank=True, default="")
    bank_credential_ref = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "municipality"],
                name="uniq_office_org_municipality",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization})"

    @property
    def is_read_only(self) -> bool:
        return self.status != self.Status.ACTIVE


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        TECHNICIAN = "technician", "Technician"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "office"], name="uniq_membership_user_office"
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(is_active=True),
                name="uniq_active_membership_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}@{self.office_id}:{self.role}"


def get_active_membership(user) -> Membership | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return (
        Membership.objects.select_related("office", "office__organization", "office__municipality")
        .filter(user=user, is_active=True)
        .first()
    )


class Device(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name="devices")
    device_fingerprint = models.CharField(max_length=255)
    activated_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    last_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    needs_revalidation = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["office", "device_fingerprint"],
                name="uniq_device_fingerprint_per_office",
            )
        ]

    def __str__(self) -> str:
        return f"{self.device_fingerprint[:12]}…"


class LoginEvent(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="login_events",
    )
    office = models.ForeignKey(
        Office, on_delete=models.SET_NULL, null=True, blank=True, related_name="login_events"
    )
    device = models.ForeignKey(
        Device, on_delete=models.SET_NULL, null=True, blank=True, related_name="login_events"
    )
    success = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True, default="")
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class TenantOwnedModel(models.Model):
    """Abstract base with organization FK."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="%(class)ss"
    )

    objects = OrganizationScopedManager()
    all_objects = UnscopedManager()

    class Meta:
        abstract = True


class OfficeScopedModel(models.Model):
    """Abstract base with office FK."""

    office = models.ForeignKey(Office, on_delete=models.CASCADE, related_name="%(class)ss")

    objects = OfficeScopedManager()
    all_objects = UnscopedManager()

    class Meta:
        abstract = True

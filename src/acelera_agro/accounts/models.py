"""Auth-related persistence: refresh sessions and idempotency keys."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class RefreshSession(models.Model):
    """Single active refresh token session per user (rotation invalidates previous)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refresh_sessions",
    )
    jti = models.CharField(max_length=64, unique=True)
    device = models.ForeignKey(
        "tenants.Device",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refresh_sessions",
    )
    office = models.ForeignKey(
        "tenants.Office",
        on_delete=models.CASCADE,
        related_name="refresh_sessions",
        null=True,
        blank=True,
    )
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "revoked_at"])]


class IdempotencyRecord(models.Model):
    key = models.CharField(max_length=255)
    office_id = models.IntegerField(null=True, blank=True)
    user_id = models.IntegerField(null=True, blank=True)
    method = models.CharField(max_length=16)
    path = models.CharField(max_length=512)
    request_hash = models.CharField(max_length=64)
    response_status = models.IntegerField()
    response_body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["key", "office_id", "path", "method"],
                name="uniq_idempotency_key_scope",
            )
        ]

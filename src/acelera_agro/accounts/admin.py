from django.contrib import admin

from acelera_agro.accounts.models import IdempotencyRecord, RefreshSession


@admin.register(RefreshSession)
class RefreshSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "office", "jti", "expires_at", "revoked_at", "created_at")
    list_filter = ("revoked_at",)
    search_fields = ("jti", "user__username", "user__email")


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    list_display = ("key", "method", "path", "response_status", "office_id", "created_at")
    search_fields = ("key", "path")

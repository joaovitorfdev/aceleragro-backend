from django.contrib import admin

from acelera_agro.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "resource_type",
        "resource_id",
        "user",
        "office_id",
        "organization_id",
    )
    list_filter = ("action", "resource_type")
    search_fields = ("resource_id", "action")
    readonly_fields = ("created_at",)

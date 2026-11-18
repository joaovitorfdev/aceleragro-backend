from django.contrib import admin

from acelera_agro.tenants.models import (
    Device,
    LoginEvent,
    Membership,
    Municipality,
    Office,
    Organization,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "trade_name", "cnpj", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "trade_name", "cnpj")


@admin.register(Municipality)
class MunicipalityAdmin(admin.ModelAdmin):
    list_display = ("ibge_code", "name", "state_uf", "fiscal_module_ha")
    search_fields = ("ibge_code", "name", "state_uf")
    list_filter = ("state_uf",)


@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "organization",
        "municipality",
        "status",
        "referral_code",
        "monthly_price",
    )
    list_filter = ("status", "organization")
    search_fields = ("name", "referral_code")
    actions = ["activate_offices", "suspend_offices"]

    @admin.action(description="Activate selected offices")
    def activate_offices(self, request, queryset):
        queryset.update(status=Office.Status.ACTIVE)

    @admin.action(description="Suspend selected offices")
    def suspend_offices(self, request, queryset):
        queryset.update(status=Office.Status.SUSPENDED)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "office", "role", "is_active", "office_referral_code")
    list_filter = ("role", "is_active")
    search_fields = ("user__username", "user__email", "office__name", "office__referral_code")
    raw_id_fields = ("user", "office")

    @admin.display(description="Referral code")
    def office_referral_code(self, obj: Membership) -> str:
        return obj.office.referral_code or ""


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "device_fingerprint",
        "user",
        "office",
        "is_active",
        "activated_at",
        "last_seen_at",
    )
    list_filter = ("is_active",)


@admin.register(LoginEvent)
class LoginEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "office", "success", "reason", "ip")
    list_filter = ("success",)
    readonly_fields = ("created_at",)

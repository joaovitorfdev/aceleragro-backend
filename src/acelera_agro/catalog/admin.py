from django.contrib import admin

from acelera_agro.catalog.models import BankBranch, BankProfile, CreditLine, CropYear, RuleSet


@admin.register(CropYear)
class CropYearAdmin(admin.ModelAdmin):
    list_display = ("code", "label", "starts_on", "ends_on", "is_active")
    list_filter = ("is_active",)


@admin.register(RuleSet)
class RuleSetAdmin(admin.ModelAdmin):
    list_display = ("code", "version", "name", "is_active", "created_at")
    list_filter = ("is_active", "code")


@admin.register(BankProfile)
class BankProfileAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    list_filter = ("is_active",)


@admin.register(BankBranch)
class BankBranchAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "bank_profile", "is_active")
    list_filter = ("bank_profile", "is_active")


@admin.register(CreditLine)
class CreditLineAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "bank_profile",
        "annual_rate",
        "term_years",
        "is_active",
    )
    list_filter = ("bank_profile", "is_active")

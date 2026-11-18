from django.contrib import admin

from acelera_agro.proposals.models import (
    ActivityProjection,
    BudgetItem,
    ExistingDebt,
    Issue,
    Property,
    Proponent,
    Proposal,
    TechnicalOpinion,
)


@admin.register(Proponent)
class ProponentAdmin(admin.ModelAdmin):
    list_display = ("full_name", "organization", "person_type", "marital_status")
    search_fields = ("full_name", "document_number")


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("name", "proponent", "ownership_type", "area_ha", "municipality")
    list_filter = ("ownership_type",)


class BudgetItemInline(admin.TabularInline):
    model = BudgetItem
    extra = 0


class ExistingDebtInline(admin.TabularInline):
    model = ExistingDebt
    extra = 0


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "office",
        "proponent",
        "status",
        "financed_amount",
        "technician_reviewed_at",
    )
    list_filter = ("status", "bank_profile")
    inlines = [BudgetItemInline, ExistingDebtInline]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = ("proposal", "code", "severity", "resolved_at", "created_at")
    list_filter = ("severity",)


@admin.register(ActivityProjection)
class ActivityProjectionAdmin(admin.ModelAdmin):
    list_display = ("proposal", "activity_kind", "year", "revenue", "expense")


@admin.register(TechnicalOpinion)
class TechnicalOpinionAdmin(admin.ModelAdmin):
    list_display = ("proposal", "recommendation", "authored_by", "updated_at")

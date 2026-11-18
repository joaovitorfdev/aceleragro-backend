"""Proposal domain: Proponent, Property, Proposal and related rows."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings
from django.db import models

from acelera_agro.tenants.models import OfficeScopedModel, TenantOwnedModel


class Proponent(TenantOwnedModel):
    class MaritalStatus(models.TextChoices):
        SINGLE = "single", "Single"
        MARRIED = "married", "Married"
        STABLE_UNION = "stable_union", "Stable union"
        DIVORCED = "divorced", "Divorced"
        WIDOWED = "widowed", "Widowed"
        OTHER = "other", "Other"

    class PersonType(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        COMPANY = "company", "Company"

    full_name = models.CharField(max_length=255)
    trade_name = models.CharField(max_length=255, blank=True, default="")
    document_number = models.CharField(max_length=18, blank=True, default="")
    person_type = models.CharField(
        max_length=16, choices=PersonType.choices, default=PersonType.INDIVIDUAL
    )
    # Blank until informed (form drafts start empty); the schema requires it for individuals.
    marital_status = models.CharField(
        max_length=16, choices=MaritalStatus.choices, blank=True, default=""
    )
    spouse_name = models.CharField(max_length=255, blank=True, default="")
    spouse_document_number = models.CharField(max_length=18, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    address = models.CharField(max_length=512, blank=True, default="")
    field_provenance = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self) -> str:
        return self.full_name


class Property(TenantOwnedModel):
    class OwnershipType(models.TextChoices):
        REGISTERED_DEED = "registered_deed", "Registered deed"
        PURCHASE_SALE_CONTRACT = "purchase_sale_contract", "Purchase/sale contract"
        POSSESSION_INCRA = "possession_incra", "Possession (INCRA)"
        LEASE = "lease", "Lease"
        PARTNERSHIP = "partnership", "Partnership"
        OTHER = "other", "Other"

    # Nullable so up to 5 properties can belong to a draft before a proponent exists.
    proponent = models.ForeignKey(
        Proponent,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="properties",
    )
    proposal = models.ForeignKey(
        "proposals.Proposal",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="properties",
    )
    municipality = models.ForeignKey(
        "tenants.Municipality",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="properties",
    )
    name = models.CharField(max_length=255, blank=True, default="")
    ownership_type = models.CharField(
        max_length=32,
        choices=OwnershipType.choices,
        blank=True,
        default="",
    )
    lease_owner_name = models.CharField(max_length=255, blank=True, default="")
    car_code = models.CharField(max_length=64, blank=True, default="")
    area_ha = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))
    nirf = models.CharField(max_length=64, blank=True, default="")
    matricula = models.CharField(max_length=64, blank=True, default="")
    field_provenance = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "properties"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name or f"Property {self.pk}"


class Proposal(OfficeScopedModel):
    class CreditPurpose(models.TextChoices):
        INVESTMENT = "investment", "Investment"
        WORKING_CAPITAL = "working_capital", "Working capital"

    class ActivityKind(models.TextChoices):
        AGRICULTURE = "agriculture", "Agriculture"
        BEEF_CATTLE = "beef_cattle", "Beef cattle"
        DAIRY_CATTLE = "dairy_cattle", "Dairy cattle"
        OTHER = "other", "Other"

    class GuaranteeType(models.TextChoices):
        PROPERTY = "property", "Property"
        LIVESTOCK = "livestock", "Livestock"
        PERSONAL = "personal", "Personal"
        NONE = "none", "None"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_REVIEW = "in_review", "In review"
        PENDING_DOCS = "pending_docs", "Pending documents"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    organization = models.ForeignKey(
        "tenants.Organization", on_delete=models.CASCADE, related_name="proposals"
    )
    # Nullable: a draft can exist empty and gain a proponent when the first value arrives.
    proponent = models.ForeignKey(
        Proponent,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="proposals",
    )
    property = models.ForeignKey(
        Property,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
    )
    crop_year = models.ForeignKey(
        "catalog.CropYear",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
    )
    ruleset = models.ForeignKey(
        "catalog.RuleSet",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
    )
    bank_profile = models.ForeignKey(
        "catalog.BankProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
    )
    credit_line = models.ForeignKey(
        "catalog.CreditLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
    )
    bank_branch = models.ForeignKey(
        "catalog.BankBranch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="proposals",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_proposals",
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    referral_code = models.CharField(max_length=64, blank=True, default="")
    credit_purpose = models.CharField(
        max_length=16, choices=CreditPurpose.choices, blank=True, default=""
    )
    activity_kind = models.CharField(
        max_length=16, choices=ActivityKind.choices, blank=True, default=""
    )
    guarantee_type = models.CharField(
        max_length=16, choices=GuaranteeType.choices, blank=True, default=""
    )
    financed_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    annual_rate = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    term_years = models.PositiveSmallIntegerField(null=True, blank=True)
    grace_years = models.PositiveSmallIntegerField(null=True, blank=True)
    charge_interest_during_grace = models.BooleanField(default=False)
    family_maintenance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    total_rba = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    agro_revenue_share = models.DecimalField(
        max_digits=6, decimal_places=4, default=Decimal("1.0000")
    )
    schedule_json = models.JSONField(default=list, blank=True)
    capacity_json = models.JSONField(default=list, blank=True)
    classification_json = models.JSONField(default=dict, blank=True)
    # Form contract state (docs/form-contract.md): path -> {...}.
    form_provenance = models.JSONField(default=dict, blank=True)
    form_suggestions = models.JSONField(default=dict, blank=True)
    # Form values without a dedicated column, e.g. {"review": {"technician_declaration": true}}.
    form_extra = models.JSONField(default=dict, blank=True)
    technician_reviewed_at = models.DateTimeField(null=True, blank=True)
    calculated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Proposal {self.pk}"


class BudgetItem(models.Model):
    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name="budget_items"
    )
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("1"))
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]


class ExistingDebt(models.Model):
    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name="existing_debts"
    )
    creditor = models.CharField(max_length=255, blank=True, default="")
    # Zero defaults let a debt row exist while the form is still being filled;
    # zero is treated as "empty" unless the user locked it.
    outstanding_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    annual_rate = models.DecimalField(
        max_digits=10, decimal_places=6, default=Decimal("0")
    )
    remaining_term_years = models.PositiveSmallIntegerField(default=0)
    grace_years = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["id"]


class ActivityProjection(models.Model):
    class ActivityKind(models.TextChoices):
        AGRICULTURE = "agriculture", "Agriculture"
        BEEF_CATTLE = "beef_cattle", "Beef cattle"
        DAIRY_CATTLE = "dairy_cattle", "Dairy cattle"
        OTHER = "other", "Other"

    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name="activity_projections"
    )
    activity_kind = models.CharField(
        max_length=32, choices=ActivityKind.choices, default=ActivityKind.AGRICULTURE
    )
    year = models.PositiveSmallIntegerField()
    revenue = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    expense = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    detail = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["activity_kind", "year"]
        unique_together = [("proposal", "activity_kind", "year")]


class TechnicalOpinion(models.Model):
    proposal = models.OneToOneField(
        Proposal, on_delete=models.CASCADE, related_name="technical_opinion"
    )
    summary = models.TextField(blank=True, default="")
    recommendation = models.CharField(max_length=64, blank=True, default="")
    authored_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="technical_opinions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Issue(models.Model):
    class Severity(models.TextChoices):
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    proposal = models.ForeignKey(
        Proposal, on_delete=models.CASCADE, related_name="issues"
    )
    code = models.CharField(max_length=64)
    message = models.CharField(max_length=512)
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.WARNING
    )
    field_path = models.CharField(max_length=128, blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

"""Document assets linked to proposals (batch upload, classify later)."""

from __future__ import annotations

from django.conf import settings
from django.db import models

from acelera_agro.tenants.models import OfficeScopedModel


class DocumentKind(models.TextChoices):
    PUBLIC_DEED = "public_deed", "Public deed"
    PURCHASE_SALE_CONTRACT = "purchase_sale_contract", "Purchase/sale contract"
    LAND_REGISTRY = "land_registry", "Land registry"
    POSSESSION_TITLE = "possession_title", "Possession title"
    INCRA_CCIR = "incra_ccir", "INCRA CCIR"
    CAR = "car", "CAR"
    CAF = "caf", "CAF"
    ITR = "itr", "ITR"
    ID_DOCUMENT = "id_document", "ID document"
    CPF = "cpf", "CPF"
    MARRIAGE_CERTIFICATE = "marriage_certificate", "Marriage certificate"
    UNION_DECLARATION = "union_declaration", "Union declaration"
    PROOF_OF_RESIDENCE = "proof_of_residence", "Proof of residence"
    BUDGET_QUOTE = "budget_quote", "Budget quote"
    DEBT_STATEMENT = "debt_statement", "Debt statement"
    HERD_DECLARATION = "herd_declaration", "Herd declaration"
    GUARANTOR_ID = "guarantor_id", "Guarantor ID"
    OTHER = "other", "Other"
    UNKNOWN = "unknown", "Unknown"


class Document(OfficeScopedModel):
    class ExtractionStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        QUEUED = "queued", "Queued"
        READING = "reading", "Reading"
        CLASSIFIED = "classified", "Classified"
        EXTRACTED = "extracted", "Extracted"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    proposal = models.ForeignKey(
        "proposals.Proposal",
        on_delete=models.CASCADE,
        related_name="documents",
    )
    s3_key = models.CharField(max_length=512)
    content_type = models.CharField(max_length=128, blank=True, default="")
    size = models.PositiveIntegerField(default=0)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    detected_kind = models.CharField(
        max_length=32,
        choices=DocumentKind.choices,
        default=DocumentKind.UNKNOWN,
    )
    detected_kind_confidence = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    user_override_kind = models.CharField(
        max_length=32,
        choices=DocumentKind.choices,
        blank=True,
        default="",
    )
    classified_at = models.DateTimeField(null=True, blank=True)
    extraction_status = models.CharField(
        max_length=16,
        choices=ExtractionStatus.choices,
        default=ExtractionStatus.PENDING,
    )
    field_provenance = models.JSONField(default=dict, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.original_filename or self.s3_key} ({self.effective_kind})"

    @property
    def effective_kind(self) -> str:
        return self.user_override_kind or self.detected_kind

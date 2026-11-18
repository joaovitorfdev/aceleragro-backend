"""Catalog: crop years, rule sets, credit lines, bank branches and profiles."""

from __future__ import annotations

from decimal import Decimal

from django.db import models


class CropYear(models.Model):
    code = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=128)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-starts_on"]

    def __str__(self) -> str:
        return self.code


class RuleSet(models.Model):
    code = models.CharField(max_length=64)
    version = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("code", "version")]
        ordering = ["code", "-version"]

    def __str__(self) -> str:
        return f"{self.code}@{self.version}"


class BankProfile(models.Model):
    """Bank-side configuration. Codes: bb, caixa, basa, sicredi, sicoob."""

    class Code(models.TextChoices):
        BB = "bb", "Banco do Brasil"
        CAIXA = "caixa", "Caixa Econômica Federal"
        BASA = "basa", "BASA"
        SICREDI = "sicredi", "Sicredi"
        SICOOB = "sicoob", "Sicoob"

    code = models.CharField(max_length=32, unique=True, choices=Code.choices)
    name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    # Document checklist with optional conditional rules:
    # [{ "kind": "public_deed", "required": true,
    #    "when": {"ownership_type": ["registered_deed"], "marital_status": ["married"]} }]
    document_checklist = models.JSONField(default=list, blank=True)
    pdf_sections = models.JSONField(default=list, blank=True)
    extra_config = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code

    def required_document_kinds(
        self,
        *,
        ownership_type: str | None = None,
        marital_status: str | None = None,
    ) -> list[str]:
        """Resolve checklist kinds that apply under the given conditions."""
        kinds: list[str] = []
        for item in self.document_checklist or []:
            when = item.get("when") or {}
            ownership_ok = True
            marital_ok = True
            if "ownership_type" in when and ownership_type is not None:
                ownership_ok = ownership_type in when["ownership_type"]
            if "marital_status" in when and marital_status is not None:
                marital_ok = marital_status in when["marital_status"]
            # Items without when always apply; items with when apply when all keys match.
            if when:
                if ownership_ok and marital_ok and item.get("required", True):
                    kinds.append(item["kind"])
            elif item.get("required", True):
                kinds.append(item["kind"])
        return kinds


class BankBranch(models.Model):
    bank_profile = models.ForeignKey(
        BankProfile, on_delete=models.CASCADE, related_name="branches"
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    municipality = models.ForeignKey(
        "tenants.Municipality",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_branches",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("bank_profile", "code")]
        ordering = ["bank_profile", "code"]
        verbose_name_plural = "bank branches"

    def __str__(self) -> str:
        return f"{self.bank_profile.code}:{self.code}"


class CreditLine(models.Model):
    bank_profile = models.ForeignKey(
        BankProfile, on_delete=models.CASCADE, related_name="credit_lines"
    )
    crop_year = models.ForeignKey(
        CropYear,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_lines",
    )
    ruleset = models.ForeignKey(
        RuleSet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credit_lines",
    )
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    annual_rate = models.DecimalField(max_digits=10, decimal_places=6, default=Decimal("0"))
    term_years = models.PositiveSmallIntegerField(default=10)
    grace_years = models.PositiveSmallIntegerField(default=0)
    charge_interest_during_grace = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    extra_config = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = [("bank_profile", "code")]
        ordering = ["bank_profile", "code"]

    def __str__(self) -> str:
        return f"{self.bank_profile.code}:{self.code}"

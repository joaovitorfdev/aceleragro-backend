"""Seed crop years, rule sets, bank profiles and BB credit lines."""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from acelera_agro.catalog.bank_profiles import BANK_PROFILE_SEEDS, DEFAULT_CREDIT_LINES
from acelera_agro.catalog.models import BankProfile, CreditLine, CropYear, RuleSet


class Command(BaseCommand):
    help = "Seed catalog: crop years, rule sets, bank profiles, BB credit lines"

    def handle(self, *args, **options):
        crop_year, _ = CropYear.objects.update_or_create(
            code="2025_2026",
            defaults={
                "label": "Safra 2025/2026",
                "starts_on": date(2025, 7, 1),
                "ends_on": date(2026, 6, 30),
                "is_active": True,
            },
        )
        ruleset, _ = RuleSet.objects.update_or_create(
            code="pronaf_spreadsheet",
            version="1",
            defaults={
                "name": "Pronaf spreadsheet legacy classification",
                "is_active": True,
                "config": {"classification": "spreadsheet_legacy"},
            },
        )

        for seed in BANK_PROFILE_SEEDS:
            profile, _ = BankProfile.objects.update_or_create(
                code=seed["code"],
                defaults={
                    "name": seed["name"],
                    "is_active": seed["is_active"],
                    "document_checklist": seed["document_checklist"],
                    "pdf_sections": seed["pdf_sections"],
                    "extra_config": seed["extra_config"],
                },
            )
            if profile.code == BankProfile.Code.BB:
                for line in DEFAULT_CREDIT_LINES:
                    CreditLine.objects.update_or_create(
                        bank_profile=profile,
                        code=line["code"],
                        defaults={
                            "name": line["name"],
                            "crop_year": crop_year,
                            "ruleset": ruleset,
                            "annual_rate": line["annual_rate"],
                            "term_years": line["term_years"],
                            "grace_years": line["grace_years"],
                            "charge_interest_during_grace": line[
                                "charge_interest_during_grace"
                            ],
                            "is_active": True,
                            "extra_config": line.get("extra_config") or {},
                        },
                    )

        self.stdout.write(self.style.SUCCESS("Catalog seeded."))

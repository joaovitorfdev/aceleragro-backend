"""Extraction provider protocol + stub/hybrid implementations + factory.

Real OCR/vision providers plug in here without changing the form contract.
GTM minimum pack documents are listed for coverage tracking.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from django.conf import settings

from acelera_agro.documents.models import Document, DocumentKind
from acelera_agro.extraction.schemas import FILENAME_KIND_HINTS, KIND_SCHEMA_MAP

STUB_FULL_NAME = "Produtor Teste 01"
STUB_DOCUMENT_NUMBER = "000.000.000-00"  # fake / masked CPF
STUB_MUNICIPALITY_IBGE = "5208707"  # matches the synthetic test municipality

# Marco 8 BB GTM — minimum kinds the provider should cover for beef investment.
GTM_BB_BEEF_INVESTMENT_KINDS: frozenset[str] = frozenset(
    {
        "id_document",
        "cpf",
        "proof_of_residence",
        "caf",
        "car",
        "itr",
        "land_registry",
        "public_deed",
        "budget_quote",
        "debt_statement",
        "herd_declaration",
    }
)


class ExtractionProvider(Protocol):
    def classify(self, document: Document) -> tuple[str, Decimal]:
        """Return (detected_kind, confidence)."""
        ...

    def extract(self, document: Document) -> dict:
        """Return extracted fields; a value may be ``{"value": v, "confidence": "0.xx"}``."""
        ...


class StubExtractionProvider:
    """Deterministic stub: classify by filename tokens; extract synthetic fields."""

    def classify(self, document: Document) -> tuple[str, Decimal]:
        name = (document.original_filename or document.s3_key or "").lower()
        for token, kind in FILENAME_KIND_HINTS:
            if token in name:
                return kind, Decimal("0.9200")
        return DocumentKind.UNKNOWN, Decimal("0.1000")

    def extract(self, document: Document) -> dict:
        """Synthetic, LGPD-safe values (never real people).

        A filename containing ``lowconf`` makes every field come back with confidence
        ``0.60`` (wrapped as ``{"value": ..., "confidence": ...}``) so the low-confidence
        path can be exercised end to end.
        """
        kind = document.user_override_kind or document.detected_kind
        schema_cls = KIND_SCHEMA_MAP.get(kind)
        if schema_cls is None:
            return {}

        defaults: dict = {}
        if kind in {"id_document", "cpf", "caf", "proof_of_residence"}:
            defaults["full_name"] = STUB_FULL_NAME
        if kind in {"cpf", "id_document"}:
            defaults["document_number"] = STUB_DOCUMENT_NUMBER
        if kind == "proof_of_residence":
            defaults["address"] = "Rua Teste 100, Goiania Stub - GO"
        if kind == "car":
            defaults["car_code"] = "CAR-STUB-0001"
        if kind in {
            "public_deed",
            "land_registry",
            "purchase_sale_contract",
            "possession_title",
            "incra_ccir",
            "itr",
            "car",
        }:
            defaults["area_ha"] = Decimal("25.5000")
            defaults["municipality"] = STUB_MUNICIPALITY_IBGE
        if kind in {"public_deed", "land_registry"}:
            defaults["matricula"] = "M-100"
            defaults["ownership_type"] = "registered_deed"
        if kind == "purchase_sale_contract":
            defaults["ownership_type"] = "purchase_sale_contract"
        if kind in {"possession_title", "incra_ccir"}:
            defaults["ownership_type"] = "possession_incra"
        if kind == "marriage_certificate":
            defaults["full_name"] = STUB_FULL_NAME
            defaults["spouse_name"] = "Conjuge Teste 01"
            defaults["spouse_document_number"] = "000.000.000-01"
            defaults["marital_status"] = "married"
        if kind == "union_declaration":
            defaults["full_name"] = STUB_FULL_NAME
            defaults["partner_name"] = "Conjuge Teste 01"
            defaults["spouse_document_number"] = "000.000.000-01"
            defaults["marital_status"] = "stable_union"
        if kind == "budget_quote":
            defaults["description"] = "Stub budget item"
            defaults["amount"] = Decimal("1000.00")
        if kind == "herd_declaration":
            defaults["herd_size"] = 50
            defaults["activity_kind"] = "beef_cattle"
        if kind == "debt_statement":
            defaults["creditor"] = "Banco Stub"
            defaults["outstanding_balance"] = Decimal("0.00")
            defaults["annual_rate"] = Decimal("0.03")
        if kind == "caf":
            defaults["caf_code"] = "CAF-STUB-0001"
            defaults["full_name"] = STUB_FULL_NAME

        model = schema_cls.model_validate(defaults)
        fields = model.model_dump(mode="json")
        if "lowconf" in (document.original_filename or "").lower():
            return {
                key: {"value": value, "confidence": "0.60"}
                for key, value in fields.items()
                if value is not None
            }
        return fields


def get_extraction_provider() -> ExtractionProvider:
    provider_name = (getattr(settings, "EXTRACTION_PROVIDER", "stub") or "stub").lower()
    if provider_name in {"hybrid", "gemini", "vision"}:
        from acelera_agro.extraction.hybrid import HybridExtractionProvider

        return HybridExtractionProvider()
    return StubExtractionProvider()

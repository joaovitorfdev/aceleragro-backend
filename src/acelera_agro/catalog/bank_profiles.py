"""Bank profile definitions: BB GTM product + scaffolds for other banks.

New banks plug in here: checklist, export_formats, optional gtm_product.
Friction stays on export — shared proposal CRUD is bank-agnostic.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# BB document checklist with conditional rules by ownership_type / marital_status.
BB_DOCUMENT_CHECKLIST: list[dict[str, Any]] = [
    {"kind": "id_document", "required": True},
    {"kind": "cpf", "required": True},
    {"kind": "proof_of_residence", "required": True},
    {"kind": "caf", "required": True},
    {"kind": "car", "required": True},
    {"kind": "itr", "required": True},
    {"kind": "budget_quote", "required": True},
    {"kind": "debt_statement", "required": False},
    {
        "kind": "public_deed",
        "required": True,
        "when": {"ownership_type": ["registered_deed"]},
    },
    {
        "kind": "land_registry",
        "required": True,
        "when": {"ownership_type": ["registered_deed"]},
    },
    {
        "kind": "purchase_sale_contract",
        "required": True,
        "when": {"ownership_type": ["purchase_sale_contract"]},
    },
    {
        "kind": "possession_title",
        "required": True,
        "when": {"ownership_type": ["possession_incra"]},
    },
    {
        "kind": "incra_ccir",
        "required": True,
        "when": {"ownership_type": ["possession_incra", "registered_deed"]},
    },
    {
        "kind": "marriage_certificate",
        "required": True,
        "when": {"marital_status": ["married"]},
    },
    {
        "kind": "union_declaration",
        "required": True,
        "when": {"marital_status": ["stable_union"]},
    },
    {"kind": "herd_declaration", "required": False},
    {"kind": "guarantor_id", "required": False},
]

BB_PDF_SECTIONS = [
    "section_01_identification",
    "section_02_property",
    "section_03_activity",
    "section_04_budget",
    "section_05_schedule",
    "section_06_capacity",
    "section_07_classification",
    "section_08_opinion",
    "annex_budget",
    "annex_classification",
]

# Marco 8 GTM slice: Pronaf Investimento · beef cattle (BB).
BB_GTM_PRODUCT: dict[str, Any] = {
    "credit_purpose": "investment",
    "activity_kind": "beef_cattle",
    "accepted_group_codes": ["B", "AF", "PRONAF_B", "PRONAF"],
    "preferred_credit_line_codes": [
        "pronaf_investimento",
        "pronaf_eco",
        "pronaf_mais_alimentos",
    ],
    "label": "Pronaf Investimento · bovinocultura de corte",
}

BANK_PROFILE_SEEDS: list[dict[str, Any]] = [
    {
        "code": "bb",
        "name": "Banco do Brasil",
        "is_active": True,
        "document_checklist": BB_DOCUMENT_CHECKLIST,
        "pdf_sections": BB_PDF_SECTIONS,
        "extra_config": {
            "full_support": True,
            # API doc_type for GET/POST /pdf/{doc_type}
            "export_formats": ["bb"],
            "gtm_product": BB_GTM_PRODUCT,
        },
    },
    {
        "code": "caixa",
        "name": "Caixa Econômica Federal",
        "is_active": False,
        "document_checklist": [],
        "pdf_sections": [],
        "extra_config": {
            "scaffold": True,
            "export_formats": [],
            "planned_export": "xlsm",
        },
    },
    {
        "code": "basa",
        "name": "BASA",
        "is_active": False,
        "document_checklist": [],
        "pdf_sections": [],
        "extra_config": {"scaffold": True, "export_formats": []},
    },
    {
        "code": "sicredi",
        "name": "Sicredi",
        "is_active": False,
        "document_checklist": [],
        "pdf_sections": [],
        "extra_config": {"scaffold": True, "export_formats": []},
    },
    {
        "code": "sicoob",
        "name": "Sicoob",
        "is_active": False,
        "document_checklist": [],
        "pdf_sections": [],
        "extra_config": {"scaffold": True, "export_formats": []},
    },
]

DEFAULT_CREDIT_LINES: list[dict[str, Any]] = [
    {
        "code": "pronaf_investimento",
        "name": "Pronaf Investimento",
        "annual_rate": Decimal("0.03"),
        "term_years": 10,
        "grace_years": 3,
        "charge_interest_during_grace": False,
        "extra_config": {
            "gtm": True,
            "credit_purpose": "investment",
            "activity_kinds": ["beef_cattle", "agriculture", "dairy_cattle"],
        },
    },
    {
        "code": "pronaf_eco",
        "name": "Pronaf Eco",
        "annual_rate": Decimal("0.03"),
        "term_years": 10,
        "grace_years": 3,
        "charge_interest_during_grace": False,
    },
    {
        "code": "pronaf_mais_alimentos",
        "name": "Pronaf Mais Alimentos",
        "annual_rate": Decimal("0.04"),
        "term_years": 10,
        "grace_years": 2,
        "charge_interest_during_grace": False,
    },
]

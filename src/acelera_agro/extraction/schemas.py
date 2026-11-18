"""Pydantic extraction field schemas (English field names)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class IdDocumentFields(BaseModel):
    full_name: str | None = None
    document_number: str | None = None
    birth_date: str | None = None


class CpfFields(BaseModel):
    document_number: str | None = None
    full_name: str | None = None


class MarriageCertificateFields(BaseModel):
    full_name: str | None = None
    spouse_name: str | None = None
    spouse_document_number: str | None = None
    marital_status: str = "married"


class UnionDeclarationFields(BaseModel):
    full_name: str | None = None
    partner_name: str | None = None
    spouse_document_number: str | None = None
    marital_status: str = "stable_union"


class ProofOfResidenceFields(BaseModel):
    address: str | None = None
    full_name: str | None = None


class PublicDeedFields(BaseModel):
    matricula: str | None = None
    area_ha: Decimal | None = None
    municipality: str | None = None
    ownership_type: str = "registered_deed"


class PurchaseSaleContractFields(BaseModel):
    area_ha: Decimal | None = None
    municipality: str | None = None
    ownership_type: str = "purchase_sale_contract"


class LandRegistryFields(BaseModel):
    matricula: str | None = None
    area_ha: Decimal | None = None
    municipality: str | None = None
    ownership_type: str = "registered_deed"


class PossessionTitleFields(BaseModel):
    area_ha: Decimal | None = None
    municipality: str | None = None
    ownership_type: str = "possession_incra"


class IncraCcirFields(BaseModel):
    nirf: str | None = None
    area_ha: Decimal | None = None
    municipality: str | None = None
    ownership_type: str = "possession_incra"


class CarFields(BaseModel):
    car_code: str | None = None
    area_ha: Decimal | None = None
    municipality: str | None = None


class CafFields(BaseModel):
    caf_code: str | None = None
    full_name: str | None = None


class ItrFields(BaseModel):
    nirf: str | None = None
    area_ha: Decimal | None = None
    municipality: str | None = None


class BudgetQuoteFields(BaseModel):
    description: str | None = None
    amount: Decimal | None = None


class DebtStatementFields(BaseModel):
    creditor: str | None = None
    outstanding_balance: Decimal | None = None
    annual_rate: Decimal | None = None


class HerdDeclarationFields(BaseModel):
    herd_size: int | None = None
    activity_kind: str | None = None


KIND_SCHEMA_MAP: dict[str, type[BaseModel]] = {
    "id_document": IdDocumentFields,
    "cpf": CpfFields,
    "marriage_certificate": MarriageCertificateFields,
    "union_declaration": UnionDeclarationFields,
    "proof_of_residence": ProofOfResidenceFields,
    "public_deed": PublicDeedFields,
    "purchase_sale_contract": PurchaseSaleContractFields,
    "land_registry": LandRegistryFields,
    "possession_title": PossessionTitleFields,
    "incra_ccir": IncraCcirFields,
    "car": CarFields,
    "caf": CafFields,
    "itr": ItrFields,
    "budget_quote": BudgetQuoteFields,
    "debt_statement": DebtStatementFields,
    "herd_declaration": HerdDeclarationFields,
}

# Filename token → DocumentKind for stub classifier
FILENAME_KIND_HINTS: list[tuple[str, str]] = [
    ("escritura", "public_deed"),
    ("deed", "public_deed"),
    ("contrato_compra", "purchase_sale_contract"),
    ("purchase", "purchase_sale_contract"),
    ("matricula", "land_registry"),
    ("registry", "land_registry"),
    ("posse", "possession_title"),
    ("possession", "possession_title"),
    ("ccir", "incra_ccir"),
    ("incra", "incra_ccir"),
    ("car", "car"),
    ("caf", "caf"),
    ("itr", "itr"),
    ("rg", "id_document"),
    ("cnh", "id_document"),
    ("identidade", "id_document"),
    ("cpf", "cpf"),
    ("casamento", "marriage_certificate"),
    ("marriage", "marriage_certificate"),
    ("uniao", "union_declaration"),
    ("residencia", "proof_of_residence"),
    ("orcamento", "budget_quote"),
    ("budget", "budget_quote"),
    ("divida", "debt_statement"),
    ("debt", "debt_statement"),
    ("rebanho", "herd_declaration"),
    ("herd", "herd_declaration"),
    ("fiador", "guarantor_id"),
]

OWNERSHIP_FROM_KIND = {
    "public_deed": "registered_deed",
    "land_registry": "registered_deed",
    "purchase_sale_contract": "purchase_sale_contract",
    "possession_title": "possession_incra",
    "incra_ccir": "possession_incra",
}

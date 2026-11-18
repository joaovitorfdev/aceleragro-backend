"""Cheap filename + text heuristics for classify/extract without vision."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from acelera_agro.documents.models import DocumentKind
from acelera_agro.extraction.schemas import FILENAME_KIND_HINTS, KIND_SCHEMA_MAP

def _fold(value: str) -> str:
    """Lowercase ASCII-ish fold for PT-BR keyword matching without accents."""
    table = str.maketrans(
        "áàâãäéèêëíìîïóòôõöúùûüçñ",
        "aaaaaeeeeiiiiooooouuuucn",
    )
    return (value or "").lower().translate(table)


_KIND_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("caf", ("caf", "cadastro de agricultor", "agricultor familiar")),
    ("car", ("cadastro ambiental rural", "recibo car", "car n")),
    ("land_registry", ("matricula", "registro de imoveis", "certidao de matricula", "cri ")),
    ("public_deed", ("escritura publica", "tabeliao")),
    ("purchase_sale_contract", ("contrato de compra e venda", "compromisso de compra")),
    ("possession_title", ("titulo de posse", "declaracao de posse")),
    ("incra_ccir", ("ccir", "certificado de cadastro de imovel rural")),
    ("itr", ("itr", "imposto territorial rural", "nirf")),
    ("cpf", ("cadastro de pessoas fisicas", "cpf")),
    ("id_document", ("carteira de identidade", "registro geral", "cnh", "rg ")),
    ("marriage_certificate", ("certidao de casamento",)),
    ("union_declaration", ("uniao estavel",)),
    ("proof_of_residence", ("comprovante de residencia",)),
    ("budget_quote", ("orcamento", "proposta comercial")),
    ("debt_statement", ("endividamento", "posicao de divida", "extrato de divida")),
    ("herd_declaration", ("declaracao de rebanho", "rebanho bovino", "ua ")),
]


def classify_from_filename(filename: str) -> tuple[str, Decimal] | None:
    name = (filename or "").lower()
    for token, kind in FILENAME_KIND_HINTS:
        if token in name:
            return kind, Decimal("0.8500")
    return None


def classify_from_text(text: str) -> tuple[str, Decimal]:
    lowered = _fold(text or "")
    if not lowered.strip():
        return DocumentKind.UNKNOWN, Decimal("0.1000")
    for kind, keywords in _KIND_KEYWORDS:
        hits = sum(1 for kw in keywords if _fold(kw) in lowered)
        if hits >= 1:
            conf = Decimal("0.7800") if hits == 1 else Decimal("0.8800")
            return kind, conf
    return DocumentKind.UNKNOWN, Decimal("0.2000")


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def extract_fields_from_text(kind: str, text: str) -> dict:
    """Best-effort regex extraction; validated against the kind schema when possible."""
    schema_cls = KIND_SCHEMA_MAP.get(kind)
    if schema_cls is None or not text:
        return {}

    raw: dict = {}
    cpf = _first_match(
        r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b",
        text,
    )
    area = _first_match(
        r"(\d{1,6}(?:[.,]\d{1,4})?)\s*(?:ha|hectares)\b",
        text,
    )
    matricula = _first_match(
        r"(?:matr[ií]cula|matricula)\s*[:=]?\s*([A-Za-z0-9.\-/]+)",
        text,
    )
    car = _first_match(
        r"\b([A-Z]{2}-\d{7}-[A-Z0-9.]{10,})\b",
        text,
    ) or _first_match(r"(?:CAR)\s*[:=]?\s*([A-Z0-9.\-]{10,})", text)
    caf = _first_match(r"(?:CAF)\s*[:=]?\s*([A-Z0-9.\-/]{5,})", text)
    nirf = _first_match(r"(?:NIRF)\s*[:=]?\s*([0-9.\-/]{5,})", text)

    if kind in {"cpf", "id_document"} and cpf:
        raw["document_number"] = cpf
    if kind in {
        "public_deed",
        "land_registry",
        "purchase_sale_contract",
        "possession_title",
        "incra_ccir",
        "itr",
        "car",
    }:
        if area:
            try:
                raw["area_ha"] = Decimal(area.replace(",", "."))
            except InvalidOperation:
                pass
    if kind in {"public_deed", "land_registry"} and matricula:
        raw["matricula"] = matricula
        raw["ownership_type"] = "registered_deed"
    if kind == "car" and car:
        raw["car_code"] = car
    if kind == "caf" and caf:
        raw["caf_code"] = caf
    if kind == "itr" and nirf:
        raw["nirf"] = nirf
    if kind == "purchase_sale_contract":
        raw["ownership_type"] = "purchase_sale_contract"
    if kind in {"possession_title", "incra_ccir"}:
        raw["ownership_type"] = "possession_incra"
    if kind == "marriage_certificate":
        raw["marital_status"] = "married"
    if kind == "union_declaration":
        raw["marital_status"] = "stable_union"

    try:
        model = schema_cls.model_validate(raw)
        dumped = model.model_dump(mode="json", exclude_none=True)
        return {
            key: {"value": value, "confidence": "0.72"}
            for key, value in dumped.items()
        }
    except Exception:
        return {
            key: {"value": value, "confidence": "0.55"}
            for key, value in raw.items()
        }

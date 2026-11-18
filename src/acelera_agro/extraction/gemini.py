"""Gemini Flash client for document classify + extract (one call)."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from django.conf import settings

from acelera_agro.documents.models import DocumentKind
from acelera_agro.extraction.schemas import KIND_SCHEMA_MAP

logger = logging.getLogger(__name__)

_ALLOWED_KINDS = sorted(KIND_SCHEMA_MAP.keys()) + [DocumentKind.UNKNOWN]


@dataclass
class AnalysisResult:
    kind: str
    confidence: Decimal
    fields: dict[str, Any]
    route: str
    raw_text_excerpt: str = ""


def _schema_hint(kind: str | None = None) -> str:
    if kind and kind in KIND_SCHEMA_MAP:
        fields = list(KIND_SCHEMA_MAP[kind].model_fields.keys())
        return f"Extract only these fields for kind={kind}: {fields}"
    lines = []
    for k, cls in KIND_SCHEMA_MAP.items():
        lines.append(f"- {k}: {list(cls.model_fields.keys())}")
    return "Known kinds and fields:\n" + "\n".join(lines)


def _build_prompt(*, forced_kind: str | None = None) -> str:
    kinds = ", ".join(_ALLOWED_KINDS)
    kind_instruction = (
        f'Use detected_kind "{forced_kind}".'
        if forced_kind and forced_kind != DocumentKind.UNKNOWN
        else f"Choose detected_kind from: {kinds}."
    )
    return f"""You read Brazilian rural-credit documents (photos or PDF text).
Return ONLY valid JSON (no markdown) with this shape:
{{
  "detected_kind": "<kind>",
  "confidence": 0.0,
  "fields": {{ "<field>": "<value or null>" }}
}}
{kind_instruction}
{_schema_hint(forced_kind)}
Rules:
- confidence is 0..1
- Use null for unknown fields; do not invent CPF/CNPJ/names of real people if unreadable
- Money/rates as decimal strings; areas as decimal hectares
- Prefer Portuguese document cues (CAF, CAR, matrícula, CPF, RG, orçamento)
"""


def _parse_json_content(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}


def _normalize_result(payload: dict[str, Any], *, forced_kind: str | None = None) -> AnalysisResult:
    kind = str(payload.get("detected_kind") or forced_kind or DocumentKind.UNKNOWN)
    if kind not in _ALLOWED_KINDS:
        kind = DocumentKind.UNKNOWN
    if forced_kind and forced_kind != DocumentKind.UNKNOWN:
        kind = forced_kind

    try:
        confidence = Decimal(str(payload.get("confidence", "0.5")))
    except Exception:
        confidence = Decimal("0.5000")
    if confidence < 0:
        confidence = Decimal("0")
    if confidence > 1:
        confidence = Decimal("1")

    raw_fields = payload.get("fields") or {}
    if not isinstance(raw_fields, dict):
        raw_fields = {}

    schema_cls = KIND_SCHEMA_MAP.get(kind)
    fields: dict[str, Any] = {}
    if schema_cls is not None:
        try:
            model = schema_cls.model_validate(raw_fields)
            dumped = model.model_dump(mode="json", exclude_none=True)
            fields = {
                key: {"value": value, "confidence": str(confidence.quantize(Decimal("0.0001")))}
                for key, value in dumped.items()
            }
        except Exception:
            for key, value in raw_fields.items():
                if value is None or value == "":
                    continue
                fields[str(key)] = {
                    "value": value,
                    "confidence": str(confidence.quantize(Decimal("0.0001"))),
                }

    return AnalysisResult(
        kind=kind,
        confidence=confidence.quantize(Decimal("0.0001")),
        fields=fields,
        route="gemini",
    )


def gemini_configured() -> bool:
    return bool(getattr(settings, "GEMINI_API_KEY", "") or "")


def analyze_with_gemini(
    *,
    text: str | None = None,
    image_bytes: bytes | None = None,
    mime_type: str = "image/jpeg",
    forced_kind: str | None = None,
) -> AnalysisResult:
    """One Gemini call: classify + extract. Text and/or image parts."""
    api_key = getattr(settings, "GEMINI_API_KEY", "") or ""
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    model = getattr(settings, "GEMINI_MODEL", "gemini-2.0-flash")
    timeout = float(getattr(settings, "EXTRACTION_HTTP_TIMEOUT_SECONDS", 60))
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )

    parts: list[dict[str, Any]] = [{"text": _build_prompt(forced_kind=forced_kind)}]
    if text:
        # Cap text to keep cost bounded
        clipped = text[:12000]
        parts.append({"text": f"Document text:\n{clipped}"})
    if image_bytes:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type or "image/jpeg",
                    "data": b64,
                }
            }
        )

    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    with httpx.Client(timeout=timeout) as client:
        response = client.post(url, params={"key": api_key}, json=body)
        response.raise_for_status()
        payload = response.json()

    try:
        candidates = payload.get("candidates") or []
        parts_out = candidates[0]["content"]["parts"]
        text_out = "".join(p.get("text", "") for p in parts_out if isinstance(p, dict))
    except (KeyError, IndexError, TypeError):
        logger.warning("Unexpected Gemini response shape")
        text_out = ""

    parsed = _parse_json_content(text_out)
    result = _normalize_result(parsed, forced_kind=forced_kind)
    return AnalysisResult(
        kind=result.kind,
        confidence=result.confidence,
        fields=result.fields,
        route=result.route,
        raw_text_excerpt=(text or "")[:200],
    )

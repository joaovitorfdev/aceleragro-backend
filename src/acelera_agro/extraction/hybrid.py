"""Hybrid extraction: text-layer router + Gemini vision + heuristic fallback."""

from __future__ import annotations

import logging
from decimal import Decimal

from acelera_agro.documents.models import Document, DocumentKind
from acelera_agro.extraction.gemini import (
    AnalysisResult,
    analyze_with_gemini,
    gemini_configured,
)
from acelera_agro.extraction.heuristics import (
    classify_from_filename,
    classify_from_text,
    extract_fields_from_text,
)
from acelera_agro.extraction.media import load_document_media
from acelera_agro.extraction.router import ExtractionRoute, choose_route

logger = logging.getLogger(__name__)


class HybridExtractionProvider:
    """Bank-agnostic document reader used by the form contract pipeline.

    - PDF with native text → cheap text path (heuristics, Gemini text if keyed)
    - Photos / scanned PDFs → Gemini vision (one call for classify+extract)
    - Missing key / failures → filename heuristics, never crash the upload flow
    """

    def __init__(self) -> None:
        self._cache: dict[int, AnalysisResult] = {}

    def classify(self, document: Document) -> tuple[str, Decimal]:
        result = self._analyze(document)
        return result.kind, result.confidence

    def extract(self, document: Document) -> dict:
        cached = self._cache.get(document.id)
        if cached is None:
            cached = self._analyze(document)
        # If technician overrode kind after classify, re-run extract for that kind.
        forced = (document.user_override_kind or "").strip()
        if forced and forced != cached.kind and forced != DocumentKind.UNKNOWN:
            refreshed = self._analyze(document, forced_kind=forced)
            return refreshed.fields
        return cached.fields

    def _analyze(
        self,
        document: Document,
        *,
        forced_kind: str | None = None,
    ) -> AnalysisResult:
        media = load_document_media(document)
        decision = choose_route(media)
        filename = media.filename

        if decision.route == ExtractionRoute.EMPTY:
            result = self._fallback(document, filename, reason="empty_bytes")
            self._cache[document.id] = result
            return result

        try:
            if decision.route == ExtractionRoute.TEXT:
                result = self._analyze_text(
                    document,
                    text=decision.text,
                    filename=filename,
                    forced_kind=forced_kind,
                )
            else:
                result = self._analyze_vision(
                    document,
                    data=media.data,
                    mime_type=media.content_type,
                    filename=filename,
                    forced_kind=forced_kind,
                )
        except Exception:
            logger.exception(
                "Hybrid extraction failed; falling back",
                extra={"document_id": document.id, "route": decision.route.value},
            )
            result = self._fallback(document, filename, reason="provider_error")

        self._cache[document.id] = result
        return result

    def _analyze_text(
        self,
        document: Document,
        *,
        text: str,
        filename: str,
        forced_kind: str | None,
    ) -> AnalysisResult:
        kind = forced_kind
        confidence = Decimal("0.8000")
        if not kind:
            hinted = classify_from_filename(filename)
            if hinted:
                kind, confidence = hinted
            else:
                kind, confidence = classify_from_text(text)

        if gemini_configured():
            try:
                return analyze_with_gemini(
                    text=text,
                    forced_kind=kind if kind != DocumentKind.UNKNOWN else None,
                )
            except Exception:
                logger.exception(
                    "Gemini text analysis failed; using heuristics",
                    extra={"document_id": document.id},
                )

        fields = extract_fields_from_text(kind, text)
        return AnalysisResult(
            kind=kind,
            confidence=confidence,
            fields=fields,
            route="text_heuristics",
            raw_text_excerpt=text[:200],
        )

    def _analyze_vision(
        self,
        document: Document,
        *,
        data: bytes,
        mime_type: str,
        filename: str,
        forced_kind: str | None,
    ) -> AnalysisResult:
        if gemini_configured() and data:
            mime = mime_type if mime_type.startswith("image/") else "image/jpeg"
            # PDF scans: Gemini accepts application/pdf as inline_data on many models
            if filename.lower().endswith(".pdf") or mime_type == "application/pdf":
                mime = "application/pdf"
            return analyze_with_gemini(
                image_bytes=data,
                mime_type=mime,
                forced_kind=forced_kind,
            )
        return self._fallback(document, filename, reason="vision_unavailable")

    def _fallback(
        self,
        document: Document,
        filename: str,
        *,
        reason: str,
    ) -> AnalysisResult:
        hinted = classify_from_filename(filename)
        if hinted:
            kind, confidence = hinted
        else:
            kind, confidence = DocumentKind.UNKNOWN, Decimal("0.1000")
        # Reuse stub-like empty fields; caller may still label manually.
        logger.info(
            "Extraction fallback",
            extra={
                "document_id": document.id,
                "reason": reason,
                "kind": kind,
            },
        )
        return AnalysisResult(
            kind=kind,
            confidence=confidence,
            fields={},
            route=f"fallback:{reason}",
        )

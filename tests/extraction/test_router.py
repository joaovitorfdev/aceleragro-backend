"""PDF text-layer router decisions."""

from __future__ import annotations

import io

import pytest

from acelera_agro.extraction.media import DocumentMedia
from acelera_agro.extraction.router import ExtractionRoute, choose_route, extract_pdf_text


def _pdf_with_text(text: str) -> bytes:
    from pypdf import PdfWriter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    # reportlab already embeds a text layer
    return buf.getvalue()


def test_image_routes_to_vision():
    media = DocumentMedia(
        data=b"\xff\xd8\xff",
        content_type="image/jpeg",
        filename="rg_campo.jpg",
    )
    decision = choose_route(media)
    assert decision.route == ExtractionRoute.VISION
    assert decision.reason == "image_content_type"


def test_empty_bytes_route():
    media = DocumentMedia(data=b"", content_type="application/pdf", filename="x.pdf")
    decision = choose_route(media)
    assert decision.route == ExtractionRoute.EMPTY


def test_pdf_with_text_layer_routes_to_text(settings):
    settings.EXTRACTION_MIN_TEXT_CHARS = 20
    payload = _pdf_with_text("Matricula 12.345 area 25 ha Cadastro Ambiental Rural")
    media = DocumentMedia(
        data=payload,
        content_type="application/pdf",
        filename="matricula.pdf",
    )
    decision = choose_route(media)
    assert decision.route == ExtractionRoute.TEXT
    assert "Matricula" in decision.text or "matricula" in decision.text.lower()
    assert len(extract_pdf_text(payload)) >= 20


def test_thin_pdf_routes_to_vision(settings):
    settings.EXTRACTION_MIN_TEXT_CHARS = 5000
    payload = _pdf_with_text("x")
    media = DocumentMedia(
        data=payload,
        content_type="application/pdf",
        filename="scan.pdf",
    )
    decision = choose_route(media)
    assert decision.route == ExtractionRoute.VISION

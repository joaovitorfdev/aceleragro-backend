"""Hybrid provider: heuristics without Gemini + mocked vision path."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO

import pytest

from acelera_agro.documents.models import Document
from acelera_agro.extraction.gemini import AnalysisResult
from acelera_agro.extraction.hybrid import HybridExtractionProvider
from acelera_agro.extraction.providers import get_extraction_provider
from acelera_agro.proposals.models import Proposal


def _pdf_bytes(text: str) -> bytes:
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


@pytest.mark.django_db
def test_factory_hybrid(settings):
    settings.EXTRACTION_PROVIDER = "hybrid"
    provider = get_extraction_provider()
    assert provider.__class__.__name__ == "HybridExtractionProvider"


@pytest.mark.django_db
def test_hybrid_text_path_without_gemini(
    settings, office, organization, tenant_ctx, catalog
):
    settings.EXTRACTION_PROVIDER = "hybrid"
    settings.GEMINI_API_KEY = ""
    settings.EXTRACTION_MIN_TEXT_CHARS = 20

    proposal = Proposal.objects.create(office=office, organization=organization)
    doc = Document.objects.create(
        office=office,
        proposal=proposal,
        s3_key="k/matricula.pdf",
        original_filename="matricula.pdf",
        content_type="application/pdf",
    )
    doc._test_bytes = _pdf_bytes(  # type: ignore[attr-defined]
        "CERTIDAO DE MATRICULA do imovel area 12,50 ha Registro de Imoveis"
    )

    provider = HybridExtractionProvider()
    kind, confidence = provider.classify(doc)
    assert kind == "land_registry"
    assert confidence > Decimal("0.5")
    fields = provider.extract(doc)
    # Heuristic may or may not catch area; kind must stick.
    assert isinstance(fields, dict)


@pytest.mark.django_db
def test_hybrid_vision_uses_gemini_mock(
    settings, office, organization, tenant_ctx, monkeypatch
):
    settings.EXTRACTION_PROVIDER = "hybrid"
    settings.GEMINI_API_KEY = "test-key"

    proposal = Proposal.objects.create(office=office, organization=organization)
    doc = Document.objects.create(
        office=office,
        proposal=proposal,
        s3_key="k/rg.jpg",
        original_filename="rg_campo.jpg",
        content_type="image/jpeg",
    )
    doc._test_bytes = b"\xff\xd8\xff\xd9"  # type: ignore[attr-defined]

    def fake_gemini(**kwargs):
        assert kwargs.get("image_bytes")
        return AnalysisResult(
            kind="id_document",
            confidence=Decimal("0.9100"),
            fields={
                "full_name": {"value": "Produtor Teste 01", "confidence": "0.9100"},
                "document_number": {"value": "000.000.000-00", "confidence": "0.9100"},
            },
            route="gemini",
        )

    monkeypatch.setattr(
        "acelera_agro.extraction.hybrid.analyze_with_gemini",
        fake_gemini,
    )
    monkeypatch.setattr(
        "acelera_agro.extraction.hybrid.gemini_configured",
        lambda: True,
    )

    provider = HybridExtractionProvider()
    kind, conf = provider.classify(doc)
    assert kind == "id_document"
    assert conf == Decimal("0.9100")
    fields = provider.extract(doc)
    assert fields["full_name"]["value"] == "Produtor Teste 01"


@pytest.mark.django_db
def test_hybrid_vision_without_key_falls_back_filename(
    settings, office, organization, tenant_ctx
):
    settings.GEMINI_API_KEY = ""
    proposal = Proposal.objects.create(office=office, organization=organization)
    doc = Document.objects.create(
        office=office,
        proposal=proposal,
        s3_key="k/cpf.jpg",
        original_filename="cpf_produtor.jpg",
        content_type="image/jpeg",
    )
    doc._test_bytes = b"\xff\xd8\xff\xd9"  # type: ignore[attr-defined]

    provider = HybridExtractionProvider()
    kind, _ = provider.classify(doc)
    assert kind == "cpf"

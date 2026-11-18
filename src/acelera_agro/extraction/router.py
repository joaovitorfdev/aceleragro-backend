"""Route documents to cheap text extraction vs vision."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from enum import Enum

from django.conf import settings

from acelera_agro.extraction.media import DocumentMedia

_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/tiff",
    "image/gif",
}

_PDF_TYPES = {"application/pdf"}


class ExtractionRoute(str, Enum):
    TEXT = "text"
    VISION = "vision"
    EMPTY = "empty"


@dataclass(frozen=True)
class RouteDecision:
    route: ExtractionRoute
    text: str
    reason: str


def _is_image(content_type: str, filename: str) -> bool:
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct in _IMAGE_TYPES:
        return True
    lower = filename.lower()
    return lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".tif", ".tiff", ".gif"))


def _is_pdf(content_type: str, filename: str) -> bool:
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct in _PDF_TYPES:
        return True
    return filename.lower().endswith(".pdf")


def extract_pdf_text(data: bytes, *, max_pages: int = 8) -> str:
    """Extract native text layer from a PDF (no OCR)."""
    if not data:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return ""

    chunks: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            chunks.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(chunks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def choose_route(media: DocumentMedia) -> RouteDecision:
    """Decide whether to use text-layer path or vision.

    - Images → vision
    - PDF with enough extractable text → text (cheap)
    - PDF with little/no text (scan) → vision
    - Empty bytes → empty
    """
    min_chars = int(getattr(settings, "EXTRACTION_MIN_TEXT_CHARS", 80))
    if not media.data:
        return RouteDecision(
            route=ExtractionRoute.EMPTY,
            text="",
            reason="empty_bytes",
        )

    if _is_image(media.content_type, media.filename):
        return RouteDecision(
            route=ExtractionRoute.VISION,
            text="",
            reason="image_content_type",
        )

    if _is_pdf(media.content_type, media.filename):
        text = extract_pdf_text(media.data)
        if len(text) >= min_chars:
            return RouteDecision(
                route=ExtractionRoute.TEXT,
                text=text,
                reason="pdf_text_layer",
            )
        return RouteDecision(
            route=ExtractionRoute.VISION,
            text=text,
            reason="pdf_scan_or_thin_text",
        )

    # Unknown binary: try PDF parse, else vision
    text = extract_pdf_text(media.data)
    if len(text) >= min_chars:
        return RouteDecision(
            route=ExtractionRoute.TEXT,
            text=text,
            reason="binary_pdf_text_layer",
        )
    return RouteDecision(
        route=ExtractionRoute.VISION,
        text="",
        reason="unknown_binary",
    )

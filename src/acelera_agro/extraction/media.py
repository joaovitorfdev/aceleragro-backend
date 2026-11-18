"""Load document bytes from object storage (or test fixtures)."""

from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass

from django.conf import settings

from acelera_agro.documents.models import Document

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocumentMedia:
    data: bytes
    content_type: str
    filename: str


def _guess_content_type(document: Document) -> str:
    if document.content_type:
        return document.content_type
    name = document.original_filename or document.s3_key or ""
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def load_document_media(document: Document) -> DocumentMedia:
    """Fetch raw bytes for classification/extraction.

    In TESTING, returns empty bytes unless ``document`` has a ``_test_bytes`` attr
    (set by unit tests). Production loads from S3/MinIO via boto3.
    """
    filename = document.original_filename or document.s3_key or "document"
    content_type = _guess_content_type(document)
    test_bytes = getattr(document, "_test_bytes", None)
    if test_bytes is not None:
        return DocumentMedia(
            data=bytes(test_bytes),
            content_type=content_type,
            filename=filename,
        )

    if getattr(settings, "TESTING", False):
        return DocumentMedia(data=b"", content_type=content_type, filename=filename)

    try:
        import boto3

        client = boto3.client(
            "s3",
            endpoint_url=settings.AWS_S3_ENDPOINT_URL,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME,
        )
        obj = client.get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=document.s3_key,
        )
        data = obj["Body"].read()
        return DocumentMedia(data=data, content_type=content_type, filename=filename)
    except Exception:
        logger.exception(
            "Failed to load document media",
            extra={"document_id": document.id, "s3_key": document.s3_key},
        )
        return DocumentMedia(data=b"", content_type=content_type, filename=filename)

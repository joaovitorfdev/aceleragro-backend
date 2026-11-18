"""Presigned upload helpers (stub-friendly when S3 unavailable)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

# In-memory object store for TESTING (and local fallbacks).
_TEST_OBJECTS: dict[str, bytes] = {}


def build_object_key(*, office_id: int, proposal_id: int, filename: str) -> str:
    safe = filename.replace("/", "_").replace("\\", "_")
    return f"offices/{office_id}/proposals/{proposal_id}/{uuid.uuid4().hex}_{safe}"


def build_org_brand_key(*, organization_id: int, kind: str, filename: str) -> str:
    """kind: logo | banner."""
    safe = filename.replace("/", "_").replace("\\", "_")
    return f"orgs/{organization_id}/{kind}/{uuid.uuid4().hex}_{safe}"


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.AWS_S3_ENDPOINT_URL,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_S3_REGION_NAME,
    )


def put_object_bytes(*, key: str, data: bytes, content_type: str) -> None:
    """Persist bytes to S3/MinIO. In TESTING, keeps an in-memory copy."""
    if getattr(settings, "TESTING", False):
        _TEST_OBJECTS[key] = data
        return
    try:
        _s3_client().put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
    except Exception:
        logger.exception("Failed to put object", extra={"key": key})
        # Local/dev fallback so brand upload still records a key.
        _TEST_OBJECTS[key] = data


def get_object_bytes(key: str) -> bytes | None:
    if not key:
        return None
    if key in _TEST_OBJECTS:
        return _TEST_OBJECTS[key]
    if getattr(settings, "TESTING", False):
        return None
    try:
        obj = _s3_client().get_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=key,
        )
        return obj["Body"].read()
    except Exception:
        logger.exception("Failed to get object", extra={"key": key})
        return None


def create_presigned_upload(
    *,
    key: str,
    content_type: str,
    expires_in: int = 3600,
) -> dict[str, Any]:
    """Return a upload URL. In TESTING, returns a stub URL without calling S3."""
    if getattr(settings, "TESTING", False):
        return {
            "url": f"https://example.local/upload/{key}",
            "fields": {},
            "method": "PUT",
            "headers": {"Content-Type": content_type},
            "expires_in": expires_in,
        }

    try:
        client = _s3_client()
        url = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.AWS_STORAGE_BUCKET_NAME,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )
        return {
            "url": url,
            "fields": {},
            "method": "PUT",
            "headers": {"Content-Type": content_type},
            "expires_in": expires_in,
        }
    except Exception:
        return {
            "url": f"{settings.AWS_S3_ENDPOINT_URL}/{settings.AWS_STORAGE_BUCKET_NAME}/{key}",
            "fields": {},
            "method": "PUT",
            "headers": {"Content-Type": content_type},
            "expires_in": expires_in,
        }

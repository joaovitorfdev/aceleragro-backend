"""HTTP middleware: tenant cleanup + Idempotency-Key for POSTs."""

from __future__ import annotations

import contextlib
import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.utils import timezone

from acelera_agro.accounts.models import IdempotencyRecord
from acelera_agro.tenants import context as tenant_context


class TenantContextMiddleware:
    """Clear tenant contextvars after each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        try:
            return self.get_response(request)
        finally:
            tenant_context.clear_tenant_context()


class IdempotencyMiddleware:
    """Replay stored responses for Idempotency-Key on POST/PUT/PATCH."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest):
        if request.method not in {"POST", "PUT", "PATCH"}:
            return self.get_response(request)

        key = request.headers.get("Idempotency-Key") or request.META.get(
            "HTTP_IDEMPOTENCY_KEY"
        )
        if not key:
            return self.get_response(request)

        body = request.body or b""
        request_hash = hashlib.sha256(body).hexdigest()
        path = request.path

        # Office may only be known after JWT auth inside the view; match either
        # scoped or unscoped stored keys on replay.
        existing = (
            IdempotencyRecord.objects.filter(
                key=key, path=path, method=request.method
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            if existing.request_hash != request_hash:
                return JsonResponse(
                    {"detail": "Idempotency-Key reuse with different body"},
                    status=409,
                )
            ttl = getattr(settings, "IDEMPOTENCY_TTL_SECONDS", 86400)
            if existing.created_at < timezone.now() - timedelta(seconds=ttl):
                existing.delete()
            else:
                return HttpResponse(
                    existing.response_body,
                    status=existing.response_status,
                    content_type="application/json",
                )

        response = self.get_response(request)

        office_id = tenant_context.get_office_id()
        user_id = getattr(getattr(request, "user", None), "id", None)

        if 200 <= response.status_code < 500 and hasattr(response, "content"):
            content = response.content.decode("utf-8", errors="replace")
            with contextlib.suppress(Exception):
                IdempotencyRecord.objects.update_or_create(
                    key=key,
                    office_id=office_id,
                    path=path,
                    method=request.method,
                    defaults={
                        "user_id": user_id,
                        "request_hash": request_hash,
                        "response_status": response.status_code,
                        "response_body": content
                        if content
                        else json.dumps({"ok": True}),
                    },
                )
        return response

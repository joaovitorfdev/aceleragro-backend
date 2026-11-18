"""Auth: login / refresh / logout with JWT claims and territorial lock."""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import Client

from acelera_agro.accounts.jwt_utils import decode_token
from acelera_agro.accounts.models import RefreshSession
from acelera_agro.tenants.models import Office


@pytest.mark.django_db
def test_login_issues_access_token_with_claims(user, membership, office, inside_coords):
    lat, lng = inside_coords
    client = Client()
    response = client.post(
        "/api/auth/login",
        data={
            "email": "tech@example.com",
            "password": "test-password-123",
            "device_fingerprint": "fp-login-1",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["office_id"] == office.id
    assert body["tenant_id"] == office.organization_id
    assert body["role"] == membership.role
    assert body["device_id"] is not None

    payload = decode_token(body["access_token"], expected_type="access")
    assert payload["sub"] == str(user.id)
    assert payload["tenant_id"] == office.organization_id
    assert payload["office_id"] == office.id
    assert payload["role"] == membership.role
    assert payload["device_id"] == body["device_id"]

    cookie_name = settings.JWT_REFRESH_COOKIE_NAME
    assert cookie_name in response.cookies
    assert RefreshSession.objects.filter(user=user, revoked_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_login_outside_geofence_forbidden(user, membership, outside_coords):
    lat, lng = outside_coords
    client = Client()
    response = client.post(
        "/api/auth/login",
        data={
            "email": "tech@example.com",
            "password": "test-password-123",
            "device_fingerprint": "fp-login-out",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_refresh_rotates_single_session(user, membership, office, inside_coords):
    lat, lng = inside_coords
    client = Client()
    login = client.post(
        "/api/auth/login",
        data={
            "email": "tech@example.com",
            "password": "test-password-123",
            "device_fingerprint": "fp-refresh-1",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert login.status_code == 200
    first_jti = RefreshSession.objects.get(user=user, revoked_at__isnull=True).jti

    refresh = client.post("/api/auth/refresh")
    assert refresh.status_code == 200, refresh.content
    body = refresh.json()
    assert body["access_token"]
    assert RefreshSession.objects.filter(jti=first_jti).first().revoked_at is not None
    assert RefreshSession.objects.filter(user=user, revoked_at__isnull=True).count() == 1


@pytest.mark.django_db
def test_logout_revokes_session(user, membership, inside_coords):
    lat, lng = inside_coords
    client = Client()
    login = client.post(
        "/api/auth/login",
        data={
            "email": "tech@example.com",
            "password": "test-password-123",
            "device_fingerprint": "fp-logout-1",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    token = login.json()["access_token"]
    response = client.post(
        "/api/auth/logout",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 200
    assert RefreshSession.objects.filter(user=user, revoked_at__isnull=True).count() == 0


@pytest.mark.django_db
def test_suspended_office_blocks_mutating_routes(
    user, membership, office, inside_coords, catalog, tenant_ctx
):
    from acelera_agro.proposals.models import Proponent

    lat, lng = inside_coords
    client = Client()
    login = client.post(
        "/api/auth/login",
        data={
            "email": "tech@example.com",
            "password": "test-password-123",
            "device_fingerprint": "fp-suspend-1",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    token = login.json()["access_token"]

    office.status = Office.Status.SUSPENDED
    office.save(update_fields=["status"])

    # Need a proponent for create; create via all_objects then call API
    proponent = Proponent.all_objects.create(
        organization=office.organization, full_name="Produtor Suspend"
    )
    response = client.post(
        "/api/proposals",
        data={
            "proponent_id": proponent.id,
            "bank_profile_id": catalog["profiles"]["bb"].id,
            "financed_amount": "1000.00",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert response.status_code == 403

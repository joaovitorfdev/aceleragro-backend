"""Marco T6 — account profile, devices, logout."""

from __future__ import annotations

import pytest


@pytest.mark.django_db
def test_auth_me_and_profile_update(user, membership, office, inside_coords):
    from django.test import Client

    lat, lng = inside_coords
    client = Client()
    login = client.post(
        "/api/auth/login",
        data={
            "email": "tech@example.com",
            "password": "test-password-123",
            "device_fingerprint": "fp-account-me",
            "lat": str(lat),
            "lng": str(lng),
        },
        content_type="application/json",
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    me = client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert me.status_code == 200, me.content
    body = me.json()
    assert body["email"] == "tech@example.com"
    assert body["office_id"] == office.id
    assert body["role"] == membership.role

    patched = client.patch(
        "/api/auth/me",
        data={"full_name": "Tech Updated Stub"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert patched.status_code == 200, patched.content
    assert patched.json()["full_name"] == "Tech Updated Stub"

    devices = client.get("/api/devices", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert devices.status_code == 200
    assert len(devices.json()) >= 1
    device_id = devices.json()[0]["id"]

    revoked = client.post(
        f"/api/devices/{device_id}/revoke",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    assert revoked.status_code == 200
    assert revoked.json()["is_active"] is False

    logout = client.post("/api/auth/logout", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert logout.status_code == 200

"""Territorial lock: activation geofence + device limit."""

from __future__ import annotations

import pytest

from acelera_agro.tenants.models import Device
from acelera_agro.tenants.territorial import (
    TerritorialLockError,
    activate_device_in_municipality,
    assert_within_municipality,
)


@pytest.mark.django_db
def test_activation_inside_boundary(user, office, inside_coords):
    lat, lng = inside_coords
    device = activate_device_in_municipality(
        user=user,
        office=office,
        device_fingerprint="fp-inside-1",
        lat=lat,
        lng=lng,
    )
    assert device.activated_at is not None
    assert device.is_active is True
    assert device.last_lat == lat
    assert device.last_lng == lng


@pytest.mark.django_db
def test_activation_outside_boundary_raises(user, office, outside_coords):
    lat, lng = outside_coords
    with pytest.raises(TerritorialLockError) as exc:
        activate_device_in_municipality(
            user=user,
            office=office,
            device_fingerprint="fp-outside-1",
            lat=lat,
            lng=lng,
        )
    assert exc.value.code == "outside_municipality"


@pytest.mark.django_db
def test_missing_coordinates_raises(user, office):
    with pytest.raises(TerritorialLockError) as exc:
        activate_device_in_municipality(
            user=user,
            office=office,
            device_fingerprint="fp-missing",
            lat=None,
            lng=None,
        )
    assert exc.value.code == "missing_coordinates"


@pytest.mark.django_db
def test_device_limit_enforced(user, office, inside_coords, settings):
    settings.DEVICE_LIMIT_PER_OFFICE = 2
    lat, lng = inside_coords
    activate_device_in_municipality(
        user=user, office=office, device_fingerprint="fp-a", lat=lat, lng=lng
    )
    activate_device_in_municipality(
        user=user, office=office, device_fingerprint="fp-b", lat=lat, lng=lng
    )
    with pytest.raises(TerritorialLockError) as exc:
        activate_device_in_municipality(
            user=user, office=office, device_fingerprint="fp-c", lat=lat, lng=lng
        )
    assert exc.value.code == "device_limit_exceeded"
    assert Device.objects.filter(office=office, is_active=True).count() == 2


@pytest.mark.django_db
def test_assert_within_municipality_helper(municipality, inside_coords, outside_coords):
    lat, lng = inside_coords
    assert_within_municipality(municipality, lat, lng)
    olat, olng = outside_coords
    with pytest.raises(TerritorialLockError):
        assert_within_municipality(municipality, olat, olng)

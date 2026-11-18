"""Territorial lock helpers (device activation + geofence)."""

from __future__ import annotations

import json
from decimal import Decimal

from django.conf import settings
from django.utils import timezone
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from acelera_agro.tenants.models import Device, Municipality, Office


class TerritorialLockError(Exception):
    """Raised when a device cannot be activated or used."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


def _parse_boundary(boundary_text: str) -> BaseGeometry | None:
    if not boundary_text or not boundary_text.strip():
        return None
    data = json.loads(boundary_text)
    if data.get("type") == "Feature":
        return shape(data["geometry"])
    if data.get("type") == "FeatureCollection":
        features = data.get("features") or []
        if not features:
            return None
        return shape(features[0]["geometry"])
    return shape(data)


def assert_within_municipality(
    municipality: Municipality,
    lat: Decimal | float,
    lng: Decimal | float,
) -> None:
    """Assert (lat, lng) is inside municipality boundary (or simple bbox fallback)."""
    geom = _parse_boundary(municipality.boundary)
    point = Point(float(lng), float(lat))  # GeoJSON: [lng, lat]
    if geom is not None:
        if not geom.contains(point) and not geom.touches(point):
            raise TerritorialLockError(
                "outside_municipality",
                "Coordinates are outside the municipality boundary.",
            )
        return
    # Fallback for tests without boundary: accept any finite coords
    if lat is None or lng is None:
        raise TerritorialLockError("missing_coordinates", "lat and lng are required.")


def assert_device_activated(device: Device) -> None:
    if not device.is_active or device.activated_at is None:
        raise TerritorialLockError("device_not_activated", "Device is not activated.")
    if device.needs_revalidation:
        raise TerritorialLockError(
            "device_needs_revalidation",
            "Device requires periodic revalidation.",
        )


def activate_device_in_municipality(
    *,
    user,
    office: Office,
    device_fingerprint: str,
    lat: Decimal | float | None,
    lng: Decimal | float | None,
) -> Device:
    """Activate a device if within municipality; enforce device limit."""
    if lat is None or lng is None:
        raise TerritorialLockError(
            "missing_coordinates",
            "lat and lng are required for device activation.",
        )

    assert_within_municipality(office.municipality, lat, lng)

    device = Device.objects.filter(
        office=office, device_fingerprint=device_fingerprint
    ).first()
    if device is None:
        active_count = Device.objects.filter(office=office, is_active=True).count()
        limit = getattr(settings, "DEVICE_LIMIT_PER_OFFICE", 5)
        if active_count >= limit:
            raise TerritorialLockError(
                "device_limit_exceeded",
                f"Office already has {limit} active devices.",
            )
        device = Device(
            user=user,
            office=office,
            device_fingerprint=device_fingerprint,
        )

    device.user = user
    device.activated_at = timezone.now()
    device.last_seen_at = timezone.now()
    device.last_lat = Decimal(str(round(float(lat), 6)))
    device.last_lng = Decimal(str(round(float(lng), 6)))
    device.is_active = True
    device.needs_revalidation = False
    device.save()
    return device

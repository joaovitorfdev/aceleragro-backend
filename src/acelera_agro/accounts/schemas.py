from __future__ import annotations

from decimal import Decimal

from ninja import Schema


class LoginIn(Schema):
    email: str
    password: str
    device_fingerprint: str
    lat: Decimal | None = None
    lng: Decimal | None = None


class TokenOut(Schema):
    access_token: str
    token_type: str = "Bearer"
    tenant_id: int
    office_id: int | None = None
    role: str
    device_id: int | None = None
    needs_office: bool = False


class MessageOut(Schema):
    detail: str


class AccountMeOut(Schema):
    user_id: int
    email: str
    full_name: str
    tenant_id: int
    office_id: int | None = None
    role: str
    device_id: int | None = None
    needs_office: bool = False


class UpdateProfileIn(Schema):
    full_name: str

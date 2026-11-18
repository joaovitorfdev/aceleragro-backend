"""Catalog read APIs."""

from __future__ import annotations

from django.db.models import Q
from ninja import Router, Schema

from acelera_agro.accounts.auth import jwt_auth
from acelera_agro.accounts.rbac import assert_role
from acelera_agro.catalog.models import BankProfile, CreditLine, CropYear
from acelera_agro.tenants.models import Membership, Municipality

router = Router(tags=["catalog"], auth=jwt_auth)

_ALL = (
    Membership.Role.OWNER,
    Membership.Role.ADMIN,
    Membership.Role.TECHNICIAN,
    Membership.Role.VIEWER,
)


class BankProfileOut(Schema):
    id: int
    code: str
    name: str
    is_active: bool


class CreditLineOut(Schema):
    id: int
    code: str
    name: str
    bank_profile_id: int
    annual_rate: str
    term_years: int
    grace_years: int
    is_active: bool


class CropYearOut(Schema):
    id: int
    code: str
    label: str
    is_active: bool


class MunicipalityOut(Schema):
    ibge_code: str
    name: str
    state_uf: str


@router.get("/catalog/bank-profiles", response=list[BankProfileOut])
def list_bank_profiles(request):
    assert_role(*_ALL)
    return list(BankProfile.objects.all())


@router.get(
    "/catalog/municipalities",
    auth=None,
    response=list[MunicipalityOut],
)
def list_municipalities(request, q: str | None = None, limit: int = 30):
    """Public reference search (signup + office pickers). No personal data."""
    qs = Municipality.objects.all().order_by("state_uf", "name")
    term = (q or "").strip()
    if term:
        qs = qs.filter(Q(name__icontains=term) | Q(ibge_code__startswith=term))
    cap = max(1, min(limit, 100))
    return [
        MunicipalityOut(ibge_code=row.ibge_code, name=row.name, state_uf=row.state_uf)
        for row in qs[:cap]
    ]


@router.get("/catalog/credit-lines", response=list[CreditLineOut])
def list_credit_lines(request, bank_profile: str | None = None):
    assert_role(*_ALL)
    qs = CreditLine.objects.select_related("bank_profile").filter(is_active=True)
    if bank_profile:
        qs = qs.filter(bank_profile__code=bank_profile)
    return [
        CreditLineOut(
            id=row.id,
            code=row.code,
            name=row.name,
            bank_profile_id=row.bank_profile_id,
            annual_rate=str(row.annual_rate),
            term_years=row.term_years,
            grace_years=row.grace_years,
            is_active=row.is_active,
        )
        for row in qs
    ]


@router.get("/catalog/crop-years", response=list[CropYearOut])
def list_crop_years(request):
    assert_role(*_ALL)
    return list(CropYear.objects.filter(is_active=True))

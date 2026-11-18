"""Marco T7 — pilot seed: Bioflora stub + Cujubim/Porto Velho offices.

LGPD: organization/person identifiers are synthetic stubs inspired by the
pilot AT office shape. Real CNPJ / personal documents must not be committed.
Municipality IBGE codes and approximate boundaries are public geographic data
used only for territorial-lock testing.
"""

from __future__ import annotations

import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from acelera_agro.tenants.models import Membership, Municipality, Office, Organization

User = get_user_model()

# Approximate urban squares (lng/lat GeoJSON) — wide enough for local GPS tests.
# Cujubim ~ -9.36, -62.58 · Porto Velho ~ -8.76, -63.90
IBGE_CUJUBIM = "1100940"
IBGE_PORTO_VELHO = "1100205"

MUNICIPALITIES = [
    {
        "ibge_code": IBGE_CUJUBIM,
        "name": "Cujubim",
        "state_uf": "RO",
        "fiscal_module_ha": Decimal("60.0000"),
        "center": (-62.5842, -9.3627),
        "delta": 0.35,
    },
    {
        "ibge_code": IBGE_PORTO_VELHO,
        "name": "Porto Velho",
        "state_uf": "RO",
        "fiscal_module_ha": Decimal("60.0000"),
        "center": (-63.9039, -8.7619),
        "delta": 0.35,
    },
]

# Synthetic CNPJ (14 digits, not a real RF registration).
ORG_CNPJ = "11244777000191"
ORG_NAME = "Bioflora Agronegocios Stub LTDA"
ORG_TRADE = "Bioflora Agronegocios Stub"

OWNER_EMAIL = "leandro.owner@bioflora.stub.local"
OWNER_PASSWORD = "pilot-bioflora-2026"
OWNER_FULL_NAME = "Leandro Cordeiro Aredes Stub"

TECH_EMAIL = "tech.cujubim@bioflora.stub.local"
TECH_PASSWORD = "pilot-tech-2026"
TECH_FULL_NAME = "Tecnico Cujubim Stub"


def _square_boundary(lng: float, lat: float, delta: float) -> str:
    return json.dumps(
        {
            "type": "Polygon",
            "coordinates": [
                [
                    [lng - delta, lat - delta],
                    [lng + delta, lat - delta],
                    [lng + delta, lat + delta],
                    [lng - delta, lat + delta],
                    [lng - delta, lat - delta],
                ]
            ],
        }
    )


class Command(BaseCommand):
    help = (
        "Seed pilot tenant: Bioflora stub org, offices in Cujubim + Porto Velho (RO), "
        "owner + technician. Also runs seed_catalog."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-catalog",
            action="store_true",
            help="Do not call seed_catalog",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if not options.get("skip_catalog"):
            call_command("seed_catalog")

        munis: dict[str, Municipality] = {}
        for row in MUNICIPALITIES:
            lng, lat = row["center"]
            mun, _ = Municipality.objects.update_or_create(
                ibge_code=row["ibge_code"],
                defaults={
                    "name": row["name"],
                    "state_uf": row["state_uf"],
                    "fiscal_module_ha": row["fiscal_module_ha"],
                    "boundary": _square_boundary(lng, lat, row["delta"]),
                },
            )
            munis[row["ibge_code"]] = mun
            self.stdout.write(f"Municipality {mun.name}/{mun.state_uf} ({mun.ibge_code})")

        owner = User.objects.filter(email__iexact=OWNER_EMAIL).first()
        if owner is None:
            first, *rest = OWNER_FULL_NAME.split(" ", 1)
            owner = User.objects.create_user(
                username=OWNER_EMAIL,
                email=OWNER_EMAIL,
                password=OWNER_PASSWORD,
                first_name=first[:150],
                last_name=(rest[0] if rest else "")[:150],
            )
            self.stdout.write(f"Created owner {OWNER_EMAIL}")
        else:
            owner.set_password(OWNER_PASSWORD)
            owner.first_name = OWNER_FULL_NAME.split(" ", 1)[0][:150]
            owner.last_name = (
                OWNER_FULL_NAME.split(" ", 1)[1][:150]
                if " " in OWNER_FULL_NAME
                else ""
            )
            owner.save()
            self.stdout.write(f"Updated owner password {OWNER_EMAIL}")

        org, created_org = Organization.objects.update_or_create(
            cnpj=ORG_CNPJ,
            defaults={
                "name": ORG_NAME,
                "trade_name": ORG_TRADE,
                "owner": owner,
                "is_active": True,
            },
        )
        self.stdout.write(
            f"{'Created' if created_org else 'Updated'} org {org.trade_name or org.name}"
        )

        offices_spec = [
            {
                "ibge": IBGE_CUJUBIM,
                "name": "Escritorio Cujubim Stub",
                "address": "Rua Stub Principal 50, Cujubim/RO",
                "phone": "(69) 3000-0002",
                "referral": "REF-CUJ-STUB",
                "activate_owner": True,
            },
            {
                "ibge": IBGE_PORTO_VELHO,
                "name": "Escritorio Porto Velho Stub",
                "address": "Av. Stub Centro 200, Porto Velho/RO",
                "phone": "(69) 3000-0003",
                "referral": "REF-PVH-STUB",
                "activate_owner": False,
            },
        ]

        offices: dict[str, Office] = {}
        for spec in offices_spec:
            mun = munis[spec["ibge"]]
            office, _ = Office.objects.update_or_create(
                organization=org,
                municipality=mun,
                defaults={
                    "name": spec["name"],
                    "address": spec["address"],
                    "phone": spec["phone"],
                    "status": Office.Status.ACTIVE,
                    "referral_code": spec["referral"],
                    "technical_responsible_name": OWNER_FULL_NAME,
                    "technical_council_id": "CFTA-STUB-001",
                },
            )
            offices[spec["ibge"]] = office
            Membership.objects.update_or_create(
                user=owner,
                office=office,
                defaults={
                    "role": Membership.Role.OWNER,
                    "is_active": spec["activate_owner"],
                },
            )
            self.stdout.write(f"Office {office.name} ({mun.name})")

        # Drop leftover pilot offices (e.g. previous Ariquemes stub) from this org.
        Office.objects.filter(organization=org).exclude(
            municipality__ibge_code__in=list(munis.keys())
        ).delete()

        # Ensure exactly one active owner membership (Cujubim).
        Membership.objects.filter(user=owner, is_active=True).exclude(
            office=offices[IBGE_CUJUBIM]
        ).update(is_active=False)
        Membership.objects.filter(user=owner, office=offices[IBGE_CUJUBIM]).update(
            is_active=True
        )

        tech = User.objects.filter(email__iexact=TECH_EMAIL).first()
        if tech is None:
            first, *rest = TECH_FULL_NAME.split(" ", 1)
            tech = User.objects.create_user(
                username=TECH_EMAIL,
                email=TECH_EMAIL,
                password=TECH_PASSWORD,
                first_name=first[:150],
                last_name=(rest[0] if rest else "")[:150],
            )
            self.stdout.write(f"Created technician {TECH_EMAIL}")
        else:
            tech.set_password(TECH_PASSWORD)
            tech.save()
            self.stdout.write(f"Updated technician password {TECH_EMAIL}")

        cujubim = offices[IBGE_CUJUBIM]
        Membership.objects.update_or_create(
            user=tech,
            office=cujubim,
            defaults={
                "role": Membership.Role.TECHNICIAN,
                "is_active": True,
            },
        )
        Membership.objects.filter(user=tech, is_active=True).exclude(
            office=cujubim
        ).update(is_active=False)

        self.stdout.write(self.style.SUCCESS("Pilot seed ready."))
        self.stdout.write("")
        self.stdout.write("Login (owner, active office = Cujubim):")
        self.stdout.write(f"  {OWNER_EMAIL} / {OWNER_PASSWORD}")
        self.stdout.write("Login (technician, active office = Cujubim):")
        self.stdout.write(f"  {TECH_EMAIL} / {TECH_PASSWORD}")
        self.stdout.write(
            "Geofence: use GPS inside the seeded squares around Cujubim or Porto Velho."
        )

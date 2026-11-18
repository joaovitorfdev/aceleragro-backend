"""Root Django Ninja API — mounts domain routers."""

from __future__ import annotations

from ninja import NinjaAPI

from acelera_agro.accounts.api import router as accounts_router
from acelera_agro.activities.api import router as activities_router
from acelera_agro.catalog.api import router as catalog_router
from acelera_agro.documents.api import router as documents_router
from acelera_agro.extraction.api import router as extraction_router
from acelera_agro.proposals.api import router as proposals_router
from acelera_agro.proposals.forms_api import router as proposal_forms_router
from acelera_agro.tenants.api import router as tenants_router

api = NinjaAPI(
    title="Acelera Agro API",
    version="0.1.0",
    description="Rural credit proposal automation API",
)

api.add_router("", accounts_router)
api.add_router("", tenants_router)
api.add_router("", catalog_router)
# Literal paths (e.g. /proposals/drafts) must be registered before /proposals/{id}.
api.add_router("", proposal_forms_router)
api.add_router("", proposals_router)
api.add_router("", documents_router)
api.add_router("", extraction_router)
api.add_router("", activities_router)

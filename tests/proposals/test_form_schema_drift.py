"""The backend form schema must stay byte-identical to the frontend copy."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_SCHEMA = (
    REPO_ROOT / "backend/src/acelera_agro/proposals/form_schema/proposal_form.json"
)
FRONTEND_SCHEMA = REPO_ROOT / "frontend/src/lib/forms/proposal-form.schema.json"


def test_backend_and_frontend_form_schema_are_byte_identical():
    assert BACKEND_SCHEMA.is_file(), BACKEND_SCHEMA
    assert FRONTEND_SCHEMA.is_file(), FRONTEND_SCHEMA
    assert BACKEND_SCHEMA.read_bytes() == FRONTEND_SCHEMA.read_bytes(), (
        "proposal_form.json drifted from the frontend copy; keep both byte-identical"
    )

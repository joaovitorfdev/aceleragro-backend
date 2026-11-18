"""Proposal form contract: drafts, GET/PATCH form, locks, limits, tenancy, validation."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model

from acelera_agro.documents.models import Document
from acelera_agro.proposals import form_rules, form_state
from acelera_agro.proposals.models import ExistingDebt, Issue, Property, Proponent, Proposal
from acelera_agro.proposals.validation import validate_proposal
from acelera_agro.tenants.models import Membership, Office, Organization

User = get_user_model()
JSON = "application/json"


def _create_draft(client, key: str | None = None) -> dict:
    extra = {"HTTP_IDEMPOTENCY_KEY": key} if key else {}
    response = client.post("/api/proposals/drafts", data={}, content_type=JSON, **extra)
    assert response.status_code == 201, response.content
    return response.json()


def _patch(client, proposal_id: int, *changes: dict):
    return client.patch(
        f"/api/proposals/{proposal_id}/form",
        data=json.dumps({"changes": list(changes)}),
        content_type=JSON,
    )


def _presign(client, proposal_id: int, *filenames: str):
    response = client.post(
        "/api/documents/presign",
        data={
            "proposal_id": proposal_id,
            "files": [
                {"filename": f, "content_type": "application/pdf", "size": 100}
                for f in filenames
            ],
        },
        content_type=JSON,
    )
    assert response.status_code == 201, response.content
    return response.json()


def _read(client, proposal_id: int):
    response = client.post(f"/api/proposals/{proposal_id}/read-documents", content_type=JSON)
    assert response.status_code == 202, response.content
    return response.json()


def _get(client, proposal_id: int) -> dict:
    response = client.get(f"/api/proposals/{proposal_id}/form")
    assert response.status_code == 200, response.content
    return response.json()


# ----------------------------------------------------------------- schema + drafts


@pytest.mark.django_db
def test_schema_endpoint_serves_the_contract_file(form_client):
    response = form_client.get("/api/forms/proposal")
    assert response.status_code == 200
    assert response.content == form_rules.schema_bytes()
    assert response.json()["version"] == 1


@pytest.mark.django_db
def test_create_draft_without_proponent(form_client, office, organization, user):
    body = _create_draft(form_client)
    assert body["status"] == "draft"
    assert body["office_id"] == office.id
    assert body["organization_id"] == organization.id
    assert body["reading"] is False
    assert body["documents"] == []
    assert body["suggestions"] == {}
    assert body["values"]["properties"] == []
    assert body["values"]["debts"] == []
    # The only value of an empty draft is the schema default.
    assert body["values"]["proponent"] == {"person_type": "individual"}

    proposal = Proposal.all_objects.get(pk=body["id"])
    assert proposal.proponent_id is None
    assert proposal.property_id is None
    assert proposal.created_by_id == user.id
    assert proposal.office_id == office.id


@pytest.mark.django_db
def test_create_draft_honors_idempotency_key(form_client):
    first = _create_draft(form_client, key="draft-key-1")
    second = _create_draft(form_client, key="draft-key-1")
    assert first["id"] == second["id"]
    assert Proposal.all_objects.count() == 1


@pytest.mark.django_db
def test_presign_attaches_documents_to_draft_without_proponent(form_client):
    draft = _create_draft(form_client)
    body = _presign(form_client, draft["id"], "cpf.pdf")
    assert len(body["items"]) == 1
    form = _get(form_client, draft["id"])
    assert [d["status"] for d in form["documents"]] == ["queued"]
    assert form["reading"] is False  # uploaded, reading not requested yet


# ------------------------------------------------------------------- user edits


@pytest.mark.django_db
def test_patch_creates_rows_lazily_and_locks_values(form_client, municipality):
    draft = _create_draft(form_client)
    pid = draft["id"]
    response = _patch(
        form_client,
        pid,
        {"path": "proponent.full_name", "value": "  Produtor Teste 01 "},
        {"path": "properties.0.area_ha", "value": "120.5"},
        {"path": "properties.0.municipality", "value": municipality.ibge_code},
        {"path": "credit.financed_amount", "value": "1500.5"},
        {"path": "credit.term_years", "value": 8},
        {"path": "debts.0.annual_rate", "value": "0.055"},
        {"path": "review.technician_declaration", "value": True},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["values"]["proponent"]["full_name"] == "Produtor Teste 01"
    assert body["values"]["properties"][0]["area_ha"] == "120.5000"
    assert body["values"]["properties"][0]["municipality"] == municipality.ibge_code
    assert body["labels"]["properties.0.municipality"] == "Goiania Stub/GO"
    assert body["values"]["credit"]["financed_amount"] == "1500.50"
    assert body["values"]["credit"]["term_years"] == 8
    assert body["values"]["debts"][0]["annual_rate"] == "0.055000"
    assert body["values"]["review"] == {"technician_declaration": True}
    assert body["provenance"]["proponent.full_name"] == {"source": "user"}
    assert body["provenance"]["properties.0.area_ha"] == {"source": "user"}

    proposal = Proposal.all_objects.get(pk=pid)
    assert proposal.proponent.full_name == "Produtor Teste 01"
    first_property = Property.all_objects.get(proposal=proposal)
    assert proposal.property_id == first_property.id  # primary property for the engine
    assert first_property.proponent_id == proposal.proponent_id
    assert ExistingDebt.objects.filter(proposal=proposal).count() == 1


@pytest.mark.django_db
def test_properties_created_before_proponent_are_linked_when_it_appears(form_client):
    pid = _create_draft(form_client)["id"]
    _patch(form_client, pid, {"path": "properties.1.name", "value": "Fazenda Dois"})
    proposal = Proposal.all_objects.get(pk=pid)
    props = list(Property.all_objects.filter(proposal=proposal).order_by("id"))
    assert len(props) == 2  # index 1 creates index 0 as well
    assert all(p.proponent_id is None for p in props)
    assert props[1].name == "Fazenda Dois"
    assert proposal.property_id == props[0].id

    _patch(form_client, pid, {"path": "proponent.full_name", "value": "Produtor Teste 01"})
    proposal.refresh_from_db()
    assert all(
        p.proponent_id == proposal.proponent_id
        for p in Property.all_objects.filter(proposal=proposal)
    )


@pytest.mark.django_db
def test_patch_rejects_invalid_changes_atomically(form_client):
    pid = _create_draft(form_client)["id"]
    cases = [
        {"path": "nope.field", "value": "x"},
        {"path": "proponent.nope", "value": "x"},
        {"path": "proponent.0.full_name", "value": "x"},
        {"path": "properties.area_ha", "value": "1"},
        {"path": "credit.financed_amount", "value": 10.5},  # floats are not allowed
        {"path": "credit.financed_amount", "value": "abc"},
        {"path": "credit.credit_purpose", "value": "bogus"},
        {"path": "properties.0.municipality", "value": "0000000"},
        {"path": "review.technician_declaration", "value": "yes"},
    ]
    for case in cases:
        response = _patch(form_client, pid, {"path": "proponent.full_name", "value": "A"}, case)
        assert response.status_code == 422, (case, response.content)
        assert response.json()["code"]
    # Nothing leaked from the failed batches.
    assert Proposal.all_objects.get(pk=pid).proponent_id is None


@pytest.mark.django_db
def test_max_five_properties_and_seven_debts(form_client):
    pid = _create_draft(form_client)["id"]
    for i in range(5):
        assert _patch(form_client, pid, {"path": f"properties.{i}.name", "value": f"F{i}"}).status_code == 200
    over = _patch(form_client, pid, {"path": "properties.5.name", "value": "F5"})
    assert over.status_code == 422
    assert over.json()["code"] == "max_items_exceeded"

    for i in range(7):
        assert _patch(form_client, pid, {"path": f"debts.{i}.creditor", "value": f"C{i}"}).status_code == 200
    over = _patch(form_client, pid, {"path": "debts.7.creditor", "value": "C7"})
    assert over.status_code == 422
    assert over.json()["code"] == "max_items_exceeded"

    body = _get(form_client, pid)
    assert len(body["values"]["properties"]) == 5
    assert len(body["values"]["debts"]) == 7


@pytest.mark.django_db
def test_hidden_spouse_values_are_preserved_when_marital_status_changes(form_client):
    pid = _create_draft(form_client)["id"]
    _patch(
        form_client,
        pid,
        {"path": "proponent.marital_status", "value": "married"},
        {"path": "proponent.spouse_name", "value": "Conjuge Teste 01"},
        {"path": "proponent.spouse_document_number", "value": "000.000.000-01"},
    )
    body = _patch(form_client, pid, {"path": "proponent.marital_status", "value": "single"}).json()
    # Nothing is deleted: the spouse values survive while the block is hidden.
    assert body["values"]["proponent"]["spouse_name"] == "Conjuge Teste 01"
    assert body["values"]["proponent"]["spouse_document_number"] == "000.000.000-01"
    spouse = form_rules.get_field("proponent", "spouse_name")
    ctx = form_rules.RuleContext(body["values"], "proponent")
    assert not form_rules.is_visible(spouse, ctx)

    back = _patch(form_client, pid, {"path": "proponent.marital_status", "value": "stable_union"})
    assert back.json()["values"]["proponent"]["spouse_name"] == "Conjuge Teste 01"


@pytest.mark.django_db
def test_clearing_a_field_keeps_the_lock(form_client):
    pid = _create_draft(form_client)["id"]
    _patch(form_client, pid, {"path": "proponent.address", "value": "Rua Teste 1"})
    body = _patch(form_client, pid, {"path": "proponent.address", "value": None}).json()
    assert "address" not in body["values"]["proponent"]
    assert body["provenance"]["proponent.address"] == {"source": "user"}


# --------------------------------------------------------- reading + locks + status


@pytest.mark.django_db
def test_read_documents_autofills_a_draft_without_proponent(form_client, municipality):
    pid = _create_draft(form_client)["id"]
    _presign(form_client, pid, "cpf.pdf", "escritura.pdf", "foto_qualquer.pdf")
    body = _read(form_client, pid)

    assert body["reading"] is False  # synchronous under TESTING
    statuses = {d["filename"]: d["status"] for d in body["documents"]}
    assert statuses == {
        "cpf.pdf": "recognized",
        "escritura.pdf": "recognized",
        "foto_qualquer.pdf": "unrecognized",
    }
    values = body["values"]
    assert values["proponent"]["full_name"] == "Produtor Teste 01"
    assert values["proponent"]["document_number"] == "000.000.000-00"
    prop = values["properties"][0]
    assert prop["area_ha"] == "25.5000"
    assert prop["municipality"] == municipality.ibge_code
    assert prop["matricula"] == "M-100"
    assert prop["ownership_type"] == "registered_deed"

    prov = body["provenance"]["proponent.full_name"]
    assert prov["source"] == "document"
    assert prov["document_kind"] == "id_document" or prov["document_kind"] == "cpf"
    assert prov["confidence"] == "0.9200"
    assert body["suggestions"] == {}

    proposal = Proposal.all_objects.get(pk=pid)
    assert proposal.proponent.full_name == "Produtor Teste 01"
    assert proposal.property_id is not None


@pytest.mark.django_db
def test_user_edit_locks_field_against_later_document_reads(form_client):
    pid = _create_draft(form_client)["id"]
    _patch(form_client, pid, {"path": "proponent.full_name", "value": "Nome Digitado"})
    _presign(form_client, pid, "cpf.pdf")
    body = _read(form_client, pid)

    assert body["values"]["proponent"]["full_name"] == "Nome Digitado"
    assert body["provenance"]["proponent.full_name"] == {"source": "user"}
    # The document value is only offered as a suggestion; unlocked fields are filled.
    assert body["suggestions"]["proponent.full_name"]["value"] == "Produtor Teste 01"
    assert body["values"]["proponent"]["document_number"] == "000.000.000-00"

    # Accepting the suggestion is a normal user edit and clears it.
    accepted = _patch(
        form_client, pid, {"path": "proponent.full_name", "value": "Produtor Teste 01"}
    ).json()
    assert accepted["values"]["proponent"]["full_name"] == "Produtor Teste 01"
    assert "proponent.full_name" not in accepted["suggestions"]


@pytest.mark.django_db
def test_dismiss_suggestion(form_client):
    pid = _create_draft(form_client)["id"]
    _patch(form_client, pid, {"path": "proponent.full_name", "value": "Nome Digitado"})
    _presign(form_client, pid, "cpf.pdf")
    assert "proponent.full_name" in _read(form_client, pid)["suggestions"]
    body = _patch(form_client, pid, {"path": "proponent.full_name", "dismiss_suggestion": True})
    assert "proponent.full_name" not in body.json()["suggestions"]
    assert body.json()["values"]["proponent"]["full_name"] == "Nome Digitado"


@pytest.mark.django_db
def test_low_confidence_values_become_suggestions(form_client):
    pid = _create_draft(form_client)["id"]
    _presign(form_client, pid, "escritura_lowconf.pdf", "cpf.pdf")
    body = _read(form_client, pid)
    prop_values = body["values"]["properties"]
    # The deed is read at 0.60 < 0.85: nothing applied from it.
    assert prop_values == [] or "area_ha" not in prop_values[0]
    sug = body["suggestions"]["properties.0.area_ha"]
    assert sug["value"] == "25.5000"
    assert sug["confidence"] == "0.60"
    assert sug["document_kind"] == "public_deed"
    # The confident document still applied.
    assert body["values"]["proponent"]["full_name"] == "Produtor Teste 01"


@pytest.mark.django_db
def test_marriage_certificate_reveals_required_spouse_fields(form_client):
    pid = _create_draft(form_client)["id"]
    _patch(form_client, pid, {"path": "proponent.marital_status", "value": "single"})
    proposal = Proposal.all_objects.get(pk=pid)
    validate_proposal(proposal)
    paths = set(proposal.issues.filter(resolved_at__isnull=True).values_list("field_path", flat=True))
    assert "proponent.spouse_name" not in paths  # hidden while single

    # Married but spouse still empty -> required + missing.
    _patch(form_client, pid, {"path": "proponent.marital_status", "value": "married"})
    proposal.refresh_from_db()
    validate_proposal(proposal)
    issues = proposal.issues.filter(resolved_at__isnull=True)
    spouse_issue = issues.get(field_path="proponent.spouse_name")
    assert spouse_issue.code == "field_required"
    assert spouse_issue.severity == Issue.Severity.ERROR

    # Fresh draft: the marriage certificate itself reveals + fills the spouse block.
    other = _create_draft(form_client)["id"]
    _presign(form_client, other, "casamento.pdf")
    body = _read(form_client, other)
    proponent = body["values"]["proponent"]
    assert proponent["marital_status"] == "married"
    assert proponent["spouse_name"] == "Conjuge Teste 01"
    spouse = form_rules.get_field("proponent", "spouse_name")
    ctx = form_rules.RuleContext(body["values"], "proponent")
    assert form_rules.is_visible(spouse, ctx) and form_rules.is_required(spouse, ctx)


@pytest.mark.django_db
def test_union_declaration_maps_partner_to_spouse(form_client):
    pid = _create_draft(form_client)["id"]
    _presign(form_client, pid, "uniao.pdf")
    proponent = _read(form_client, pid)["values"]["proponent"]
    assert proponent["marital_status"] == "stable_union"
    assert proponent["spouse_name"] == "Conjuge Teste 01"


@pytest.mark.django_db
def test_unrecognized_document_can_be_labelled_and_read(form_client):
    pid = _create_draft(form_client)["id"]
    doc_id = _presign(form_client, pid, "foto_qualquer.pdf")["items"][0]["document_id"]
    body = _read(form_client, pid)
    assert body["documents"][0]["status"] == "unrecognized"

    labelled = form_client.patch(
        f"/api/documents/{doc_id}",
        data={"user_override_kind": "cpf"},
        content_type=JSON,
    )
    assert labelled.status_code == 200, labelled.content
    body = _read(form_client, pid)
    assert body["documents"][0]["status"] == "recognized"
    assert body["documents"][0]["detected_kind"] == "cpf"
    assert body["values"]["proponent"]["document_number"] == "000.000.000-00"


@pytest.mark.django_db
def test_reading_flag_and_failed_status(form_client):
    pid = _create_draft(form_client)["id"]
    doc_id = _presign(form_client, pid, "cpf.pdf")["items"][0]["document_id"]
    Document.all_objects.filter(pk=doc_id).update(extraction_status="reading")
    body = _get(form_client, pid)
    assert body["reading"] is True
    assert body["documents"][0]["status"] == "reading"

    Document.all_objects.filter(pk=doc_id).update(extraction_status="failed")
    body = _get(form_client, pid)
    assert body["reading"] is False
    assert body["documents"][0]["status"] == "failed"


@pytest.mark.django_db
def test_provider_errors_mark_document_failed(form_client, monkeypatch):
    from acelera_agro.extraction import services

    class Boom:
        def classify(self, document):
            raise RuntimeError("provider down")

    monkeypatch.setattr(services, "get_extraction_provider", lambda: Boom())
    pid = _create_draft(form_client)["id"]
    _presign(form_client, pid, "cpf.pdf")
    body = _read(form_client, pid)
    assert body["documents"][0]["status"] == "failed"
    assert body["reading"] is False


# ------------------------------------------------------------- RBAC + tenancy


@pytest.fixture
def other_office_client(client_factory, municipality):
    other_org = Organization.objects.create(name="Org Outra Stub")
    other_office = Office.objects.create(
        organization=other_org,
        municipality=municipality,
        name="Escritorio Outro",
        referral_code="REF-OTHER-01",
    )
    other_user = User.objects.create_user(
        username="other@example.com", email="other@example.com", password="test-password-123"
    )
    Membership.objects.create(
        user=other_user, office=other_office, role=Membership.Role.TECHNICIAN, is_active=True
    )
    return client_factory("other@example.com", fingerprint="fp-other")


@pytest.mark.django_db
def test_other_office_cannot_read_or_patch_the_form(form_client, other_office_client):
    pid = _create_draft(form_client)["id"]
    _patch(form_client, pid, {"path": "proponent.full_name", "value": "Produtor Teste 01"})

    assert other_office_client.get(f"/api/proposals/{pid}/form").status_code == 404
    denied = _patch(other_office_client, pid, {"path": "proponent.full_name", "value": "Hack"})
    assert denied.status_code == 404
    assert (
        other_office_client.post(
            f"/api/proposals/{pid}/read-documents", content_type=JSON
        ).status_code
        == 404
    )
    assert Proponent.all_objects.get(proposals__pk=pid).full_name == "Produtor Teste 01"


@pytest.mark.django_db
def test_viewer_can_read_but_not_mutate(form_client, client_factory, office, membership):
    pid = _create_draft(form_client)["id"]
    viewer = User.objects.create_user(
        username="viewer@example.com", email="viewer@example.com", password="test-password-123"
    )
    # One active membership per user: the viewer is a separate user of the same office.
    Membership.objects.create(user=viewer, office=office, role=Membership.Role.VIEWER, is_active=True)
    viewer_client = client_factory("viewer@example.com", fingerprint="fp-viewer")

    assert viewer_client.get(f"/api/proposals/{pid}/form").status_code == 200
    assert viewer_client.get("/api/forms/proposal").status_code == 200
    assert _patch(viewer_client, pid, {"path": "proponent.full_name", "value": "x"}).status_code == 403
    assert viewer_client.post("/api/proposals/drafts", data={}, content_type=JSON).status_code == 403
    assert (
        viewer_client.post(f"/api/proposals/{pid}/read-documents", content_type=JSON).status_code
        == 403
    )


@pytest.mark.django_db
def test_suspended_office_is_read_only(form_client, office):
    pid = _create_draft(form_client)["id"]
    office.status = Office.Status.SUSPENDED
    office.save(update_fields=["status"])
    assert form_client.get(f"/api/proposals/{pid}/form").status_code == 200
    assert _patch(form_client, pid, {"path": "proponent.full_name", "value": "x"}).status_code == 403
    assert form_client.post("/api/proposals/drafts", data={}, content_type=JSON).status_code == 403


@pytest.mark.django_db
def test_submitted_proposal_form_is_not_editable(form_client):
    pid = _create_draft(form_client)["id"]
    Proposal.all_objects.filter(pk=pid).update(status=Proposal.Status.SUBMITTED)
    assert _patch(form_client, pid, {"path": "proponent.full_name", "value": "x"}).status_code == 409


# --------------------------------------------------------------------- validation


@pytest.mark.django_db
def test_validation_emits_issues_for_empty_draft_instead_of_crashing(form_client):
    pid = _create_draft(form_client)["id"]
    proposal = Proposal.all_objects.get(pk=pid)
    validate_proposal(proposal)
    issues = {i.field_path: i for i in proposal.issues.filter(resolved_at__isnull=True)}
    assert issues["proponent"].code == "missing_proponent"
    assert issues["proponent.full_name"].code == "field_required"
    assert issues["proponent.marital_status"].code == "field_required"
    assert issues["credit.credit_purpose"].code == "field_required"
    assert issues["credit.financed_amount"].code == "missing_financed_amount"
    assert issues["review.technician_declaration"].code == "field_required"
    assert "proponent.spouse_name" not in issues
    assert "credit.grace_years" not in issues  # hidden until purpose = investment

    # The legacy calculate endpoint tolerates drafts as well.
    response = form_client.post(f"/api/proposals/{pid}/calculate", content_type=JSON)
    assert response.status_code == 200, response.content
    assert response.json()["proponent_id"] is None


@pytest.mark.django_db
def test_validation_repeatable_item_paths(form_client):
    pid = _create_draft(form_client)["id"]
    _patch(
        form_client,
        pid,
        {"path": "properties.0.ownership_type", "value": "lease"},
        {"path": "properties.1.ownership_type", "value": "registered_deed"},
    )
    proposal = Proposal.all_objects.get(pk=pid)
    validate_proposal(proposal)
    paths = set(proposal.issues.filter(resolved_at__isnull=True).values_list("field_path", flat=True))
    assert "properties.0.lease_owner_name" in paths
    assert "properties.1.lease_owner_name" not in paths
    assert "properties.1.area_ha" in paths
    assert form_state.build_values(proposal)["properties"][0]["ownership_type"] == "lease"

"""Autofill rules of docs/form-contract.md (locks, confidence, declarations, conflicts)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from acelera_agro.documents.models import Document
from acelera_agro.extraction import services
from acelera_agro.extraction.services import apply_autofill, autofill_document
from acelera_agro.proposals import form_rules, form_state
from acelera_agro.proposals.models import ExistingDebt, Property, Proponent, Proposal


@pytest.fixture
def draft(office, organization):
    return Proposal.all_objects.create(office=office, organization=organization)


def _entry(confidence: str = "0.92", doc_id: int = 1, kind: str = "cpf") -> dict:
    return {"document_id": doc_id, "document_kind": kind, "confidence": confidence}


def _value(proposal: Proposal, path: str):
    proposal.refresh_from_db()
    return form_state.read_value(proposal, form_state.parse_path(path))


@pytest.mark.django_db
def test_first_value_creates_proponent_and_property_lazily(draft):
    assert draft.proponent_id is None
    assert apply_autofill(draft, "proponent.full_name", "Produtor Teste 01", _entry()) == "applied"
    draft.refresh_from_db()
    assert draft.proponent.full_name == "Produtor Teste 01"
    assert draft.proponent.field_provenance["full_name"]["source"] == "document"

    assert Property.all_objects.filter(proposal=draft).count() == 0
    assert apply_autofill(draft, "properties.0.area_ha", Decimal("25.5"), _entry()) == "applied"
    draft.refresh_from_db()
    prop = Property.all_objects.get(proposal=draft)
    assert prop.area_ha == Decimal("25.5000")
    assert prop.proponent_id == draft.proponent_id
    assert draft.property_id == prop.id
    assert draft.form_provenance["properties.0.area_ha"]["document_id"] == 1


@pytest.mark.django_db
def test_property_before_proponent_then_proponent_adopts_it(draft):
    apply_autofill(draft, "properties.0.matricula", "M-100", _entry())
    prop = Property.all_objects.get(proposal=draft)
    assert prop.proponent_id is None
    apply_autofill(draft, "proponent.full_name", "Produtor Teste 01", _entry())
    prop.refresh_from_db()
    assert prop.proponent_id == Proponent.all_objects.get().id


@pytest.mark.django_db
def test_min_confidence_default_and_per_field_override(draft, monkeypatch):
    assert apply_autofill(draft, "proponent.address", "Rua A", _entry("0.84")) == "suggested"
    assert draft.proponent_id is None  # a suggestion never creates rows
    assert draft.form_suggestions["proponent.address"] == {
        "value": "Rua A",
        "document_id": 1,
        "document_kind": "cpf",
        "confidence": "0.84",
    }
    assert apply_autofill(draft, "proponent.address", "Rua A", _entry("0.85")) == "applied"
    assert "proponent.address" not in draft.form_suggestions  # applied value clears it

    field = form_rules.get_field("proponent", "email")
    monkeypatch.setitem(field, "autofill_min_confidence", "0.99")
    assert apply_autofill(draft, "proponent.email", "a@example.com", _entry("0.95")) == "suggested"
    monkeypatch.setitem(field, "autofill_min_confidence", "0.50")
    assert apply_autofill(draft, "proponent.email", "a@example.com", _entry("0.60")) == "applied"


@pytest.mark.django_db
def test_user_lock_is_never_overwritten_only_suggested(draft):
    form_state.apply_user_changes(draft, [{"path": "proponent.full_name", "value": "Manual"}])
    assert apply_autofill(draft, "proponent.full_name", "Produtor Teste 01", _entry("0.99")) == (
        "suggested"
    )
    assert _value(draft, "proponent.full_name") == "Manual"
    assert draft.form_provenance["proponent.full_name"] == {"source": "user"}
    # Same value as the user's: nothing to say.
    assert apply_autofill(draft, "proponent.full_name", "Manual", _entry("0.99")) == "skipped"


@pytest.mark.django_db
def test_declaration_fields_are_never_autofilled(draft):
    field = form_rules.get_field("review", "technician_declaration")
    assert field["declaration"] is True
    assert apply_autofill(draft, "review.technician_declaration", True, _entry("1.0")) == "skipped"
    draft.refresh_from_db()
    assert draft.form_suggestions == {}
    assert draft.form_extra == {}
    assert "technician_declaration" not in form_state.build_values(draft)["review"]

    # Also through a whole document read.
    doc = Document.all_objects.create(
        office=draft.office, proposal=draft, s3_key="k", original_filename="cpf.pdf"
    )
    autofill_document(draft, doc, {"technician_declaration": True, "full_name": "Produtor Teste 01"})
    assert "technician_declaration" not in form_state.build_values(draft)["review"]


@pytest.mark.django_db
def test_conflict_higher_confidence_wins_and_loser_is_suggested(draft):
    apply_autofill(draft, "proponent.full_name", "Produtor Teste 01", _entry("0.90", doc_id=1))
    result = apply_autofill(
        draft, "proponent.full_name", "Produtor Teste 02", _entry("0.95", doc_id=2, kind="id_document")
    )
    assert result == "applied"
    assert _value(draft, "proponent.full_name") == "Produtor Teste 02"
    assert draft.form_provenance["proponent.full_name"]["document_id"] == 2
    displaced = draft.form_suggestions["proponent.full_name"]
    assert displaced["value"] == "Produtor Teste 01"
    assert displaced["document_id"] == 1


@pytest.mark.django_db
def test_conflict_lower_or_equal_confidence_is_only_suggested(draft):
    apply_autofill(draft, "proponent.full_name", "Produtor Teste 01", _entry("0.95", doc_id=1))
    for conf in ("0.90", "0.95"):
        assert (
            apply_autofill(draft, "proponent.full_name", "Produtor Teste 02", _entry(conf, doc_id=2))
            == "suggested"
        )
    assert _value(draft, "proponent.full_name") == "Produtor Teste 01"
    assert draft.form_suggestions["proponent.full_name"]["value"] == "Produtor Teste 02"
    # A weaker later candidate does not displace the stronger pending suggestion.
    apply_autofill(draft, "proponent.full_name", "Produtor Teste 03", _entry("0.88", doc_id=3))
    assert draft.form_suggestions["proponent.full_name"]["value"] == "Produtor Teste 02"


@pytest.mark.django_db
def test_legacy_value_without_provenance_is_protected(draft, organization):
    proponent = Proponent.all_objects.create(organization=organization, full_name="Legado")
    draft.proponent = proponent
    draft.save(update_fields=["proponent"])
    assert apply_autofill(draft, "proponent.full_name", "Produtor Teste 01", _entry()) == "suggested"
    proponent.refresh_from_db()
    assert proponent.full_name == "Legado"


@pytest.mark.django_db
def test_invalid_values_are_skipped(draft):
    assert apply_autofill(draft, "properties.0.municipality", "0000000", _entry()) == "skipped"
    assert apply_autofill(draft, "properties.9.area_ha", "1", _entry()) == "skipped"
    assert apply_autofill(draft, "proponent.unknown", "x", _entry()) == "skipped"
    assert apply_autofill(draft, "credit.activity_kind", "spaceship", _entry()) == "skipped"
    assert apply_autofill(draft, "proponent.full_name", None, _entry()) == "skipped"
    assert draft.proponent_id is None


@pytest.mark.django_db
def test_municipality_resolves_by_code_or_name(draft, municipality):
    assert apply_autofill(draft, "properties.0.municipality", "goiania stub", _entry()) == "applied"
    prop = Property.all_objects.get(proposal=draft)
    assert prop.municipality_id == municipality.id


@pytest.mark.django_db
def test_hidden_fields_still_receive_values(draft):
    # `matricula` is hidden for leases, but autofill never deletes/blocks hidden values.
    form_state.apply_user_changes(draft, [{"path": "properties.0.ownership_type", "value": "lease"}])
    assert apply_autofill(draft, "properties.0.matricula", "M-1", _entry()) == "applied"
    assert _value(draft, "properties.0.matricula") == "M-1"


@pytest.mark.django_db
def test_debt_statement_fills_debt_rows(draft):
    doc = Document.all_objects.create(
        office=draft.office, proposal=draft, s3_key="k", original_filename="divida.pdf",
        detected_kind="debt_statement", detected_kind_confidence=Decimal("0.9200"),
    )
    fields = {"creditor": "Banco Teste", "outstanding_balance": "1000.00", "annual_rate": "0.055"}
    autofill_document(draft, doc, fields)
    autofill_document(draft, doc, fields)  # re-reading must not duplicate the row
    debts = list(ExistingDebt.objects.filter(proposal=draft))
    assert len(debts) == 1
    assert debts[0].creditor == "Banco Teste"
    assert debts[0].outstanding_balance == Decimal("1000.00")
    assert debts[0].annual_rate == Decimal("0.055000")


@pytest.mark.django_db
def test_ownership_derived_from_kinds_only_when_unset(draft, municipality):
    apply_autofill(draft, "properties.0.name", "Fazenda Teste", _entry())
    services._derive_ownership(draft, {"public_deed"})
    assert _value(draft, "properties.0.ownership_type") == "registered_deed"
    assert draft.form_provenance["properties.0.ownership_type"]["source"] == "derived"

    # A user choice is never replaced.
    form_state.apply_user_changes(
        draft, [{"path": "properties.0.ownership_type", "value": "lease"}]
    )
    services._derive_ownership(draft, {"public_deed"})
    assert _value(draft, "properties.0.ownership_type") == "lease"


@pytest.mark.django_db
def test_derived_value_can_be_replaced_by_a_document_value(draft):
    apply_autofill(draft, "properties.0.name", "Fazenda Teste", _entry())
    services._derive_ownership(draft, {"purchase_sale_contract"})
    assert (
        apply_autofill(draft, "properties.0.ownership_type", "registered_deed", _entry())
        == "applied"
    )
    assert _value(draft, "properties.0.ownership_type") == "registered_deed"


# ------------------------------------------------------------ background reading


@pytest.mark.django_db
def test_background_thread_path_queues_then_processes(
    draft, settings, monkeypatch, django_capture_on_commit_callbacks
):
    settings.TESTING = False
    started: list[tuple] = []
    closed: list[bool] = []

    class InlineThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args
            assert daemon is True

        def start(self):
            started.append(self.args)
            self.target(*self.args)

    class FakeConnections:
        def close_all(self):
            closed.append(True)

    monkeypatch.setattr(services.threading, "Thread", InlineThread)
    monkeypatch.setattr(services, "connections", FakeConnections())
    monkeypatch.setattr(services, "close_old_connections", lambda: None)

    doc = Document.all_objects.create(
        office=draft.office, proposal=draft, s3_key="k", original_filename="cpf.pdf"
    )
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        ids = services.start_reading(draft)
    assert ids == [doc.id]
    doc.refresh_from_db()
    assert doc.extraction_status == "queued"
    assert form_state.is_reading(draft) is True
    assert started == []  # thread starts only after commit

    for callback in callbacks:
        callback()
    doc.refresh_from_db()
    assert doc.extraction_status == "extracted"
    assert form_state.document_status(doc) == "recognized"
    assert form_state.is_reading(draft) is False
    assert closed == [True]  # DB connections released at the end of the thread
    assert _value(draft, "proponent.full_name") == "Produtor Teste 01"


@pytest.mark.django_db
def test_stale_queued_documents_are_requeued(draft):
    from datetime import timedelta

    from django.utils import timezone

    doc = Document.all_objects.create(
        office=draft.office, proposal=draft, s3_key="k", original_filename="cpf.pdf",
        extraction_status="reading",
    )
    assert services.queue_documents(draft) == []  # fresh: owned by a live worker
    Document.all_objects.filter(pk=doc.pk).update(
        updated_at=timezone.now() - timedelta(minutes=30)
    )
    assert services.queue_documents(draft) == [doc.id]

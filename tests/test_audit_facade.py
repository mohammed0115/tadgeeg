"""One entry point for auditing a document, and the two silent failures it closes.

`AuditPipelineV2.run()` takes a document id, a document type and an
organisation id. The Document row already knows the last two, so every caller
either looks them up or threads them through a Celery signature. Both mistakes
that follow are silent:

  · a wrong `document_type` audits the file against another type's rules and
    returns a complete, confident, wrong result — the run finishes, the score
    is real, the rules were the wrong ones
  · a caller with a Document but no organisation reaches for
    `request.user.organization`, which is not necessarily the document's owner

The facade derives both from the row, which makes them unrepresentable rather
than discouraged. Most of what follows tests exactly that.
"""

from unittest import mock

import pytest

from apps.rule_engine.services.audit_facade import (
    AuditFacade,
    AuditFacadeError,
    AuditRunResult,
)


@pytest.fixture
def document(db, organization, admin_user):
    from apps.documents.models import Document

    return Document.objects.create(
        organization=organization, uploaded_by=admin_user,
        original_filename="invoice.pdf", file="", file_size=1024,
        mime_type="application/pdf",
        document_type=Document.DocumentType.INVOICE,
    )


@pytest.fixture
def fake_run():
    """An AuditRun-shaped object — the facade must not need a real pipeline."""
    run = mock.Mock()
    run.id = "11111111-1111-1111-1111-111111111111"
    run.status = "completed"
    run.risk_score = 42.5
    run.risk_level = "medium"
    run.total_rules = 30
    run.failed_rules = 2
    run.warning_rules = 1
    return run


def _patched_pipeline(fake_run):
    return mock.patch(
        "apps.rule_engine.pipeline.v2.pipeline.AuditPipelineV2.run",
        return_value=fake_run,
    )


# ── The type and tenant come from the row ────────────────────────────────────

@pytest.mark.django_db
def test_the_document_type_is_read_from_the_row_not_the_caller(document, fake_run):
    """A caller cannot pass the wrong type, because it cannot pass one at all."""
    with _patched_pipeline(fake_run) as run:
        AuditFacade.process_document(document.pk)

    assert run.call_args.kwargs["document_type"] == document.document_type


@pytest.mark.django_db
def test_the_organisation_is_read_from_the_document_not_the_request(document, fake_run):
    """The document's owner, never the caller's organisation. Those differ
    exactly once, and that once is a cross-tenant audit."""
    with _patched_pipeline(fake_run) as run:
        AuditFacade.process_document(document.pk)

    assert run.call_args.kwargs["organization_id"] == str(document.organization_id)


@pytest.mark.django_db
def test_the_facade_signature_accepts_no_type_or_organisation():
    """If either can be passed, it can be passed wrongly."""
    import inspect

    params = inspect.signature(AuditFacade.process_document).parameters
    assert "document_type" not in params
    assert "organization_id" not in params


# ── Refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_missing_document_is_refused_with_a_readable_reason():
    result = AuditFacade.process_document("99999999-9999-9999-9999-999999999999")

    assert result.ok is False
    assert "No document" in result.error
    assert result.audit_run_id is None


@pytest.mark.django_db
def test_a_document_with_no_organisation_is_refused(document):
    """An audit with no tenant has nowhere to write findings and no quota.

    The database will not let this row exist — `Document.organization` is NOT
    NULL, which is the stronger guarantee and worth knowing. The facade check
    stays for two cases the constraint does not cover: an unsaved instance,
    and a `.only()`/`.defer()` queryset where the attribute is present and the
    id is not. Simulated here rather than persisted, because the point is the
    facade's behaviour, not the column's.
    """
    from apps.documents.models import Document

    orphan = Document(
        pk=document.pk, organization=None, original_filename="x.pdf",
        document_type=Document.DocumentType.INVOICE,
    )

    with mock.patch.object(Document.objects, "select_related") as select:
        select.return_value.filter.return_value.first.return_value = orphan
        result = AuditFacade.process_document(document.pk)

    assert result.ok is False
    assert "no organization" in result.error.lower()


@pytest.mark.django_db
def test_the_database_itself_refuses_a_document_without_an_organisation(db, admin_user):
    """The constraint behind the facade check — asserted so a future migration
    that relaxes it cannot pass unnoticed."""
    from django.db.utils import IntegrityError

    from apps.documents.models import Document

    with pytest.raises(IntegrityError):
        Document.objects.create(
            organization=None, uploaded_by=admin_user, original_filename="x.pdf",
            file="", file_size=1, mime_type="application/pdf",
            document_type=Document.DocumentType.INVOICE,
        )


@pytest.mark.django_db
def test_a_document_with_no_type_is_refused_rather_than_guessed(document):
    """Auditing it would apply whichever ruleset happened to be default."""
    document.document_type = ""
    document.save(update_fields=["document_type"])

    result = AuditFacade.process_document(document.pk)

    assert result.ok is False
    assert "document_type" in result.error


# ── Failure is returned, not raised ──────────────────────────────────────────

@pytest.mark.django_db
def test_a_pipeline_crash_becomes_a_result_not_an_exception(document):
    """A Celery task, a view and a command all need the same answer to "did it
    work"; three separate except blocks around one pipeline is how three
    behaviours drift apart."""
    with mock.patch(
        "apps.rule_engine.pipeline.v2.pipeline.AuditPipelineV2.run",
        side_effect=RuntimeError("stage exploded"),
    ):
        result = AuditFacade.process_document(document.pk)

    assert isinstance(result, AuditRunResult)
    assert result.ok is False
    assert "RuntimeError" in result.error


@pytest.mark.django_db
def test_the_crash_detail_does_not_reach_the_caller_verbatim(document):
    """The exception text can name internals; the type alone is enough for a
    user, and the traceback goes to the log."""
    with mock.patch(
        "apps.rule_engine.pipeline.v2.pipeline.AuditPipelineV2.run",
        side_effect=RuntimeError("connection to 10.0.0.5:5432 refused"),
    ):
        result = AuditFacade.process_document(document.pk)

    assert "10.0.0.5" not in result.error


@pytest.mark.django_db
def test_run_or_raise_lets_the_exception_out(document):
    """For a Celery task that wants its retry machinery to see the failure."""
    with mock.patch(
        "apps.rule_engine.pipeline.v2.pipeline.AuditPipelineV2.run",
        side_effect=RuntimeError("stage exploded"),
    ):
        with pytest.raises(RuntimeError):
            AuditFacade.run_or_raise(document.pk)


@pytest.mark.django_db
def test_run_or_raise_still_refuses_bad_input_with_the_facade_error():
    with pytest.raises(AuditFacadeError, match="No document"):
        AuditFacade.run_or_raise("99999999-9999-9999-9999-999999999999")


# ── The result object ────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_the_result_carries_what_a_caller_needs(document, fake_run):
    with _patched_pipeline(fake_run):
        result = AuditFacade.process_document(document.pk)

    assert result.ok is True
    assert result.risk_score == 42.5
    assert result.failed_rules == 2
    assert result.status == "completed"


@pytest.mark.django_db
def test_a_clean_audit_and_a_crashed_one_are_distinguishable(document, fake_run):
    """Both have zero failures if you only count findings. Collapsing them is
    how an outage reads as a pass."""
    fake_run.failed_rules = 0
    fake_run.warning_rules = 0
    with _patched_pipeline(fake_run):
        clean = AuditFacade.process_document(document.pk)

    with mock.patch(
        "apps.rule_engine.pipeline.v2.pipeline.AuditPipelineV2.run",
        side_effect=RuntimeError("boom"),
    ):
        crashed = AuditFacade.process_document(document.pk)

    assert clean.ok and not clean.needs_attention
    assert not crashed.ok and not crashed.needs_attention
    assert clean.ok != crashed.ok, "the only field that separates them"


@pytest.mark.django_db
def test_the_result_is_immutable(document, fake_run):
    """A result callers can edit stops being a record of what happened."""
    with _patched_pipeline(fake_run):
        result = AuditFacade.process_document(document.pk)

    with pytest.raises(Exception):
        result.ok = False


@pytest.mark.django_db
def test_the_facade_does_not_hand_back_the_model(document, fake_run):
    """A caller holding an AuditRun can save it, mutate it, or follow a
    relation the facade never meant to expose — and then it is not a boundary."""
    with _patched_pipeline(fake_run):
        result = AuditFacade.process_document(document.pk)

    assert not hasattr(result, "_meta")
    assert isinstance(result.audit_run_id, str)


# ── Pass-through of the pipeline's own options ───────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("trigger", ["upload", "manual", "scheduled", "reprocess"])
def test_the_trigger_reaches_the_pipeline(document, fake_run, trigger):
    with _patched_pipeline(fake_run) as run:
        AuditFacade.process_document(document.pk, triggered_by=trigger)

    assert run.call_args.kwargs["triggered_by"] == trigger


@pytest.mark.django_db
def test_force_rerun_and_dry_run_reach_the_pipeline(document, fake_run):
    with _patched_pipeline(fake_run) as run:
        AuditFacade.process_document(document.pk, force_rerun=True, dry_run=True)

    assert run.call_args.kwargs["force_rerun"] is True
    assert run.call_args.kwargs["dry_run"] is True

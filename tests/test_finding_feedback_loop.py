"""The feedback loop: does the engine ever find out it was wrong?

Before this, no. A rule fired, an auditor disagreed, and the disagreement went
nowhere — `status="ignored"` was the only place to put it, and that field
already meant "correct, but we accept it". So every accepted risk looked
identical to every engine error, and any precision computed from it could only
fall. That is the reason the 98% accuracy claim had nothing behind it.

The tests here are mostly about the ways this data can be made to lie:
unreviewed findings counted as correct, one tenant's verdicts polluting
another's, precision reported without the sample size behind it.
"""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditFinding
from apps.audit.services.finding_feedback import FeedbackError, FindingFeedbackService


@pytest.fixture
def service():
    return FindingFeedbackService()


@pytest.fixture
def finding_factory(db, organization, admin_user):
    def _make(rule_code="DUP-001", rule_name="Duplicate invoice", **kwargs):
        return AuditFinding.objects.create(
            organization=kwargs.pop("organization", organization),
            rule_code=rule_code,
            rule_name=rule_name,
            message="Possible duplicate of INV-118",
            **kwargs,
        )
    return _make


# ── The axis that was missing ────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_new_finding_is_unreviewed_not_assumed_correct(finding_factory):
    assert finding_factory().verdict == AuditFinding.Verdict.UNREVIEWED


@pytest.mark.django_db
def test_verdict_and_workflow_status_are_independent(service, finding_factory, admin_user):
    """A correct finding can still be ignored; that is not an engine error."""
    finding = finding_factory(status=AuditFinding.Status.IGNORED)
    service.record_verdict(finding=finding, user=admin_user,
                           verdict=AuditFinding.Verdict.TRUE_POSITIVE)

    finding.refresh_from_db()
    assert finding.status == AuditFinding.Status.IGNORED
    assert finding.verdict == AuditFinding.Verdict.TRUE_POSITIVE


@pytest.mark.django_db
def test_a_verdict_records_who_and_when(service, finding_factory, admin_user):
    before = timezone.now()
    finding = service.record_verdict(
        finding=finding_factory(), user=admin_user,
        verdict=AuditFinding.Verdict.TRUE_POSITIVE,
    )
    assert finding.verdict_by == admin_user
    assert finding.verdict_at >= before


# ── Refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_false_positive_must_say_why(service, finding_factory, admin_user):
    """Without a reason, nobody can act on it — the rule stays broken."""
    with pytest.raises(FeedbackError, match="reason"):
        service.record_verdict(finding=finding_factory(), user=admin_user,
                               verdict=AuditFinding.Verdict.FALSE_POSITIVE)


@pytest.mark.django_db
def test_a_false_positive_with_a_reason_is_accepted(service, finding_factory, admin_user):
    finding = service.record_verdict(
        finding=finding_factory(), user=admin_user,
        verdict=AuditFinding.Verdict.FALSE_POSITIVE,
        note="Different supplier, same amount by coincidence.",
    )
    assert finding.verdict == AuditFinding.Verdict.FALSE_POSITIVE
    assert "coincidence" in finding.verdict_note


@pytest.mark.django_db
def test_unreviewed_cannot_be_recorded_as_a_judgement(service, finding_factory, admin_user):
    with pytest.raises(FeedbackError):
        service.record_verdict(finding=finding_factory(), user=admin_user,
                               verdict=AuditFinding.Verdict.UNREVIEWED)


@pytest.mark.django_db
def test_an_unknown_verdict_is_refused(service, finding_factory, admin_user):
    with pytest.raises(FeedbackError, match="Unknown verdict"):
        service.record_verdict(finding=finding_factory(), user=admin_user, verdict="probably")


# ── Tenant isolation ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_user_cannot_judge_another_tenants_finding(service, finding_factory, admin_user):
    """A foreign verdict would corrupt that tenant's measured precision."""
    from apps.authentication.models import Organization

    other = Organization.objects.create(name="Other", name_ar="أخرى")
    foreign = finding_factory(organization=other)

    with pytest.raises(FeedbackError, match="another organization"):
        service.record_verdict(finding=foreign, user=admin_user,
                               verdict=AuditFinding.Verdict.TRUE_POSITIVE)

    foreign.refresh_from_db()
    assert foreign.verdict == AuditFinding.Verdict.UNREVIEWED


@pytest.mark.django_db
def test_precision_counts_only_the_callers_organisation(service, finding_factory, admin_user, organization):
    from apps.authentication.models import Organization

    other = Organization.objects.create(name="Other", name_ar="أخرى")
    finding_factory(verdict=AuditFinding.Verdict.FALSE_POSITIVE, organization=other)
    service.record_verdict(finding=finding_factory(), user=admin_user,
                           verdict=AuditFinding.Verdict.TRUE_POSITIVE)

    rows = service.rule_precision(organization)
    assert len(rows) == 1
    assert rows[0]["precision"] == 1.0
    assert rows[0]["false_positives"] == 0


# ── Precision arithmetic, and the ways it can lie ────────────────────────────

@pytest.mark.django_db
def test_precision_is_true_positives_over_judged(service, finding_factory, admin_user, organization):
    for _ in range(3):
        service.record_verdict(finding=finding_factory(), user=admin_user,
                               verdict=AuditFinding.Verdict.TRUE_POSITIVE)
    service.record_verdict(finding=finding_factory(), user=admin_user,
                           verdict=AuditFinding.Verdict.FALSE_POSITIVE, note="misfire")

    row = service.rule_precision(organization)[0]
    assert row["precision"] == 0.75
    assert row["judged"] == 4


@pytest.mark.django_db
def test_unreviewed_findings_do_not_count_as_correct(service, finding_factory, admin_user, organization):
    """Counting "nobody looked" as a success is how 99% accuracy gets claimed."""
    service.record_verdict(finding=finding_factory(), user=admin_user,
                           verdict=AuditFinding.Verdict.FALSE_POSITIVE, note="misfire")
    for _ in range(50):
        finding_factory()

    row = service.rule_precision(organization)[0]
    assert row["precision"] == 0.0
    assert row["judged"] == 1
    assert row["unreviewed"] == 50


@pytest.mark.django_db
def test_uncertain_is_excluded_from_precision_entirely(service, finding_factory, admin_user, organization):
    service.record_verdict(finding=finding_factory(), user=admin_user,
                           verdict=AuditFinding.Verdict.TRUE_POSITIVE)
    service.record_verdict(finding=finding_factory(), user=admin_user,
                           verdict=AuditFinding.Verdict.UNCERTAIN)

    row = service.rule_precision(organization)[0]
    assert row["judged"] == 1
    assert row["precision"] == 1.0
    assert row["uncertain"] == 1


@pytest.mark.django_db
def test_a_rule_with_no_judgements_reports_none_not_zero(service, finding_factory, organization):
    """None means unmeasured. 0.0 means measured and wrong. Not the same."""
    finding_factory()
    assert service.rule_precision(organization)[0]["precision"] is None


@pytest.mark.django_db
def test_worst_rules_sort_first_and_unmeasured_ones_last(service, finding_factory, admin_user, organization):
    service.record_verdict(finding=finding_factory(rule_code="GOOD-1"), user=admin_user,
                           verdict=AuditFinding.Verdict.TRUE_POSITIVE)
    service.record_verdict(finding=finding_factory(rule_code="BAD-1"), user=admin_user,
                           verdict=AuditFinding.Verdict.FALSE_POSITIVE, note="misfire")
    finding_factory(rule_code="UNKNOWN-1")

    order = [r["rule_code"] for r in service.rule_precision(organization)]
    assert order == ["BAD-1", "GOOD-1", "UNKNOWN-1"]


@pytest.mark.django_db
def test_coverage_reports_how_little_has_been_judged(service, finding_factory, admin_user, organization):
    service.record_verdict(finding=finding_factory(), user=admin_user,
                           verdict=AuditFinding.Verdict.TRUE_POSITIVE)
    for _ in range(9):
        finding_factory()

    assert service.coverage(organization) == {"total": 10, "judged": 1, "percent": 10.0}


@pytest.mark.django_db
def test_coverage_percent_is_none_when_there_is_nothing_to_judge(service, organization):
    assert service.coverage(organization)["percent"] is None


# ── The verdict is evidence, so it is logged ─────────────────────────────────

@pytest.mark.django_db
def test_a_verdict_is_written_to_the_audit_chain(service, finding_factory, admin_user):
    from apps.authentication.models import AuditLog

    finding = finding_factory()
    service.record_verdict(finding=finding, user=admin_user,
                           verdict=AuditFinding.Verdict.FALSE_POSITIVE,
                           note="Supplier legitimately bills twice monthly.")

    entry = AuditLog.objects.filter(details__action_type="audit.finding.verdict").last()
    assert entry is not None, "a judgement with no logged author"
    assert entry.details["new_value"] == AuditFinding.Verdict.FALSE_POSITIVE
    assert entry.details["metadata"]["rule_code"] == "DUP-001"


# ── HTTP surface ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_endpoint_records_a_verdict(finding_factory, admin_user):
    client = APIClient()
    client.force_authenticate(admin_user)
    finding = finding_factory()

    response = client.post(
        f"/api/v1/audit/findings/{finding.id}/verdict/",
        {"verdict": "false_positive", "note": "Legitimate recurring charge."},
        format="json",
    )
    assert response.status_code == 200
    finding.refresh_from_db()
    assert finding.verdict == AuditFinding.Verdict.FALSE_POSITIVE


@pytest.mark.django_db
def test_endpoint_hides_another_tenants_finding_behind_a_404(finding_factory, admin_user):
    """403 would confirm the id exists."""
    from apps.authentication.models import Organization

    other = Organization.objects.create(name="Other", name_ar="أخرى")
    foreign = finding_factory(organization=other)

    client = APIClient()
    client.force_authenticate(admin_user)
    response = client.post(f"/api/v1/audit/findings/{foreign.id}/verdict/",
                           {"verdict": "true_positive"}, format="json")
    assert response.status_code == 404


@pytest.mark.django_db
def test_endpoint_requires_authentication(finding_factory):
    finding = finding_factory()
    response = APIClient().post(f"/api/v1/audit/findings/{finding.id}/verdict/",
                                {"verdict": "true_positive"}, format="json")
    assert response.status_code in (401, 403)


@pytest.mark.django_db
def test_precision_endpoint_serves_coverage_next_to_the_ratio(finding_factory, admin_user):
    """A ratio without its sample size is the unsourced claim, rebuilt."""
    client = APIClient()
    client.force_authenticate(admin_user)
    finding_factory()

    body = client.get("/api/v1/audit/rule-precision/").json()
    assert "coverage" in body and "rules" in body
    assert body["coverage"]["judged"] == 0


# ── What the UI depends on ────────────────────────────────────────────────────
# The buttons live in templates/invoices/session_detail.html and are the only
# entry point to the whole loop. Three things silently break them, none of which
# raises: the list endpoint omitting `verdict`, the POST response using a
# different field name than the list, and the Alpine handler reading the wrong
# property off a thrown Error.

@pytest.mark.django_db
def test_the_findings_list_carries_the_verdict_so_buttons_know_what_to_show(
    finding_factory, admin_user, organization
):
    from apps.audit.models import AuditSession
    from apps.audit.serializers import AuditFindingSerializer

    session = AuditSession.objects.create(organization=organization)
    finding = finding_factory(audit_session=session)
    data = AuditFindingSerializer(finding).data

    for field in ("verdict", "verdict_at", "verdict_by_name", "verdict_note"):
        assert field in data, f"the card cannot render without {field}"
    assert data["verdict"] == AuditFinding.Verdict.UNREVIEWED


@pytest.mark.django_db
def test_the_verdict_response_uses_the_same_field_names_as_the_list(
    finding_factory, admin_user
):
    """The UI patches the row in place from this response.

    A mismatch here shows as a card that silently stops naming the reviewer
    after you judge it — no error anywhere.
    """
    from apps.audit.serializers import AuditFindingSerializer

    client = APIClient()
    client.force_authenticate(admin_user)
    finding = finding_factory()

    response = client.post(f"/api/v1/audit/findings/{finding.id}/verdict/",
                           {"verdict": "true_positive"}, format="json")
    finding.refresh_from_db()
    listed = AuditFindingSerializer(finding).data

    assert response.data["verdict"] == listed["verdict"]
    assert "verdict_by_name" in response.data
    assert response.data["verdict_by_name"] == listed["verdict_by_name"]


@pytest.mark.django_db
def test_the_verdict_is_read_only_through_the_list_serializer(finding_factory):
    """A verdict must carry an author and a chain entry, so it cannot be set
    by PATCHing the finding — only through the service."""
    from apps.audit.serializers import AuditFindingSerializer

    serializer = AuditFindingSerializer(
        finding_factory(), data={"verdict": "true_positive"}, partial=True
    )
    assert serializer.is_valid(), serializer.errors
    assert "verdict" not in serializer.validated_data


def test_the_ui_reads_the_error_message_the_way_apiFetch_throws_it():
    """apiFetch throws `new Error(data.detail)` — the text is on `.message`.

    Reading `.detail` off an Error yields undefined, and every refusal would
    render as the generic fallback. The auditor would never learn that a false
    positive needs a reason; they would just see 'try again' and stop.
    """
    from pathlib import Path

    import re

    repo = Path(__file__).resolve().parents[1]
    session_detail = (repo / "templates/invoices/session_detail.html").read_text(encoding="utf-8")
    handler = session_detail.split("async recordVerdict")[1].split("async load()")[0]
    # Comments name err.detail to explain why it is wrong. Strip them, or this
    # assertion fails on its own documentation — the third time today that a
    # naive text search matched an explanatory comment.
    code_only = re.sub(r"//.*", "", handler)

    assert "err.message" in code_only
    assert "err.detail" not in code_only

    api_fetch = (repo / "templates/layouts/dashboard_base.html").read_text(encoding="utf-8")
    assert "throw new Error((data && (data.detail" in api_fetch, (
        "apiFetch's error shape changed — recordVerdict reads err.message and "
        "must be revisited"
    )

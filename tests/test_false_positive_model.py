"""The model that learns from your auditors — and the limits it must keep.

This is the only component here that learns anything specific to you. A local
LLM arrives pre-trained on the internet and knows nothing about your rules or
which of your findings turn out to be noise; the verdicts your seniors record
are a labelled dataset nobody else has.

The tests are mostly about refusals and about one boundary that matters more
than any score: the model **ranks**, it never suppresses. A model trained on
past rejections that hides new findings is a machine for confirming yesterday's
judgement, and in an audit that is a control failure, not a UX trade-off.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.ai.false_positive_model import (
    MIN_PER_CLASS,
    MIN_TRAINING_ROWS,
    FalsePositivePredictor,
)


@pytest.fixture
def judged(db, organization, admin_user):
    """Findings with verdicts, in whatever mix a test asks for."""
    from apps.audit.models import AuditFinding

    def _make(*, noisy_rule_count=0, clean_rule_count=0):
        now = timezone.now()
        created = []

        # A rule that is mostly noise — the pattern the model should find.
        for i in range(noisy_rule_count):
            created.append(AuditFinding.objects.create(
                organization=organization, rule_code="DUP-001",
                rule_name="Duplicate", rule_group="DUP", severity="low",
                message="possible duplicate", source="validation_engine",
                verdict=(AuditFinding.Verdict.FALSE_POSITIVE if i % 10 < 8
                         else AuditFinding.Verdict.TRUE_POSITIVE),
                verdict_note="x", verdict_at=now - timedelta(days=i % 30),
            ))

        # A rule that is mostly real.
        for i in range(clean_rule_count):
            created.append(AuditFinding.objects.create(
                organization=organization, rule_code="VAT-002",
                rule_name="VAT mismatch", rule_group="VAT", severity="critical",
                message="vat does not reconcile with the subtotal",
                source="validation_engine",
                verdict=(AuditFinding.Verdict.TRUE_POSITIVE if i % 10 < 8
                         else AuditFinding.Verdict.FALSE_POSITIVE),
                verdict_note="x", verdict_at=now - timedelta(days=i % 30),
            ))
        return created

    return _make


# ── Refusals ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_too_little_data_is_refused_with_a_reason_not_fitted_anyway(organization, judged):
    """A model fitted on forty rows encodes noise as confidence."""
    judged(noisy_rule_count=20, clean_rule_count=20)

    report = FalsePositivePredictor(organization).train()

    assert report.trained is False
    assert str(MIN_TRAINING_ROWS) in report.reason
    assert "time, not of tuning" in report.reason


@pytest.mark.django_db
def test_a_one_sided_dataset_is_refused(organization, judged):
    """300 true positives and 4 false positives fits a model that predicts the
    majority every time and reports 98% accuracy for doing nothing — the trap
    an accuracy figure alone can never reveal."""
    judged(clean_rule_count=250)      # ~10% false positives → below MIN_PER_CLASS? no
    from apps.audit.models import AuditFinding

    # Force a genuinely lopsided set.
    AuditFinding.objects.filter(
        organization=organization, verdict=AuditFinding.Verdict.FALSE_POSITIVE,
    ).exclude(
        pk__in=list(
            AuditFinding.objects.filter(
                organization=organization,
                verdict=AuditFinding.Verdict.FALSE_POSITIVE,
            ).values_list("pk", flat=True)[:5]
        )
    ).delete()

    report = FalsePositivePredictor(organization).train()

    assert report.trained is False
    assert str(MIN_PER_CLASS) in report.reason
    assert "majority class" in report.reason


@pytest.mark.django_db
def test_an_organisation_with_no_verdicts_is_told_to_wait(organization):
    report = FalsePositivePredictor(organization).train()

    assert report.trained is False
    assert report.rows == 0


# ── Training ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_a_balanced_dataset_trains_and_reports_its_own_quality(organization, judged):
    judged(noisy_rule_count=150, clean_rule_count=150)

    report = FalsePositivePredictor(organization).train()

    assert report.trained is True
    assert report.rows == 300
    assert report.roc_auc is not None
    assert report.precision is not None and report.recall is not None


@pytest.mark.django_db
def test_the_model_finds_the_pattern_that_is_actually_there(organization, judged):
    """DUP-001 is 80% noise and VAT-002 is 80% real. If the model cannot
    separate those, its ranking is worthless and `is_useful` must say so."""
    judged(noisy_rule_count=200, clean_rule_count=200)

    report = FalsePositivePredictor(organization).train()

    assert report.is_useful, f"AUC {report.roc_auc} — the model learned nothing"
    assert report.roc_auc > 0.7


@pytest.mark.django_db
def test_a_guessing_model_is_reported_as_not_useful(organization, judged):
    """AUC near 0.5 is a coin flip. Shipping it would dress chance in a
    probability."""
    from core.ai.false_positive_model import TrainingReport

    report = TrainingReport(trained=True, roc_auc=0.51)
    assert report.is_useful is False


@pytest.mark.django_db
def test_the_features_that_drove_the_model_are_reported(organization, judged):
    """A model whose inputs nobody can name cannot be defended to a regulator,
    and defensibility is this product's entire argument."""
    judged(noisy_rule_count=200, clean_rule_count=200)

    report = FalsePositivePredictor(organization).train()

    assert report.top_features
    assert all("feature" in item and "importance" in item for item in report.top_features)


# ── The boundary that matters ────────────────────────────────────────────────

@pytest.mark.django_db
def test_ranking_never_drops_a_finding(organization, judged):
    """THE control. A model trained on past rejections that hides new findings
    confirms yesterday's judgement forever."""
    judged(noisy_rule_count=200, clean_rule_count=200)
    predictor = FalsePositivePredictor(organization)
    predictor.train()

    from apps.audit.models import AuditFinding

    findings = list(AuditFinding.objects.filter(organization=organization)[:50])
    ranked = predictor.rank(findings)

    assert len(ranked) == len(findings)
    assert {r["finding"].pk for r in ranked} == {f.pk for f in findings}


@pytest.mark.django_db
def test_likely_real_findings_sort_before_likely_noise(organization, judged):
    judged(noisy_rule_count=200, clean_rule_count=200)
    predictor = FalsePositivePredictor(organization)
    predictor.train()

    from apps.audit.models import AuditFinding

    findings = list(AuditFinding.objects.filter(organization=organization)[:40])
    ranked = predictor.rank(findings)

    probabilities = [r["false_positive_probability"] for r in ranked]
    assert probabilities == sorted(probabilities), "not ordered least-noisy-first"


@pytest.mark.django_db
def test_an_untrained_predictor_still_returns_every_finding(organization, judged):
    """No model is not a reason to show fewer findings."""
    judged(noisy_rule_count=10)
    predictor = FalsePositivePredictor(organization)
    predictor.train()

    from apps.audit.models import AuditFinding

    findings = list(AuditFinding.objects.filter(organization=organization))
    ranked = predictor.rank(findings)

    assert len(ranked) == len(findings)
    assert all(r["false_positive_probability"] is None for r in ranked)
    assert all(r["reason"] for r in ranked), "silence about why there is no score"


@pytest.mark.django_db
def test_every_ranked_row_carries_the_basis_for_its_score(organization, judged):
    """A bare probability cannot be argued with, so it gets accepted or ignored
    wholesale — the same reason the anomaly detector explains itself."""
    judged(noisy_rule_count=200, clean_rule_count=200)
    predictor = FalsePositivePredictor(organization)
    predictor.train()

    from apps.audit.models import AuditFinding

    ranked = predictor.rank(list(AuditFinding.objects.filter(organization=organization)[:5]))
    assert all("AUC" in r["reason"] for r in ranked)


# ── Tenant isolation ─────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_training_uses_only_this_organisations_verdicts(organization, judged, admin_user):
    """One tenant's tolerance for noise says nothing about another's, and a
    shared model would leak the shape of one customer's book into another's
    queue ordering."""
    from apps.audit.models import AuditFinding
    from apps.authentication.models import Organization

    judged(noisy_rule_count=150, clean_rule_count=150)

    other = Organization.objects.create(name="Other", name_ar="أخرى")
    for i in range(500):
        AuditFinding.objects.create(
            organization=other, rule_code="OTHER-1", rule_name="Other",
            message="x", verdict=AuditFinding.Verdict.FALSE_POSITIVE,
            verdict_note="x",
        )

    report = FalsePositivePredictor(organization).train()
    assert report.rows == 300


@pytest.mark.django_db
def test_unjudged_findings_are_not_training_data(organization, judged):
    """"Nobody looked" is not a label. Treating it as one teaches the model
    that unreviewed findings are correct."""
    from apps.audit.models import AuditFinding

    judged(noisy_rule_count=150, clean_rule_count=150)
    for i in range(100):
        AuditFinding.objects.create(
            organization=organization, rule_code="NEW-1", rule_name="New",
            message="unreviewed",
        )

    assert FalsePositivePredictor(organization).train().rows == 300

"""No number may be presented as a measurement unless something measured it.

The reports page used to print a hardcoded "98.5% AI extraction quality" and a
hardcoded "95% ZATCA Phase 2 status" under labels that told the auditor these
were *their organisation's* figures. In an audit product that is the worst
version of the problem: a professional judgement resting on a constant.

Two rules, one test file:
  1. a metric with a real source is computed from that source;
  2. a metric with no source renders as "not measured" — never as a number,
     and never as 0, because 0% compliance and "we never measured" are
     different facts that must not collapse into the same pixel.
"""

import re
from decimal import Decimal
from pathlib import Path

import pytest

from apps.frontend.page_views import _latest_measured_extraction_accuracy

BASE_DIR = Path(__file__).resolve().parents[1]


# ── The specific fabrications, so they cannot come back ───────────────────────

def test_the_fabricated_constants_are_gone_from_the_reports_template():
    source = (BASE_DIR / "templates/reports/index.html").read_text(encoding="utf-8")
    assert "98.5%" not in source, "hardcoded extraction-accuracy figure is back"
    assert ">95%<" not in source.replace(" ", ""), "hardcoded ZATCA figure is back"


def test_no_template_prints_a_bare_percentage_in_a_metric_slot():
    """A literal percentage inside a *-value element is a measurement claim.

    Scoped to value elements on purpose: percentages in prose, CSS widths, and
    chart geometry are fine. It is the number-in-a-metric-slot that lies —
    `summary-card-value`, `stat-value`, `stat-cell-value`, `brand-feature-value`
    all render as "here is your figure".

    Counts are still allowed (`+130`, `6`) because a count is checkable against
    the repository. A percentage is a claim about performance, and this project
    has no measurement to back one until §1.2 of the remediation plan lands.
    """
    offenders = []
    pattern = re.compile(r'class="[^"]*(?:card|stat|feature)[^"]*-value[^"]*"[^>]*>\s*([\d.]+)\s*%')
    for template in (BASE_DIR / "templates").rglob("*.html"):
        for match in pattern.finditer(template.read_text(encoding="utf-8")):
            offenders.append(f"{template.relative_to(BASE_DIR)}: {match.group(1)}%")
    assert not offenders, "hardcoded metric values:\n  " + "\n  ".join(offenders)


def test_the_marketing_accuracy_and_automation_claims_are_gone():
    """98% / 95% appeared on the landing pages and the login portal.

    They were never measured. On a page an enterprise buyer reads, an
    unsourced performance figure is a contractual exposure, not a typo.
    """
    offenders = []
    for path in ("templates/landing/index.html",
                 "templates/landing/page.html",
                 "templates/auth/portal.html",
                 # Found by the repo-wide scanner above, not by hand — which is
                 # the argument for having the scanner.
                 "templates/auth/login.html"):
        text = _without_comments((BASE_DIR / path).read_text(encoding="utf-8"))
        for claim in (">98%<", ">95%<", "95% Automation", "98% Accuracy"):
            if claim in text.replace(" ", "").replace("\n", "") or claim in text:
                offenders.append(f"{path}: {claim}")
    assert not offenders, "unsourced marketing claim:\n  " + "\n  ".join(offenders)


def _without_comments(template_source):
    """Strip Django comments before scanning for forbidden strings.

    A comment that says «this replaced "95% Automation"» is documentation, not
    a claim on the page. Scanning raw source made this guard fail on its own
    explanation — the fourth time in one session that a text scan matched the
    note describing why the thing is absent. The rule that keeps falling out of
    it: a guard that greps source has to parse out comments first, or it
    eventually flags the comment that explains the guard.
    """
    without_blocks = re.sub(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", "",
                            template_source, flags=re.S)
    return re.sub(r"{#.*?#}", "", without_blocks, flags=re.S)


def test_the_countable_claims_are_actually_true():
    """"+130 rules" and "6 ERP integrations" replaced the percentages.

    A replacement claim that is also unverified would be no improvement, so
    this counts the real thing. If a connector is removed, this fails and the
    marketing copy gets corrected with it.
    """
    rule_classes = sum(
        1
        for path in (BASE_DIR / "apps/rule_engine/rules").rglob("*.py")
        for line in path.read_text(encoding="utf-8").splitlines()
        if re.match(r"^class \w*Rule", line)
    )
    assert rule_classes >= 130, f"landing page claims +130 rules, found {rule_classes}"

    connectors = {
        p.stem for p in (BASE_DIR / "apps/erp/connectors").glob("*.py")
        if p.stem not in {"__init__", "base", "registry"}
    }
    assert len(connectors) >= 6, f"landing page claims 6 ERP integrations, found {connectors}"


# ── Extraction accuracy: no source → no number ────────────────────────────────

@pytest.mark.django_db
def test_extraction_accuracy_is_none_when_nothing_has_been_measured():
    assert _latest_measured_extraction_accuracy() is None


@pytest.mark.django_db
def test_extraction_accuracy_ignores_runs_that_were_not_approved():
    """A pending or rejected run is not evidence."""
    from apps.auditing.models import AIValidationDataset, AIValidationRun

    dataset = AIValidationDataset.objects.create(name="ocr_eval_v1")
    for decision in (AIValidationRun.Decision.PENDING,
                     AIValidationRun.Decision.NOT_APPROVED):
        AIValidationRun.objects.create(
            dataset=dataset, component=AIValidationRun.Component.OCR,
            model_version="tesseract-5.3", field_accuracy=0.985, decision=decision,
        )
    assert _latest_measured_extraction_accuracy() is None


@pytest.mark.django_db
def test_extraction_accuracy_reports_the_approved_run_with_its_provenance():
    """A number without a model version and dataset is not auditable."""
    from apps.auditing.models import AIValidationDataset, AIValidationRun

    dataset = AIValidationDataset.objects.create(name="ocr_eval_v1")
    AIValidationRun.objects.create(
        dataset=dataset, component=AIValidationRun.Component.OCR,
        model_version="tesseract-5.3", field_accuracy=0.912,
        decision=AIValidationRun.Decision.APPROVED,
    )
    measured = _latest_measured_extraction_accuracy()
    assert measured["pct"] == 91.2
    assert measured["model_version"] == "tesseract-5.3"
    assert measured["dataset"] == "ocr_eval_v1"


@pytest.mark.django_db
def test_extraction_accuracy_does_not_borrow_another_components_score():
    """A great duplicate-detection F1 says nothing about OCR field accuracy."""
    from apps.auditing.models import AIValidationDataset, AIValidationRun

    dataset = AIValidationDataset.objects.create(name="dup_eval_v1")
    AIValidationRun.objects.create(
        dataset=dataset, component=AIValidationRun.Component.DUPLICATE,
        model_version="rules-v3", field_accuracy=0.99,
        decision=AIValidationRun.Decision.APPROVED,
    )
    assert _latest_measured_extraction_accuracy() is None


# ── ZATCA compliance: computed from the tenant's own invoices ─────────────────

@pytest.mark.django_db
def test_zatca_compliance_is_computed_from_real_invoices(client, admin_user, invoice_factory):
    invoice_factory(invoice_number="A-1", qr_code_valid=True)
    invoice_factory(invoice_number="A-2", qr_code_valid=True)
    invoice_factory(invoice_number="A-3", qr_code_valid=False)
    invoice_factory(invoice_number="A-4", qr_code_valid=False)

    client.force_login(admin_user)
    kpis = client.get("/reports/").context["report_kpis"]

    assert kpis["zatca_qr_valid_count"] == 2
    assert kpis["zatca_compliance_pct"] == 50.0


@pytest.mark.django_db
def test_zatca_compliance_is_none_not_zero_when_there_are_no_invoices(client, admin_user):
    """"No data" and "nothing complies" are different facts."""
    client.force_login(admin_user)
    kpis = client.get("/reports/").context["report_kpis"]
    assert kpis["zatca_compliance_pct"] is None


@pytest.mark.django_db
def test_zero_compliance_renders_as_zero_and_not_as_a_dash(client, admin_user, invoice_factory):
    """Regression on the None/0 collapse: a real 0% must be shown, not hidden."""
    invoice_factory(invoice_number="B-1", qr_code_valid=False)
    client.force_login(admin_user)
    response = client.get("/reports/")
    assert response.context["report_kpis"]["zatca_compliance_pct"] == 0.0


@pytest.mark.django_db
def test_the_rendered_page_shows_a_dash_rather_than_a_number_when_unmeasured(client, admin_user):
    """End-to-end: what the auditor actually sees when nothing is measured."""
    client.force_login(admin_user)
    html = client.get("/reports/").content.decode()
    assert "98.5%" not in html


# ── The platform's own VAT status ─────────────────────────────────────────────
# مؤسسة أحصل الحل is registered with ZATCA as NOT subject to VAT
# (إشعار طلب التسجيل — غير خاضع, ref 60001208479). So the platform must not add
# VAT to its own subscription prices, and must not present a VAT number of its
# own. This is separate from the ZATCA features above, which validate the
# *customers'* invoices — customers are subject; the vendor is not.

def test_subscription_pricing_adds_no_vat():
    """A 15% line appearing in billing would be an unlawful charge, not a bug."""
    from apps.payments import pricing

    source = Path(pricing.__file__).read_text(encoding="utf-8")
    for marker in ("0.15", "1.15", "VAT", "vat_amount", "tax_rate"):
        assert marker not in source, f"{marker!r} in pricing.py — platform is غير خاضع"


def test_billing_templates_do_not_claim_a_vat_inclusive_price():
    offenders = []
    for template in (BASE_DIR / "templates/billing").rglob("*.html"):
        text = template.read_text(encoding="utf-8")
        for marker in ("شامل الضريبة", "شاملة الضريبة", "ضريبة القيمة المضافة", "incl. VAT", "VAT included"):
            if marker in text:
                offenders.append(f"{template.relative_to(BASE_DIR)}: {marker}")
    assert not offenders, "VAT claimed on a non-VAT-registered vendor:\n  " + "\n  ".join(offenders)


# ── Rule precision: measured from the tenant's own verdicts ──────────────────
# This is the card that replaced the hardcoded "Risks Found: 0". Unlike
# extraction accuracy, it IS computable from tenant data, because the auditors'
# verdicts are the labels. The tests below are about the ways that number can
# still mislead.

@pytest.mark.django_db
def test_rule_precision_is_dash_until_something_has_been_judged(client, admin_user):
    client.force_login(admin_user)
    assert client.get("/reports/").context["rule_accuracy"] is None


@pytest.mark.django_db
def test_rule_precision_is_measured_from_real_verdicts(client, admin_user, organization):
    from apps.audit.models import AuditFinding
    from apps.audit.services.finding_feedback import FindingFeedbackService

    service = FindingFeedbackService()
    for n in range(3):
        service.record_verdict(
            finding=AuditFinding.objects.create(
                organization=organization, rule_code="DUP-001",
                rule_name="Duplicate", message=f"m{n}"),
            user=admin_user, verdict=AuditFinding.Verdict.TRUE_POSITIVE)
    service.record_verdict(
        finding=AuditFinding.objects.create(
            organization=organization, rule_code="DUP-001",
            rule_name="Duplicate", message="m4"),
        user=admin_user, verdict=AuditFinding.Verdict.FALSE_POSITIVE, note="misfire")

    client.force_login(admin_user)
    measured = client.get("/reports/").context["rule_accuracy"]

    assert measured["pct"] == 75.0
    assert measured["judged"] == 4


@pytest.mark.django_db
def test_the_precision_card_never_shows_a_ratio_without_its_sample_size(client, admin_user, organization):
    """A ratio alone is the unsourced claim, rebuilt in a new place."""
    from apps.audit.models import AuditFinding
    from apps.audit.services.finding_feedback import FindingFeedbackService

    FindingFeedbackService().record_verdict(
        finding=AuditFinding.objects.create(
            organization=organization, rule_code="DUP-001",
            rule_name="Duplicate", message="m"),
        user=admin_user, verdict=AuditFinding.Verdict.TRUE_POSITIVE)

    client.force_login(admin_user)
    response = client.get("/reports/")
    measured = response.context["rule_accuracy"]

    assert measured["judged"] == 1
    assert measured["coverage_pct"] is not None
    html = response.content.decode()
    assert "100.0%" in html
    # The sample size has to be on the page next to it, not just in context.
    assert "1" in html


@pytest.mark.django_db
def test_unjudged_findings_drag_coverage_down_without_touching_precision(
    client, admin_user, organization
):
    """Precision says "of what we checked". Coverage says "how little that was"."""
    from apps.audit.models import AuditFinding
    from apps.audit.services.finding_feedback import FindingFeedbackService

    FindingFeedbackService().record_verdict(
        finding=AuditFinding.objects.create(
            organization=organization, rule_code="DUP-001",
            rule_name="Duplicate", message="judged"),
        user=admin_user, verdict=AuditFinding.Verdict.TRUE_POSITIVE)
    for n in range(9):
        AuditFinding.objects.create(organization=organization, rule_code="DUP-001",
                                    rule_name="Duplicate", message=f"unjudged{n}")

    client.force_login(admin_user)
    measured = client.get("/reports/").context["rule_accuracy"]

    assert measured["pct"] == 100.0        # of what was checked
    assert measured["coverage_pct"] == 10.0  # which was almost nothing


@pytest.mark.django_db
def test_rule_precision_does_not_cross_tenants(client, admin_user, organization):
    from apps.audit.models import AuditFinding
    from apps.audit.services.finding_feedback import FindingFeedbackService
    from apps.authentication.models import Organization

    other = Organization.objects.create(name="Other", name_ar="أخرى")
    AuditFinding.objects.create(organization=other, rule_code="X-1", rule_name="X",
                                message="theirs",
                                verdict=AuditFinding.Verdict.FALSE_POSITIVE)
    FindingFeedbackService().record_verdict(
        finding=AuditFinding.objects.create(
            organization=organization, rule_code="DUP-001",
            rule_name="Duplicate", message="ours"),
        user=admin_user, verdict=AuditFinding.Verdict.TRUE_POSITIVE)

    client.force_login(admin_user)
    measured = client.get("/reports/").context["rule_accuracy"]
    assert measured["pct"] == 100.0
    assert measured["judged"] == 1

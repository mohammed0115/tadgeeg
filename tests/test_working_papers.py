"""
Tests for Phase 1.3 — Working Papers + Reviewer Sign-off.

Covers:
  • Happy path: DRAFT → READY_FOR_REVIEW → REVIEWED → LOCKED.
  • Reviewer rejection sends paper back to DRAFT.
  • Role gates: junior cannot review, senior cannot partner-sign.
  • Lock semantics: status=LOCKED triggers chain-hash assignment.
  • Post-lock immutability: editing payload after lock raises ValidationError.
  • Cross-tenant: papers from one org are not visible / actionable from another.
  • Reference auto-numbering increments per (org, paper_type).
"""

from __future__ import annotations

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.audit.integrity import GENESIS_HASH, verify_chain
from apps.audit.models import WorkingPaper, WPSignature
from apps.audit.services.working_papers import (
    WorkingPaperWorkflowError,
    next_reference,
    partner_sign,
    review_paper,
    submit_for_review,
)
from apps.authentication.models import Organization, User


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def org(db):
    return Organization.objects.create(name="WP Test Org")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="WP Test Org B")


@pytest.fixture
def junior(db, org):
    return User.objects.create_user(
        email="junior@wp.test", full_name="Jamil Junior", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )


@pytest.fixture
def senior(db, org):
    return User.objects.create_user(
        email="senior@wp.test", full_name="Sara Senior", password="x",
        organization=org, role=User.Role.SENIOR_AUDITOR,
    )


@pytest.fixture
def partner(db, org):
    return User.objects.create_user(
        email="partner@wp.test", full_name="Pavel Partner", password="x",
        organization=org, role=User.Role.CHIEF_AUDIT_OFFICER,
    )


@pytest.fixture
def paper(db, org, junior):
    return WorkingPaper.objects.create(
        organization=org,
        reference="WP-2026-LS-001",
        title="AR Lead Schedule — FY2026",
        paper_type=WorkingPaper.PaperType.LEAD_SCHEDULE,
        status=WorkingPaper.Status.DRAFT,
        prepared_by=junior,
        content={"opening_balance": 1_000_000, "closing_balance": 1_250_000},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────────

def test_full_signoff_flow_locks_the_paper(db, paper, junior, senior, partner):
    """DRAFT → READY_FOR_REVIEW → REVIEWED → LOCKED, with chain assigned at LOCK."""

    # 1) Submit
    submit_for_review(paper, junior)
    paper.refresh_from_db()
    assert paper.status == WorkingPaper.Status.READY_FOR_REVIEW
    assert paper.submitted_at is not None
    assert paper.event_hash == ""   # chain still deferred

    # 2) Senior approves
    review_paper(paper, senior, decision="approve",
                 notes="Looks good", signature_data={"name": "Sara Senior"})
    paper.refresh_from_db()
    assert paper.status == WorkingPaper.Status.REVIEWED
    assert paper.reviewed_by_id == senior.id
    assert paper.reviewer_notes == "Looks good"
    assert paper.event_hash == ""   # still no chain
    assert WPSignature.objects.filter(paper=paper, role="reviewer").count() == 1

    # 3) Partner signs → paper LOCKS, hash chain populates.
    partner_sign(paper, partner, notes="Approved for filing")
    paper.refresh_from_db()
    assert paper.status == WorkingPaper.Status.LOCKED
    assert paper.partner_signed_by_id == partner.id
    assert paper.locked_at is not None
    assert paper.event_hash != ""
    assert paper.previous_hash == GENESIS_HASH   # first paper in this org's chain
    assert paper.chain_position == 1
    assert WPSignature.objects.filter(paper=paper, role="partner").count() == 1


# ─────────────────────────────────────────────────────────────────────────────
# Reviewer rejects — back to DRAFT
# ─────────────────────────────────────────────────────────────────────────────

def test_reviewer_reject_sends_paper_back_to_draft(db, paper, junior, senior):
    submit_for_review(paper, junior)

    review_paper(paper, senior, decision="reject",
                 notes="Vouching test results missing")

    paper.refresh_from_db()
    assert paper.status == WorkingPaper.Status.DRAFT
    assert paper.reviewer_notes == "Vouching test results missing"
    assert paper.reviewed_by_id is None
    assert paper.submitted_at is None
    # No reviewer signature is created on rejection — only on approve.
    assert WPSignature.objects.filter(paper=paper).count() == 0


def test_reviewer_reject_requires_a_reason(db, paper, junior, senior):
    submit_for_review(paper, junior)
    with pytest.raises(WorkingPaperWorkflowError):
        review_paper(paper, senior, decision="reject", notes="")


# ─────────────────────────────────────────────────────────────────────────────
# Role gates
# ─────────────────────────────────────────────────────────────────────────────

def test_junior_cannot_review(db, paper, junior):
    submit_for_review(paper, junior)
    with pytest.raises(PermissionDenied):
        review_paper(paper, junior, decision="approve",
                     notes="self-approving!")


def test_senior_cannot_partner_sign(db, paper, junior, senior):
    submit_for_review(paper, junior)
    review_paper(paper, senior, decision="approve", notes="ok")
    paper.refresh_from_db()
    with pytest.raises(PermissionDenied):
        partner_sign(paper, senior)


# ─────────────────────────────────────────────────────────────────────────────
# Status guards
# ─────────────────────────────────────────────────────────────────────────────

def test_cannot_review_a_draft(db, paper, senior):
    """Senior cannot review a paper still in DRAFT — preparer must submit first."""
    with pytest.raises(WorkingPaperWorkflowError):
        review_paper(paper, senior, decision="approve", notes="ok")


def test_cannot_partner_sign_an_unreviewed_paper(db, paper, junior, partner):
    submit_for_review(paper, junior)
    # Skip reviewer step — should refuse.
    with pytest.raises(WorkingPaperWorkflowError):
        partner_sign(paper, partner)


def test_cannot_submit_a_locked_paper(db, paper, junior, senior, partner):
    submit_for_review(paper, junior)
    review_paper(paper, senior, decision="approve", notes="ok")
    partner_sign(paper, partner)
    paper.refresh_from_db()
    with pytest.raises(WorkingPaperWorkflowError):
        submit_for_review(paper, junior)


# ─────────────────────────────────────────────────────────────────────────────
# Post-lock immutability via the hash chain
# ─────────────────────────────────────────────────────────────────────────────

def test_locked_paper_payload_cannot_be_edited(db, paper, junior, senior, partner):
    submit_for_review(paper, junior)
    review_paper(paper, senior, decision="approve", notes="ok")
    partner_sign(paper, partner)
    paper.refresh_from_db()

    paper.title = "EDITED AFTER LOCK"
    with pytest.raises(ValidationError):
        paper.save()


def test_locked_chain_verifies_intact(db, paper, junior, senior, partner):
    submit_for_review(paper, junior)
    review_paper(paper, senior, decision="approve", notes="ok")
    partner_sign(paper, partner)

    rep = verify_chain(WorkingPaper, str(paper.organization_id))
    assert rep.is_intact
    assert rep.rows_checked == 1


# ─────────────────────────────────────────────────────────────────────────────
# Reference numbering
# ─────────────────────────────────────────────────────────────────────────────

def test_reference_auto_increments_per_type(db, org):
    ref1 = next_reference(org, WorkingPaper.PaperType.LEAD_SCHEDULE)
    assert ref1.endswith("-001")

    WorkingPaper.objects.create(
        organization=org, reference=ref1, title="t1",
        paper_type=WorkingPaper.PaperType.LEAD_SCHEDULE,
    )

    ref2 = next_reference(org, WorkingPaper.PaperType.LEAD_SCHEDULE)
    assert ref2.endswith("-002")

    # Different paper type → its own counter starts at 001.
    ref3 = next_reference(org, WorkingPaper.PaperType.SUBSTANTIVE_TEST)
    assert ref3.endswith("-001")
    assert "-ST-" in ref3 and "-LS-" in ref2


# ─────────────────────────────────────────────────────────────────────────────
# Cross-tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_papers_from_different_orgs_chain_independently(db, org, org_b):
    junior_a = User.objects.create_user(
        email="ja@x.t", full_name="Junior A", password="x",
        organization=org, role=User.Role.JUNIOR_AUDITOR,
    )
    senior_a = User.objects.create_user(
        email="sa@x.t", full_name="Senior A", password="x",
        organization=org, role=User.Role.SENIOR_AUDITOR,
    )
    partner_a = User.objects.create_user(
        email="pa@x.t", full_name="Partner A", password="x",
        organization=org, role=User.Role.CHIEF_AUDIT_OFFICER,
    )
    junior_b = User.objects.create_user(
        email="jb@x.t", full_name="Junior B", password="x",
        organization=org_b, role=User.Role.JUNIOR_AUDITOR,
    )
    senior_b = User.objects.create_user(
        email="sb@x.t", full_name="Senior B", password="x",
        organization=org_b, role=User.Role.SENIOR_AUDITOR,
    )
    partner_b = User.objects.create_user(
        email="pb@x.t", full_name="Partner B", password="x",
        organization=org_b, role=User.Role.CHIEF_AUDIT_OFFICER,
    )

    pa = WorkingPaper.objects.create(
        organization=org, reference="WP-A-001", title="A",
        paper_type=WorkingPaper.PaperType.MEMO,
        status=WorkingPaper.Status.DRAFT, prepared_by=junior_a,
    )
    pb = WorkingPaper.objects.create(
        organization=org_b, reference="WP-B-001", title="B",
        paper_type=WorkingPaper.PaperType.MEMO,
        status=WorkingPaper.Status.DRAFT, prepared_by=junior_b,
    )

    submit_for_review(pa, junior_a)
    review_paper(pa, senior_a, decision="approve", notes="ok")
    partner_sign(pa, partner_a)
    submit_for_review(pb, junior_b)
    review_paper(pb, senior_b, decision="approve", notes="ok")
    partner_sign(pb, partner_b)

    pa.refresh_from_db(); pb.refresh_from_db()

    # Each chain is independent: each paper's previous_hash is GENESIS.
    assert pa.previous_hash == GENESIS_HASH
    assert pb.previous_hash == GENESIS_HASH
    assert pa.event_hash != pb.event_hash

    rep_a = verify_chain(WorkingPaper, str(org.id))
    rep_b = verify_chain(WorkingPaper, str(org_b.id))
    assert rep_a.is_intact and rep_a.rows_checked == 1
    assert rep_b.is_intact and rep_b.rows_checked == 1

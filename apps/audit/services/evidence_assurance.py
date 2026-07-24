"""Evidence assurance & reporting (TADGEEG-FIN-AUDIT-6D).

Purely ADDITIVE analysis over the 6A/6B/6C evidence data. It REUSES:
  * ``evidence_lifecycle.verify_attachment`` for the actual SHA-256 re-check;
  * ``evidence_lifecycle._attachment_event`` for the append-only trail;
  * ``evidence_request.status_counts`` / ``evidence_lifecycle.dashboard_summary``
    for existing aggregates;
  * ``apps.notifications`` via ``evidence_notifications``.

It never modifies file contents, never repairs or deletes evidence, never
changes a readiness conclusion, never writes to ``apps.ledger``, and uses no AI.
Reporting only.
"""
from __future__ import annotations

import time

from django.db.models import Count, Q
from django.utils import timezone

from apps.audit.audit_difference_models import AuditDifferenceItem
from apps.audit.evidence_models import (
    AuditEvidenceAttachment,
    AuditEvidenceRequest,
    AuditEvidenceRetentionPolicy,
)
from apps.audit.general_ledger_models import GeneralLedgerRiskFinding
from apps.audit.services import evidence_lifecycle as lc
from apps.audit.services import evidence_notifications as ev_notify

_A = AuditEvidenceAttachment
_L = _A.Lifecycle
_VR = _A.VerificationResult
_R = AuditEvidenceRequest
_S = _R.Status

# Coverage below this fraction triggers an auditor notification.
COVERAGE_ALERT_THRESHOLD = 0.5


class AssuranceError(Exception):
    """Raised for invalid assurance/retention configuration."""


# ─────────────────────────────────────────────────────────────────────────────
# 1 — Evidence integrity sweep
# ─────────────────────────────────────────────────────────────────────────────
def _classify(attachment, result: dict) -> tuple[str, str]:
    """Map a verify_attachment() result onto (verification_result, error)."""
    if result.get("ok"):
        return _VR.OK, ""
    error = result.get("error") or ""
    expected = result.get("expected") or ""
    lowered = error.lower()
    if "no stored file" in lowered or "missing from storage" in lowered:
        return _VR.MISSING_FILE, error
    if "unreadable" in lowered:
        return _VR.UNREADABLE, error
    if not expected:
        return _VR.NO_DIGEST, error or "no stored SHA-256 to compare against."
    if error:
        return _VR.UNREADABLE, error
    return _VR.HASH_MISMATCH, "recomputed digest does not match the stored SHA-256."


def sweep_attachments(*, organization=None, engagement=None, actor=None,
                      limit=None, notify=True) -> dict:
    """Deterministically re-verify every live attachment; report only.

    Reuses :func:`evidence_lifecycle.verify_attachment` for the hash comparison
    and records the detailed outcome + duration. Files are never modified or
    repaired — failures are reported for auditor action.
    """
    qs = AuditEvidenceAttachment.objects.filter(
        lifecycle_state__in=list(_A.LIVE_STATES))
    if organization is not None:
        qs = qs.filter(organization=organization)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    qs = qs.select_related("evidence_request", "organization", "engagement")
    if limit:
        qs = qs[:limit]

    stats = {"checked": 0, "ok": 0, "failed": 0, "duration_ms": 0,
             "by_result": {}, "failures": []}
    started = time.monotonic()

    for att in qs:
        t0 = time.monotonic()
        result = lc.verify_attachment(att, actor=actor)  # REUSED from 6C
        duration_ms = int((time.monotonic() - t0) * 1000)
        verification_result, error = _classify(att, result)

        att.verification_result = verification_result
        att.verification_duration_ms = duration_ms
        att.verification_error = error
        att.save(update_fields=["verification_result", "verification_duration_ms",
                                "verification_error"])

        stats["checked"] += 1
        stats["by_result"][verification_result] = \
            stats["by_result"].get(verification_result, 0) + 1
        if verification_result == _VR.OK:
            stats["ok"] += 1
        elif verification_result in _A.FAILED_VERIFICATION_RESULTS:
            stats["failed"] += 1
            stats["failures"].append({
                "attachment_id": str(att.id),
                "request_number": att.evidence_request.request_number,
                "filename": att.original_filename,
                "result": verification_result,
                "error": error,
            })
            if notify:
                ev_notify.notify_integrity_failure(att, result=verification_result,
                                                   error=error)

    stats["duration_ms"] = int((time.monotonic() - started) * 1000)
    stats["completed_at"] = timezone.now().isoformat()
    if notify and organization is not None:
        ev_notify.notify_verification_completed(organization, stats=stats)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
# 2 — Integrity exception report
# ─────────────────────────────────────────────────────────────────────────────
def _attachment_row(att) -> dict:
    return {
        "attachment_id": str(att.id),
        "request_number": att.evidence_request.request_number if att.evidence_request_id else "",
        "filename": att.original_filename,
        "version": att.version,
        "sha256": att.file_sha256,
        "lifecycle_state": att.lifecycle_state,
        "verification_result": att.verification_result,
        "verification_error": att.verification_error,
        "last_verified_at": att.last_verified_at.isoformat() if att.last_verified_at else None,
        "retention_until": str(att.retention_until) if att.retention_until else None,
    }


def integrity_exception_report(*, organization, engagement=None) -> dict:
    """Organization-scoped exception report. Reports only — no actions taken."""
    qs = AuditEvidenceAttachment.objects.filter(organization=organization) \
        .select_related("evidence_request")
    if engagement is not None:
        qs = qs.filter(engagement=engagement)

    buckets = {
        "hash_mismatch": list(qs.filter(verification_result=_VR.HASH_MISMATCH)),
        "missing_files": list(qs.filter(verification_result=_VR.MISSING_FILE)),
        "unreadable": list(qs.filter(verification_result=_VR.UNREADABLE)),
        "no_digest": list(qs.filter(verification_result=_VR.NO_DIGEST)),
        "pending_verification": list(qs.filter(verification_result=_VR.PENDING)),
        "expired": list(qs.filter(lifecycle_state=_L.EXPIRED)),
        "frozen": list(qs.filter(lifecycle_state=_L.FROZEN)),
        "archived": list(qs.filter(lifecycle_state=_L.ARCHIVED)),
    }

    agg = qs.aggregate(
        total=Count("id"),
        verified=Count("id", filter=Q(verification_result=_VR.OK)),
        failed=Count("id", filter=Q(
            verification_result__in=list(_A.FAILED_VERIFICATION_RESULTS))),
        pending=Count("id", filter=Q(verification_result=_VR.PENDING)),
    )
    total = agg["total"] or 0
    verified = agg["verified"] or 0
    integrity_pct = round((verified / total) * 100, 1) if total else None

    return {
        "generated_at": timezone.now().isoformat(),
        "statistics": {**agg, "integrity_percent": integrity_pct},
        "corrupted_count": len(buckets["hash_mismatch"]),
        "exceptions": {name: [_attachment_row(a) for a in rows]
                       for name, rows in buckets.items()},
        "counts": {name: len(rows) for name, rows in buckets.items()},
        "note": "Report only — no evidence was modified, repaired, or deleted.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3 — Evidence coverage analysis
# ─────────────────────────────────────────────────────────────────────────────
def _coverage_status(pct, required) -> str:
    """complete · high · partial · low · none · no_requests."""
    if not required:
        return "no_requests"
    if pct >= 100:
        return "complete"
    if pct >= 75:
        return "high"
    if pct >= 50:
        return "partial"
    if pct > 0:
        return "low"
    return "none"


def _coverage_for_requests(requests) -> dict:
    """Coverage metrics for a set of evidence requests.

    ``required`` = requests raised; ``uploaded`` = requests with >=1 live
    attachment; coverage % = accepted / required.
    """
    required = len(requests)
    accepted = sum(1 for r in requests if r.status == _S.ACCEPTED)
    rejected = sum(1 for r in requests if r.status == _S.REJECTED)
    pending_review = sum(1 for r in requests
                         if r.status in (_S.SUBMITTED, _S.UNDER_REVIEW))
    uploaded = sum(1 for r in requests if getattr(r, "live_attachments", 0))
    pct = round((accepted / required) * 100, 1) if required else 0.0
    return {
        "required": required,
        "uploaded": uploaded,
        "accepted": accepted,
        "rejected": rejected,
        "pending_review": pending_review,
        "coverage_percent": pct,
        "coverage_status": _coverage_status(pct, required),
    }


def _requests_with_attachment_counts(organization, engagement=None):
    qs = AuditEvidenceRequest.objects.filter(organization=organization).annotate(
        live_attachments=Count("attachments", filter=Q(
            attachments__lifecycle_state__in=list(_A.LIVE_STATES))))
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    return qs


def evidence_coverage(*, organization, engagement=None) -> dict:
    """Coverage per GL finding and per SAD item, plus an overall summary."""
    requests = list(_requests_with_attachment_counts(organization, engagement)
                    .select_related("gl_finding", "sad_item"))

    by_finding, by_item = {}, {}
    for req in requests:
        if req.gl_finding_id:
            by_finding.setdefault(req.gl_finding_id, []).append(req)
        if req.sad_item_id:
            by_item.setdefault(req.sad_item_id, []).append(req)

    findings_qs = GeneralLedgerRiskFinding.objects.filter(organization=organization)
    items_qs = AuditDifferenceItem.objects.filter(organization=organization)
    if engagement is not None:
        findings_qs = findings_qs.filter(engagement=engagement)
        items_qs = items_qs.filter(engagement=engagement)

    findings = []
    for f in findings_qs.only("id", "risk_code", "account_code", "status", "severity"):
        metrics = _coverage_for_requests(by_finding.get(f.id, []))
        findings.append({
            "id": str(f.id), "kind": "gl_finding", "reference": f.risk_code,
            "account_code": f.account_code, "status": f.status,
            "severity": f.severity, **metrics,
        })

    items = []
    for it in items_qs.only("id", "account_code", "finding_title", "finding_risk_code"):
        metrics = _coverage_for_requests(by_item.get(it.id, []))
        items.append({
            "id": str(it.id), "kind": "sad_item",
            "reference": it.finding_risk_code or str(it.id),
            "account_code": it.account_code, "title": it.finding_title, **metrics,
        })

    total_required = sum(r["required"] for r in findings + items)
    total_accepted = sum(r["accepted"] for r in findings + items)
    overall_pct = round((total_accepted / total_required) * 100, 1) if total_required else 0.0

    return {
        "generated_at": timezone.now().isoformat(),
        "findings": findings,
        "sad_items": items,
        "summary": {
            "findings_count": len(findings),
            "sad_items_count": len(items),
            "total_required": total_required,
            "total_accepted": total_accepted,
            "coverage_percent": overall_pct,
            "coverage_status": _coverage_status(overall_pct, total_required),
            "items_without_requests": sum(
                1 for r in findings + items if r["coverage_status"] == "no_requests"),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5 — Evidence index (immutable; NO download URLs)
# ─────────────────────────────────────────────────────────────────────────────
def evidence_index(*, organization, engagement=None) -> list[dict]:
    """Immutable evidence index for inclusion in exported reports.

    Deliberately contains NO download URLs — it is a reference listing.
    """
    qs = (AuditEvidenceAttachment.objects.filter(organization=organization)
          .select_related("evidence_request", "evidence_request__gl_finding",
                          "evidence_request__sad_item",
                          "evidence_request__reviewed_by")
          .order_by("evidence_request__request_number", "version"))
    if engagement is not None:
        qs = qs.filter(engagement=engagement)

    index = []
    for n, att in enumerate(qs, start=1):
        req = att.evidence_request
        index.append({
            "evidence_number": f"EV-{n:05d}",
            "request_number": req.request_number if req else "",
            "finding": (req.gl_finding.risk_code
                        if req and req.gl_finding_id else ""),
            "sad_item": (req.sad_item.account_code
                         if req and req.sad_item_id else ""),
            "filename": att.original_filename,
            "version": att.version,
            "sha256": att.file_sha256,
            "integrity": att.integrity_badge,
            "verification_result": att.verification_result,
            "status": req.status if req else "",
            "reviewer": (req.reviewed_by.full_name
                         if req and req.reviewed_by_id else ""),
            "review_date": (req.reviewed_at.date().isoformat()
                            if req and req.reviewed_at else ""),
            "retention_until": str(att.retention_until) if att.retention_until else "",
            "lifecycle_state": att.lifecycle_state,
        })
    return index


# ─────────────────────────────────────────────────────────────────────────────
# 6 — Retention policy (metadata only; never deletes)
# ─────────────────────────────────────────────────────────────────────────────
def set_retention_policy(*, engagement, actor, policy, custom_years=None, reason=""):
    """Create/update the engagement's retention policy (does not apply it)."""
    obj, _created = AuditEvidenceRetentionPolicy.objects.get_or_create(
        engagement=engagement,
        defaults={"organization": engagement.organization})
    obj.organization = engagement.organization
    obj.policy = policy
    obj.custom_years = custom_years
    obj.reason = reason or ""
    obj.full_clean(exclude=["applied_by"])
    obj.save()
    return obj


def apply_retention_policy(*, policy_obj, actor=None) -> dict:
    """Stamp ``retention_until`` on the engagement's attachments.

    METADATA ONLY: no file is deleted, purged, or altered. Frozen attachments
    are skipped (frozen evidence is immutable).
    """
    marked, skipped_frozen = 0, 0
    attachments = AuditEvidenceAttachment.objects.filter(
        engagement=policy_obj.engagement, organization=policy_obj.organization)

    for att in attachments:
        if att.is_frozen:
            skipped_frozen += 1
            continue
        expiry = policy_obj.expiry_for(att.uploaded_at)
        if att.retention_until != expiry:
            att.retention_until = expiry
            att.save(update_fields=["retention_until"])
        marked += 1

    policy_obj.applied_at = timezone.now()
    policy_obj.applied_by = actor if getattr(actor, "pk", None) else None
    policy_obj.attachments_marked = marked
    policy_obj.save(update_fields=["applied_at", "applied_by", "attachments_marked"])
    return {"marked": marked, "skipped_frozen": skipped_frozen,
            "policy": policy_obj.policy, "years": policy_obj.years,
            "note": "Metadata only — no evidence was deleted or purged."}


# ─────────────────────────────────────────────────────────────────────────────
# 7 — Assurance dashboard (aggregate queries only)
# ─────────────────────────────────────────────────────────────────────────────
def assurance_dashboard(*, organization, engagement=None) -> dict:
    """Integrity %, coverage %, and lifecycle/review counters."""
    att_qs = AuditEvidenceAttachment.objects.filter(organization=organization)
    req_qs = AuditEvidenceRequest.objects.filter(organization=organization)
    if engagement is not None:
        att_qs = att_qs.filter(engagement=engagement)
        req_qs = req_qs.filter(engagement=engagement)

    att = att_qs.aggregate(
        total=Count("id"),
        verified=Count("id", filter=Q(verification_result=_VR.OK)),
        failed=Count("id", filter=Q(
            verification_result__in=list(_A.FAILED_VERIFICATION_RESULTS))),
        pending_verification=Count("id", filter=Q(verification_result=_VR.PENDING)),
        expired=Count("id", filter=Q(lifecycle_state=_L.EXPIRED)),
        frozen=Count("id", filter=Q(lifecycle_state=_L.FROZEN)),
        archived=Count("id", filter=Q(lifecycle_state=_L.ARCHIVED)),
    )
    req = req_qs.aggregate(
        open_requests=Count("id", filter=~Q(status__in=list(_R.FINAL_STATUSES))),
        pending_reviews=Count("id", filter=Q(
            status__in=[_S.SUBMITTED, _S.UNDER_REVIEW])),
        rejected=Count("id", filter=Q(status=_S.REJECTED)),
        accepted=Count("id", filter=Q(status=_S.ACCEPTED)),
    )

    total = att["total"] or 0
    integrity_pct = round((att["verified"] / total) * 100, 1) if total else None
    coverage = evidence_coverage(organization=organization, engagement=engagement)

    return {
        **att, **req,
        "integrity_percent": integrity_pct,
        "coverage_percent": coverage["summary"]["coverage_percent"],
        "coverage_status": coverage["summary"]["coverage_status"],
        "verification_status": (
            "failures" if att["failed"] else
            "pending" if att["pending_verification"] else
            "clean" if total else "no_evidence"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4 — Readiness export payload section (informational only)
# ─────────────────────────────────────────────────────────────────────────────
def readiness_evidence_section(*, organization, engagement) -> dict:
    """Evidence assurance block for the 5A/5D readiness export.

    INFORMATIONAL ONLY — it never feeds the readiness conclusion algorithm.
    """
    dash = assurance_dashboard(organization=organization, engagement=engagement)
    coverage = evidence_coverage(organization=organization, engagement=engagement)
    return {
        "informational_only": True,
        "note": ("Evidence assurance is informational and does not change the "
                 "readiness conclusion or constitute an audit opinion."),
        "coverage_percent": coverage["summary"]["coverage_percent"],
        "coverage_status": coverage["summary"]["coverage_status"],
        "coverage_summary": coverage["summary"],
        "integrity_percent": dash["integrity_percent"],
        "integrity_summary": {
            "total_attachments": dash["total"],
            "verified": dash["verified"],
            "failed": dash["failed"],
            "pending_verification": dash["pending_verification"],
            "verification_status": dash["verification_status"],
        },
        "pending_requests": dash["open_requests"],
        "open_reviews": dash["pending_reviews"],
        "rejected_evidence": dash["rejected"],
        "expired_evidence": dash["expired"],
        "frozen_evidence": dash["frozen"],
    }


def check_coverage_threshold(*, organization, engagement=None,
                             threshold=COVERAGE_ALERT_THRESHOLD, notify=True) -> dict:
    """Notify auditors when coverage falls below ``threshold`` (0–1)."""
    coverage = evidence_coverage(organization=organization, engagement=engagement)
    pct = coverage["summary"]["coverage_percent"]
    required = coverage["summary"]["total_required"]
    below = bool(required) and (pct / 100.0) < threshold
    if below and notify:
        ev_notify.notify_coverage_below_threshold(
            organization, coverage_percent=pct, threshold=round(threshold * 100, 1),
            engagement=engagement)
    return {"below_threshold": below, "coverage_percent": pct,
            "threshold_percent": round(threshold * 100, 1)}


def notify_expired_evidence(*, organization, engagement=None) -> dict:
    """Notify auditors about evidence whose retention window has elapsed."""
    today = timezone.now().date()
    qs = AuditEvidenceAttachment.objects.filter(
        organization=organization, retention_until__lt=today).exclude(
        lifecycle_state=_L.EXPIRED)
    if engagement is not None:
        qs = qs.filter(engagement=engagement)
    count = qs.count()
    if count:
        ev_notify.notify_evidence_expired(organization, count=count)
    return {"expired_count": count,
            "note": "Notification only — evidence is never auto-purged."}

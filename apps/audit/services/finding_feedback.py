"""Record an auditor's judgement on whether a rule was right.

This is the only place the product learns anything about its own accuracy.
Everything else in the audit engine is deterministic and self-confident: a rule
fires or it does not, and nothing downstream ever disagrees with it. Without a
verdict recorded here, "how accurate is the engine" has no answer that is not a
guess, thresholds can only be tuned by intuition, and the accuracy figure on a
marketing page has nothing behind it.

Two things this module is careful about:

**The verdict is not the workflow.** ``AuditFinding.status`` says what is being
done (open / resolved / ignored); ``verdict`` says whether the engine was
right. They were one field, and "ignored" meant both "correct, but we accept
it" and "wrong". Measuring precision off that field would count every accepted
risk as an engine error.

**A verdict is evidence, so it is audited.** It feeds accuracy claims, it can
justify changing a rule that other engagements depend on, and in a dispute the
question "who decided this finding was wrong, and when" has to have an answer.
Each verdict is written to the hash-chained audit log through the single writer.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditFinding

logger = logging.getLogger("audit.feedback")


class FeedbackError(Exception):
    """The verdict was refused. The message is safe to show a user."""


#: A false-positive claim changes what a rule does for everyone in the tenant,
#: so it has to say why. The others may stand on their own.
_REASON_REQUIRED = {AuditFinding.Verdict.FALSE_POSITIVE}


class FindingFeedbackService:
    """Records verdicts and reports what they add up to."""

    def record_verdict(self, *, finding, user, verdict, note=""):
        """Attach ``user``'s judgement to ``finding``.

        Returns the updated finding. Raises ``FeedbackError`` for anything the
        caller could reasonably have got wrong, so a view can turn it into a
        message rather than a 500.
        """
        verdict = (verdict or "").strip()
        note = (note or "").strip()

        if verdict not in AuditFinding.Verdict.values:
            raise FeedbackError(f"Unknown verdict {verdict!r}.")
        if verdict == AuditFinding.Verdict.UNREVIEWED:
            raise FeedbackError("Cannot record 'unreviewed' as a judgement.")

        # Tenant isolation is enforced here rather than trusted from the view:
        # a verdict from another organisation would corrupt that tenant's
        # precision figures, and this service is reachable from more than one
        # entry point.
        user_org_id = getattr(user, "organization_id", None)
        if user_org_id is None or user_org_id != finding.organization_id:
            raise FeedbackError("This finding belongs to another organization.")

        if verdict in _REASON_REQUIRED and not note:
            raise FeedbackError(
                "Marking a finding as a false positive requires a short reason "
                "— it is what tells whoever fixes the rule what to change."
            )

        with transaction.atomic():
            previous = finding.verdict
            finding.verdict = verdict
            finding.verdict_by = user
            finding.verdict_at = timezone.now()
            finding.verdict_note = note
            finding.save(update_fields=[
                "verdict", "verdict_by", "verdict_at", "verdict_note",
                "last_detected_at",
            ])
            self._log(finding, user, previous, verdict, note)

        return finding

    @staticmethod
    def _log(finding, user, previous, verdict, note):
        """Write to the hash chain via the single writer.

        ``log_crm_action`` is deliberately best-effort — it returns None rather
        than raising, so that a logging fault cannot abort the caller's
        transaction. That trade-off is not this module's to reverse, but it
        cannot pass unremarked either: a verdict feeds accuracy claims, and an
        unlogged one is a judgement with no author. So a failed write is
        recorded at ERROR and the verdict is kept, on the reasoning that losing
        the auditor's answer is worse than holding it with a gap in the chain.
        """
        from apps.platform_admin.services.crm_audit import log_crm_action

        entry = log_crm_action(
            actor=user,
            organization=finding.organization,
            action_type="audit.finding.verdict",
            resource_type="audit.AuditFinding",
            resource_id=str(finding.id),
            reason=note or None,
            old_value=previous,
            new_value=verdict,
            metadata={"rule_code": finding.rule_code, "rule_name": finding.rule_name},
        )
        if entry is None:
            logger.error(
                "verdict %s→%s on finding %s by user %s was NOT written to the "
                "audit chain — the judgement stands but has no logged author",
                previous, verdict, finding.id, getattr(user, "pk", "?"),
            )
        return entry

    # ── What the verdicts add up to ──────────────────────────────────────

    def rule_precision(self, organization, *, rule_code=None):
        """Measured precision per rule: TP / (TP + FP).

        Only judged findings count. UNREVIEWED and UNCERTAIN are excluded
        rather than assumed correct — treating "nobody looked" as a true
        positive is how a system reports 99% accuracy having measured nothing.

        Returns a list of dicts, worst precision first, so the rules most in
        need of attention are at the top. ``precision`` is None when a rule has
        no judged findings; None is not 0.0 and must not render as 0%.
        """
        from django.db.models import Count, Q

        rows = (
            AuditFinding.objects
            .filter(organization=organization)
            .filter(**({"rule_code": rule_code} if rule_code else {}))
            .values("rule_code", "rule_name")
            .annotate(
                true_positives=Count("id", filter=Q(verdict=AuditFinding.Verdict.TRUE_POSITIVE)),
                false_positives=Count("id", filter=Q(verdict=AuditFinding.Verdict.FALSE_POSITIVE)),
                uncertain=Count("id", filter=Q(verdict=AuditFinding.Verdict.UNCERTAIN)),
                unreviewed=Count("id", filter=Q(verdict=AuditFinding.Verdict.UNREVIEWED)),
                total=Count("id"),
            )
        )

        results = []
        for row in rows:
            judged = row["true_positives"] + row["false_positives"]
            results.append({
                **row,
                "judged": judged,
                "precision": (row["true_positives"] / judged) if judged else None,
            })

        # None sorts last: an unmeasured rule is not a good rule, but it is
        # also not a bad one, and it must not head a list of worst offenders.
        results.sort(key=lambda r: (r["precision"] is None, r["precision"] or 0.0))
        return results

    def coverage(self, organization):
        """How much of the engine's output has actually been judged.

        An accuracy number computed from three judged findings out of nine
        thousand is not an accuracy number. Any caller presenting precision has
        to present this next to it.
        """
        from django.db.models import Count, Q

        counts = AuditFinding.objects.filter(organization=organization).aggregate(
            total=Count("id"),
            judged=Count("id", filter=~Q(verdict=AuditFinding.Verdict.UNREVIEWED)),
        )
        total = counts["total"]
        return {
            "total": total,
            "judged": counts["judged"],
            "percent": round(100.0 * counts["judged"] / total, 1) if total else None,
        }

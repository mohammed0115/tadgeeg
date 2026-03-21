"""
Rule Selector — queries and returns active RuleAssignments for a document type + org.
Handles the merge between system-level (org=NULL) and tenant-level assignments.
"""
import logging
from django.utils import timezone
from django.db import models as django_models

from apps.rule_engine.models import RuleAssignment, AssignmentStatus

logger = logging.getLogger("rule_engine")


class RuleSelector:

    def get_applicable_rules(
        self,
        document_type: str,
        organization_id: str,
    ) -> list:
        """
        Returns ordered list of active RuleAssignments for a document type.

        Priority:
        1. Org-specific assignment (organization_id set) — highest priority
        2. System-level assignment (organization IS NULL) — fallback

        If org has a record for a rule, it overrides the system default entirely.
        If org has no record for a rule, system default applies.
        """
        today = timezone.now().date()

        date_filter = (
            django_models.Q(effective_from__isnull=True) | django_models.Q(effective_from__lte=today)
        ) & (
            django_models.Q(effective_until__isnull=True) | django_models.Q(effective_until__gte=today)
        )

        # Org-specific assignments
        org_assignments = list(
            RuleAssignment.objects.filter(
                document_type=document_type,
                organization_id=organization_id,
                status=AssignmentStatus.ACTIVE,
                rule__is_active=True,
            ).filter(date_filter).select_related("rule").order_by("rule__rule_code")
        )

        # System-level assignments (no org)
        system_assignments = list(
            RuleAssignment.objects.filter(
                document_type=document_type,
                organization__isnull=True,
                status=AssignmentStatus.ACTIVE,
                rule__is_active=True,
            ).filter(date_filter).select_related("rule").order_by("rule__rule_code")
        )

        # Merge: org assignments override system assignments for same rule
        org_rule_ids = {a.rule_id for a in org_assignments}
        merged = list(org_assignments) + [
            a for a in system_assignments
            if a.rule_id not in org_rule_ids
        ]

        # Sort by rule_code for deterministic execution order
        merged.sort(key=lambda a: a.rule.rule_code)

        logger.debug(
            f"Selected {len(merged)} rules for document_type={document_type}, "
            f"org={organization_id} ({len(org_assignments)} org-specific, "
            f"{len(system_assignments) - len(org_rule_ids & {a.rule_id for a in system_assignments})} from system)"
        )

        return merged

    def get_rule_codes_for_document(self, document_type: str, organization_id: str) -> list:
        """Returns just the rule codes — useful for quick checks."""
        return [a.rule.rule_code for a in self.get_applicable_rules(document_type, organization_id)]

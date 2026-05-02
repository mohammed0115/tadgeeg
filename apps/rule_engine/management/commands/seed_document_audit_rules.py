"""Seed the canonical document audit rules from `apps.rule_engine.catalog`.

Idempotent:
  • `RuleDefinition` is created/updated by `rule_code`
  • `RuleDefinitionTranslation` rows (EN + AR) are created/updated by (rule, language)
  • `RuleAssignment` rows are created/updated by (rule, document_type, organization=NULL)

Run:
    ./manage.py seed_document_audit_rules
    ./manage.py seed_document_audit_rules --dry-run
    ./manage.py seed_document_audit_rules --verbose
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.rule_engine.catalog.document_rules import ALL_RULES, CATEGORY_TO_DB, stats
from apps.rule_engine.models.rule_definition import (
    RuleDefinition, RuleDefinitionTranslation, RuleCategory, RuleType, RuleScope, Severity,
)
from apps.rule_engine.models.rule_assignment import (
    RuleAssignment, AssignmentStatus, ApplicabilityMode, SupportedDocumentType,
)


# Map our rule_type strings to the RuleType enum values
RULE_TYPE_MAP = {
    "validation":     RuleType.VALIDATION,
    "compliance":     RuleType.COMPLIANCE,
    "anomaly":        RuleType.ANOMALY,
    "reconciliation": RuleType.RECONCILIATION,
    "risk":           RuleType.RISK,
}

SEVERITY_MAP = {
    "critical": Severity.CRITICAL,
    "high":     Severity.HIGH,
    "medium":   Severity.MEDIUM,
    "low":      Severity.LOW,
    "info":     Severity.INFO,
}

# Set of valid SupportedDocumentType.values — used to validate every rule's
# document_type before we commit, so we fail loudly on a typo instead of
# silently creating an unenforceable rule.
SUPPORTED_DOC_TYPES = {choice.value for choice in SupportedDocumentType}


class Command(BaseCommand):
    help = "Seed the canonical document audit rules + translations + assignments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing to the DB.",
        )
        parser.add_argument(
            "--verbose", action="store_true",
            help="Print every rule action (otherwise only summary).",
        )

    def handle(self, *args, dry_run: bool = False, verbose: bool = False, **kwargs):
        # ── Pre-flight: validate every catalog entry ────────────────────────
        bad = []
        for r in ALL_RULES:
            if r["document_type"] not in SUPPORTED_DOC_TYPES:
                bad.append(f"{r['rule_id']}: unsupported document_type {r['document_type']!r}")
            if r["severity"] not in SEVERITY_MAP:
                bad.append(f"{r['rule_id']}: bad severity {r['severity']!r}")
            if r["rule_type"] not in RULE_TYPE_MAP:
                bad.append(f"{r['rule_id']}: bad rule_type {r['rule_type']!r}")
            if r["category"] not in CATEGORY_TO_DB:
                bad.append(f"{r['rule_id']}: unknown category {r['category']!r}")
        if bad:
            self.stderr.write(self.style.ERROR(
                f"Catalog has {len(bad)} validation issues — aborting:"
            ))
            for b in bad[:20]:
                self.stderr.write(f"  • {b}")
            return

        s = stats()
        self.stdout.write(self.style.NOTICE(
            f"Seeding {s['total']} rules across {len(s['by_type'])} document types."
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no DB writes."))

        created_def = updated_def = 0
        created_tr  = updated_tr  = 0
        created_asg = updated_asg = 0

        # ── Idempotent upsert per rule ──────────────────────────────────────
        with transaction.atomic():
            for r in ALL_RULES:
                rule_code = r["rule_id"]
                category_db = CATEGORY_TO_DB[r["category"]]
                rtype_db    = RULE_TYPE_MAP[r["rule_type"]]
                sev_db      = SEVERITY_MAP[r["severity"]]

                defaults = {
                    "category":             category_db,
                    "rule_type":            rtype_db,
                    "scope":                RuleScope.SPECIALIZED,
                    "default_severity":     sev_db,
                    "implementation_class": "apps.rule_engine.rules.generic.catalog_stub.CatalogStubRule",
                    "default_config":       {"category_label": r["category"]},
                    "blocks_approval":      bool(r.get("blocks_approval", False)),
                    "is_active":            True,
                    "is_system_rule":       True,
                    "tags":                 [r["category"], r["document_type"]],
                }

                if dry_run:
                    rd = RuleDefinition.objects.filter(rule_code=rule_code).first()
                    if rd:
                        updated_def += 1
                    else:
                        created_def += 1
                else:
                    rd, created = RuleDefinition.objects.update_or_create(
                        rule_code=rule_code, defaults=defaults,
                    )
                    if created:
                        created_def += 1
                    else:
                        updated_def += 1

                # ── Translations (EN + AR) ─────────────────────────────────
                for lang, name, desc, fail_msg, rec in [
                    ("en", r["name_en"], r["description_en"], r["fail_message_en"], r["recommendation_en"]),
                    ("ar", r["name_ar"], r["description_ar"], r["fail_message_ar"], r["recommendation_ar"]),
                ]:
                    tr_defaults = {
                        "name":             name,
                        "description":      desc,
                        "fail_message":     fail_msg,
                        "suggested_action": rec,
                    }
                    if dry_run:
                        tr = RuleDefinitionTranslation.objects.filter(
                            rule__rule_code=rule_code, language=lang,
                        ).first()
                        if tr:
                            updated_tr += 1
                        else:
                            created_tr += 1
                    else:
                        _, created = RuleDefinitionTranslation.objects.update_or_create(
                            rule=rd, language=lang, defaults=tr_defaults,
                        )
                        if created:
                            created_tr += 1
                        else:
                            updated_tr += 1

                # ── System-level assignment (organization=NULL) ─────────────
                asg_defaults = {
                    "applicability":      ApplicabilityMode.FULL,
                    "status":              AssignmentStatus.ACTIVE,
                    "severity_override":   None,
                    "blocks_approval_override": (
                        bool(r["blocks_approval"]) if r.get("blocks_approval") else None
                    ),
                }
                if dry_run:
                    a = RuleAssignment.objects.filter(
                        rule__rule_code=rule_code,
                        document_type=r["document_type"],
                        organization=None,
                    ).first()
                    if a:
                        updated_asg += 1
                    else:
                        created_asg += 1
                else:
                    _, created = RuleAssignment.objects.update_or_create(
                        rule=rd,
                        document_type=r["document_type"],
                        organization=None,
                        defaults=asg_defaults,
                    )
                    if created:
                        created_asg += 1
                    else:
                        updated_asg += 1

                if verbose:
                    self.stdout.write(
                        f"  • {rule_code:<10} [{r['document_type']:<20}] "
                        f"{r['severity']:<8} — {r['name_en'][:60]}"
                    )

            if dry_run:
                # Roll back — `dry_run` mode just counts what would happen.
                transaction.set_rollback(True)

        # ── Summary ──────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS(""))
        self.stdout.write(self.style.SUCCESS("──── seed summary ────"))
        self.stdout.write(f"  RuleDefinition:               created={created_def}  updated={updated_def}")
        self.stdout.write(f"  RuleDefinitionTranslation:    created={created_tr}  updated={updated_tr}")
        self.stdout.write(f"  RuleAssignment (system-wide): created={created_asg}  updated={updated_asg}")
        self.stdout.write("")

        # Per-type breakdown
        self.stdout.write("Per-type breakdown:")
        for dtype, n in sorted(stats()["by_type"].items()):
            self.stdout.write(f"  {dtype:<22} {n:>3} rules")
        self.stdout.write("")

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN complete — DB unchanged."))
        else:
            self.stdout.write(self.style.SUCCESS("Seed complete."))

"""
Management command: seed GAAP/IFRS rule definitions into the rule engine.

Usage
-----
    python manage.py seed_gaap_rule_definitions
    python manage.py seed_gaap_rule_definitions --dry-run   # preview only
    python manage.py seed_gaap_rule_definitions --force     # update existing

What it does
------------
  1. Creates (or updates) a RuleDefinition record for each of the 8 GAAP rules
     already implemented in apps/rule_engine/rules/gaap/categories/.
  2. Creates system-level RuleAssignment records for every document type listed
     in each rule's `applies_to` tuple.
  3. Is fully idempotent — safe to run multiple times.

SOLID alignment
---------------
  After this command runs, RuleEngineStage (Stage 3) automatically picks up
  GAAP rules via RuleSelector → RuleAssignment without any code changes.
  The legacy apps/auditing/accounting_rules/ engine is now superseded.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

# ── GAAP rule catalogue ────────────────────────────────────────────────────────
# Each tuple: (rule_code, category, rule_type, default_severity, blocks_approval,
#              implementation_class, name_en, name_ar, description,
#              fail_msg_en, fail_msg_ar, suggested_action_ar, applies_to)

GAAP_CATALOG = [
    (
        "GAAP-COMP-001",
        "data_integrity", "compliance", "high", False,
        "apps.rule_engine.rules.gaap.categories.completeness.GAAPCompletenessCoreFieldsRule",
        "GAAP: Core Completeness Fields",
        "GAAP: اكتمال الحقول الأساسية",
        "Ensure mandatory accounting fields exist for transaction-level records.",
        "Mandatory accounting fields are missing.",
        "الحقول المحاسبية الإلزامية مفقودة.",
        "أضف جميع الحقول المحاسبية المطلوبة.",
        ("sales_invoice", "purchase_order", "expense", "bank_statement", "other"),
    ),
    (
        "GAAP-CUT-001",
        "compliance", "compliance", "high", False,
        "apps.rule_engine.rules.gaap.categories.cutoff.GAAPCutoffPeriodRule",
        "GAAP: Cutoff and Accounting Period",
        "GAAP: قطع الحسابات والفترة المحاسبية",
        "Ensure posting date and document date are inside the approved accounting period.",
        "Document date falls outside the approved accounting period.",
        "تاريخ المستند خارج الفترة المحاسبية المعتمدة.",
        "تحقق من تاريخ التسجيل وتأكد من أنه ضمن الفترة المحاسبية الصحيحة.",
        ("sales_invoice", "purchase_order", "expense", "tax_return", "other"),
    ),
    (
        "GAAP-DOC-001",
        "compliance", "compliance", "high", False,
        "apps.rule_engine.rules.gaap.categories.documentation.GAAPDocumentationSupportRule",
        "GAAP: Supporting Documentation",
        "GAAP: الوثائق الداعمة",
        "Transactions above threshold must include valid supporting evidence.",
        "No supporting documentation found for this high-value transaction.",
        "لم يتم العثور على وثائق داعمة لهذه المعاملة ذات القيمة العالية.",
        "أرفق المستندات الداعمة المطلوبة (فاتورة، عقد، إذن شراء).",
        ("sales_invoice", "purchase_order", "expense", "fixed_asset", "other"),
    ),
    (
        "GAAP-CLS-001",
        "financial_logic", "compliance", "medium", False,
        "apps.rule_engine.rules.gaap.categories.classification.GAAPClassificationCapexOpexRule",
        "GAAP: CAPEX vs OPEX Classification",
        "GAAP: تصنيف النفقات الرأسمالية والتشغيلية",
        "Detect likely misclassification of capital expenditures as operating expenses.",
        "Possible misclassification: high-value item recorded as operating expense.",
        "تصنيف محتمل خاطئ: بند ذو قيمة عالية مُسجَّل كمصروف تشغيلي.",
        "راجع تصنيف هذا البند — قد يكون أصلاً رأسمالياً.",
        ("expense", "purchase_order", "fixed_asset", "sales_invoice", "other"),
    ),
    (
        "GAAP-REV-001",
        "financial_logic", "compliance", "high", False,
        "apps.rule_engine.rules.gaap.categories.recognition.GAAPRevenueRecognitionRule",
        "GAAP: Revenue Recognition Timing",
        "GAAP: توقيت الاعتراف بالإيرادات",
        "Revenue should not be recognized before the supporting performance event.",
        "Revenue recognized before the performance obligation is evidenced.",
        "تم الاعتراف بالإيراد قبل إثبات التزام الأداء.",
        "تحقق من توقيت الاعتراف بالإيراد وتطابقه مع الأداء الفعلي.",
        ("sales_invoice", "sales_receipt", "other"),
    ),
    (
        "GAAP-EXP-001",
        "financial_logic", "compliance", "medium", False,
        "apps.rule_engine.rules.gaap.categories.recognition.GAAPExpenseMatchingRule",
        "GAAP: Expense Matching Principle",
        "GAAP: مبدأ مقابلة المصروفات",
        "Expense recognition should align with the related period and activity.",
        "Expense does not match the period or activity it relates to.",
        "المصروف لا يتطابق مع الفترة أو النشاط المرتبط به.",
        "راجع توقيت تسجيل هذا المصروف.",
        ("expense", "purchase_order", "sales_invoice", "other"),
    ),
    (
        "GAAP-CONS-001",
        "compliance", "compliance", "medium", False,
        "apps.rule_engine.rules.gaap.categories.consistency.GAAPConsistencyTreatmentRule",
        "GAAP: Accounting Treatment Consistency",
        "GAAP: اتساق المعالجة المحاسبية",
        "Similar transactions should be classified and posted consistently.",
        "Inconsistent accounting treatment detected for similar transactions.",
        "تم اكتشاف عدم اتساق في المعالجة المحاسبية لمعاملات مماثلة.",
        "تأكد من تطبيق نفس السياسة المحاسبية على معاملات مماثلة.",
        ("sales_invoice", "purchase_order", "expense", "bank_statement", "other"),
    ),
    (
        "GAAP-ANO-001",
        "anomaly", "anomaly", "high", False,
        "apps.rule_engine.rules.gaap.categories.anomaly.GAAPAnomalyPatternRule",
        "GAAP: Materiality and Anomaly Pattern",
        "GAAP: الأهمية النسبية ونمط الشذوذ",
        "Flag unusually large, duplicate-like, or suspicious rounded transactions.",
        "Transaction exhibits anomaly patterns (unusual amount, rounding, or duplication).",
        "المعاملة تُظهر أنماط شذوذ (مبلغ غير عادي، تقريب مشبوه، أو تكرار).",
        "راجع هذه المعاملة للتحقق من صحتها.",
        ("sales_invoice", "purchase_order", "expense", "bank_statement", "sales_receipt", "other"),
    ),
]


class Command(BaseCommand):
    help = "Seed GAAP/IFRS RuleDefinition and RuleAssignment records for the V2 pipeline."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be created without writing to the database.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Update fields on existing RuleDefinition records.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.rule_engine.models import (
            RuleDefinition,
            RuleAssignment,
            RuleCategory,
            RuleType,
            RuleScope,
            Severity,
            AssignmentStatus,
        )

        dry_run = options["dry_run"]
        force   = options["force"]

        created_defs    = 0
        updated_defs    = 0
        created_assigns = 0
        skipped_assigns = 0

        for entry in GAAP_CATALOG:
            (
                rule_code, category, rule_type, severity, blocks_approval,
                impl_class, name_en, name_ar, description,
                fail_en, fail_ar, action_ar, applies_to,
            ) = entry

            # ── RuleDefinition ──────────────────────────────────────────────
            def_defaults = {
                "category":           category,
                "rule_type":          rule_type,
                "scope":              "specialized",
                "default_severity":   severity,
                "blocks_approval":    blocks_approval,
                "implementation_class": impl_class,
                "is_active":          True,
                "is_system_rule":     True,
                "tags":               ["gaap", "ifrs", category],
            }

            if dry_run:
                self.stdout.write(
                    f"  [DRY-RUN] RuleDefinition: {rule_code} → {impl_class}"
                )
            else:
                rule_def, created = RuleDefinition.objects.get_or_create(
                    rule_code=rule_code,
                    defaults=def_defaults,
                )
                if created:
                    created_defs += 1
                    self.stdout.write(self.style.SUCCESS(f"  + Created RuleDefinition: {rule_code}"))
                elif force:
                    for k, v in def_defaults.items():
                        setattr(rule_def, k, v)
                    rule_def.save()
                    updated_defs += 1
                    self.stdout.write(f"  ~ Updated RuleDefinition: {rule_code}")
                else:
                    self.stdout.write(f"  = Exists RuleDefinition: {rule_code} (skip, use --force to update)")

            # ── RuleAssignment (system-level, org=None) ──────────────────────
            for doc_type in applies_to:
                if dry_run:
                    self.stdout.write(
                        f"    [DRY-RUN] RuleAssignment: {rule_code} → {doc_type}"
                    )
                    continue

                _, assign_created = RuleAssignment.objects.get_or_create(
                    rule=rule_def,
                    document_type=doc_type,
                    organization=None,   # system-level default (all orgs)
                    defaults={"status": AssignmentStatus.ACTIVE},
                )
                if assign_created:
                    created_assigns += 1
                else:
                    skipped_assigns += 1

        if not dry_run:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS(
                f"Done — RuleDefinitions: +{created_defs} created, ~{updated_defs} updated  |  "
                f"RuleAssignments: +{created_assigns} created, {skipped_assigns} already existed"
            ))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Dry-run complete — no changes written."))

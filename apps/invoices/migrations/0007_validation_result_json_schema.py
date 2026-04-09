"""
Migration 0007: Replace 30 boolean columns on InvoiceValidationResult
with a single rule_results JSONField.

Why:
  The previous schema had one boolean column per validation rule.
  Every new rule required a migration + serializer + admin change.
  The new schema stores rule results as a JSON array, decoupling the
  database schema from the rule set.

Data migration:
  Existing rows are converted: each non-null boolean column is translated
  to a rule_result entry in the JSON array with the appropriate rule_code.
  Rows that have all booleans at default values are left with an empty
  rule_results list (they will be re-validated on next processing).
"""
from django.db import migrations, models


# Mapping of old boolean column → (rule_code, rule_name, group, severity, pass_means_true)
# pass_means_true = True  → column=True means the rule PASSED
# pass_means_true = False → column=True means a problem was FOUND (i.e. rule FAILED)
BOOL_TO_RULE = [
    # field_name,                  rule_code,    rule_name,                          group,  severity, pass_on_true
    ("has_invoice_number",         "INV-001",    "Invoice Number Present",            "INV", "high",   True),
    ("has_invoice_date",           "INV-002",    "Invoice Date Present",              "INV", "high",   True),
    ("has_vendor_name",            "INV-003",    "Vendor Name Present",               "INV", "high",   True),
    ("has_vendor_vat",             "INV-004",    "Vendor VAT Number Present",         "INV", "high",   True),
    ("has_total_amount",           "INV-008",    "Total Amount Present",              "INV", "high",   True),
    ("has_currency",               "INV-005",    "Currency Present",                  "INV", "medium", True),
    ("total_greater_zero",         "INV-007",    "Total Amount Greater Than Zero",    "INV", "high",   True),
    ("no_vat_without_base",        "INV-006",    "No VAT Without Subtotal",           "INV", "medium", True),
    ("duplicate_invoice_number",   "DUP-001",    "Duplicate Invoice Number",          "DUP", "high",   False),
    ("duplicate_vendor_and_number","DUP-002",    "Duplicate Vendor + Number",         "DUP", "high",   False),
    ("duplicate_vendor_amount_date","DUP-003",   "Duplicate Vendor + Amount + Date",  "DUP", "high",   False),
    ("duplicate_file_hash",        "DUP-004",    "Duplicate File Hash",               "DUP", "critical",False),
    ("duplicate_across_months",    "DUP-005",    "Duplicate Across Months",           "DUP", "medium", False),
    ("vat_rate_correct",           "VAT-001",    "VAT Rate Correct (15%)",            "VAT", "high",   True),
    ("vat_calculation_correct",    "VAT-002",    "VAT Calculation Correct",           "VAT", "high",   True),
    ("vat_subtotal_correct",       "VAT-003",    "VAT Subtotal Correct",              "VAT", "medium", True),
    ("vat_number_present",         "VAT-004",    "VAT Number Present",                "VAT", "high",   True),
    ("qr_code_valid",              "VAT-005",    "QR Code Valid",                     "VAT", "high",   True),
    ("amount_unusually_high",      "ANO-001",    "Amount Unusually High",             "ANO", "medium", False),
    ("new_unknown_vendor",         "ANO-002",    "New/Unknown Vendor",                "ANO", "medium", False),
    ("many_invoices_same_day",     "ANO-003",    "Many Invoices Same Day",            "ANO", "medium", False),
    ("sudden_price_change",        "ANO-004",    "Sudden Price Change",               "ANO", "medium", False),
    ("many_invoices_year_end",     "ANO-005",    "Many Invoices at Year End",         "ANO", "low",    False),
    ("vendor_dominates_invoices",  "ANO-006",    "Vendor Dominates Invoices",         "ANO", "medium", False),
    ("has_cost_center",            "CTL-001",    "Cost Center Present",               "CTL", "medium", True),
    ("has_account_code",           "CTL-002",    "Account Code Present",              "CTL", "medium", True),
    ("within_budget",              "CTL-003",    "Within Budget",                     "CTL", "high",   True),
    ("no_edit_after_approve",      "CTL-004",    "No Edit After Approval",            "CTL", "high",   True),
    ("has_approver",               "CTL-005",    "Approver Assigned",                 "CTL", "medium", True),
    ("has_audit_trail",            "CTL-006",    "Audit Trail Present",               "CTL", "low",    True),
    ("document_is_clear",          "DOC-001",    "Document Is Clear",                 "DOC", "medium", True),
    ("appears_genuine",            "DOC-002",    "Document Appears Genuine",          "DOC", "critical",True),
    ("no_alterations",             "DOC-003",    "No Alterations Detected",           "DOC", "high",   True),
    ("has_qr_code",                "DOC-004",    "QR Code Present",                   "DOC", "medium", True),
]


def migrate_booleans_to_json(apps, schema_editor):
    """Convert existing boolean columns to rule_results JSON entries."""
    InvoiceValidationResult = apps.get_model("invoices", "InvoiceValidationResult")

    batch = []
    for obj in InvoiceValidationResult.objects.all().iterator(chunk_size=500):
        rule_results = []
        for field_name, rule_code, rule_name, group, severity, pass_on_true in BOOL_TO_RULE:
            col_value = getattr(obj, field_name, None)
            if col_value is None:
                continue
            passed = bool(col_value) if pass_on_true else not bool(col_value)
            rule_results.append({
                "rule_code": rule_code,
                "rule_name": rule_name,
                "group": group,
                "severity": severity,
                "passed": passed,
                "detail": "",
            })
        obj.rule_results = rule_results
        batch.append(obj)
        if len(batch) >= 500:
            InvoiceValidationResult.objects.bulk_update(batch, ["rule_results"])
            batch.clear()

    if batch:
        InvoiceValidationResult.objects.bulk_update(batch, ["rule_results"])


def reverse_json_to_booleans(apps, schema_editor):
    """Reverse migration: re-populate booleans from rule_results JSON (best-effort)."""
    InvoiceValidationResult = apps.get_model("invoices", "InvoiceValidationResult")

    code_to_mapping = {row[1]: row for row in BOOL_TO_RULE}
    batch = []
    for obj in InvoiceValidationResult.objects.all().iterator(chunk_size=500):
        for entry in (obj.rule_results or []):
            code = entry.get("rule_code")
            if code not in code_to_mapping:
                continue
            field_name, _, _, _, _, pass_on_true = code_to_mapping[code]
            passed = bool(entry.get("passed", False))
            col_value = passed if pass_on_true else not passed
            setattr(obj, field_name, col_value)
        batch.append(obj)
        if len(batch) >= 500:
            bool_fields = [row[0] for row in BOOL_TO_RULE]
            InvoiceValidationResult.objects.bulk_update(batch, bool_fields)
            batch.clear()

    if batch:
        bool_fields = [row[0] for row in BOOL_TO_RULE]
        InvoiceValidationResult.objects.bulk_update(batch, bool_fields)


class Migration(migrations.Migration):

    dependencies = [
        ("invoices", "0006_vendor_profile_indexes"),
    ]

    operations = [
        # 1. Add the new JSONField
        migrations.AddField(
            model_name="invoicevalidationresult",
            name="rule_results",
            field=models.JSONField(
                default=list,
                help_text="List of per-rule result dicts: [{rule_code, rule_name, group, severity, passed, detail}, ...]",
            ),
        ),

        # 2. Migrate existing data into the new field
        migrations.RunPython(migrate_booleans_to_json, reverse_code=reverse_json_to_booleans),

        # 3. Remove the 30 old boolean columns
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_invoice_number"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_invoice_date"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_vendor_name"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_vendor_vat"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_total_amount"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_currency"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="total_greater_zero"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="no_vat_without_base"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="duplicate_invoice_number"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="duplicate_vendor_and_number"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="duplicate_vendor_amount_date"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="duplicate_file_hash"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="duplicate_across_months"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="vat_rate_correct"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="vat_calculation_correct"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="vat_subtotal_correct"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="vat_number_present"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="qr_code_valid"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="amount_unusually_high"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="new_unknown_vendor"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="many_invoices_same_day"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="sudden_price_change"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="many_invoices_year_end"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="vendor_dominates_invoices"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_cost_center"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_account_code"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="within_budget"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="no_edit_after_approve"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_approver"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_audit_trail"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="document_is_clear"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="appears_genuine"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="no_alterations"),
        migrations.RemoveField(model_name="invoicevalidationresult", name="has_qr_code"),
    ]

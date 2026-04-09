"""
apps/audit/services/rule_evaluator.py
======================================
CustomRuleEvaluator — evaluates a CustomRuleDefinition against an invoice dict.

Previously this logic lived as CustomRuleDefinition.evaluate() inside the model,
which forced the model to import Invoice, run ORM queries, and contain business
logic — all violations of SRP.

Usage:
    from apps.audit.services.rule_evaluator import CustomRuleEvaluator

    result = CustomRuleEvaluator.evaluate(rule, invoice_dict)
    # {"passed": True/False, "explanation": str}
"""
from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.audit.models import CustomRuleDefinition

logger = logging.getLogger("finai")


class CustomRuleEvaluator:
    """
    Stateless evaluator for CustomRuleDefinition instances.

    All methods are static — instantiation is never needed.
    """

    @staticmethod
    def evaluate(rule: "CustomRuleDefinition", invoice: dict) -> dict:
        """
        Evaluate *rule* against an *invoice* dict.

        Args:
            rule:    A CustomRuleDefinition model instance.
            invoice: A plain dict representing the invoice fields
                     (e.g. from invoice.extracted_data or a serialized Invoice).

        Returns:
            {"passed": bool, "explanation": str}
        """
        from apps.audit.models import CustomRuleDefinition as RuleDef

        ct = rule.condition_type
        params = rule.condition_params or {}

        try:
            if ct == RuleDef.ConditionType.MISSING_FIELD:
                return CustomRuleEvaluator._check_missing_field(params, invoice)

            if ct == RuleDef.ConditionType.AMOUNT_THRESHOLD:
                return CustomRuleEvaluator._check_amount_threshold(params, invoice)

            if ct == RuleDef.ConditionType.DATE_CHECK:
                return CustomRuleEvaluator._check_date(params, invoice)

            if ct == RuleDef.ConditionType.DUPLICATE_CHECK:
                return CustomRuleEvaluator._check_duplicate(rule, invoice)

            if ct == RuleDef.ConditionType.PATTERN_MATCH:
                return CustomRuleEvaluator._check_pattern(params, invoice)

        except Exception as exc:
            logger.warning("CustomRuleEvaluator failed for rule %s: %s", rule.pk, exc)
            return {"passed": False, "explanation": f"خطأ في تقييم القاعدة: {exc}"}

        return {"passed": True, "explanation": ""}

    # ── Condition implementations ─────────────────────────────────────────────

    @staticmethod
    def _check_missing_field(params: dict, invoice: dict) -> dict:
        field = params.get("field", "")
        value = invoice.get(field)
        passed = bool(value and str(value).strip())
        return {
            "passed": passed,
            "explanation": "" if passed else f"شرط '{field}' مفقود أو فارغ.",
        }

    @staticmethod
    def _check_amount_threshold(params: dict, invoice: dict) -> dict:
        amount = float(invoice.get("total_amount") or invoice.get("amount") or 0)
        min_a = float(params.get("min_amount", 0))
        max_a = float(params.get("max_amount", float("inf")))
        passed = min_a <= amount <= max_a
        return {
            "passed": passed,
            "explanation": "" if passed else f"المبلغ {amount} خارج النطاق المسموح [{min_a} – {max_a}].",
        }

    @staticmethod
    def _check_date(params: dict, invoice: dict) -> dict:
        from datetime import date as date_type
        from core.utils.coerce import to_date

        raw = invoice.get("invoice_date") or invoice.get("date")
        if not raw:
            return {"passed": False, "explanation": "تاريخ الفاتورة مفقود."}

        inv_date = raw if isinstance(raw, date_type) else to_date(str(raw)[:10])
        if inv_date is None:
            return {"passed": False, "explanation": f"تعذّر تحليل تاريخ الفاتورة: {raw}"}

        today = date_type.today()
        if params.get("no_future_dates") and inv_date > today:
            return {"passed": False, "explanation": f"تاريخ الفاتورة {inv_date} في المستقبل."}

        max_days = params.get("max_days_old")
        if max_days and (today - inv_date).days > int(max_days):
            return {"passed": False, "explanation": f"تاريخ الفاتورة {inv_date} أقدم من {max_days} يوم."}

        return {"passed": True, "explanation": ""}

    @staticmethod
    def _check_duplicate(rule: "CustomRuleDefinition", invoice: dict) -> dict:
        from apps.invoices.models import Invoice as InvoiceModel

        inv_number = invoice.get("invoice_number", "")
        if not inv_number:
            return {"passed": True, "explanation": ""}

        exists = (
            InvoiceModel.objects.filter(
                organization_id=rule.organization_id,
                invoice_number=inv_number,
            ).count() > 1
        )
        return {
            "passed": not exists,
            "explanation": "" if not exists else f"رقم الفاتورة '{inv_number}' مكرر.",
        }

    @staticmethod
    def _check_pattern(params: dict, invoice: dict) -> dict:
        field = params.get("field", "invoice_number")
        pattern = params.get("pattern", "")
        must_match = params.get("must_match", True)
        value = str(invoice.get(field, "") or "")
        matched = bool(re.search(pattern, value)) if pattern else True
        passed = matched if must_match else not matched
        return {
            "passed": passed,
            "explanation": "" if passed else f"'{field}' لا يطابق النمط المطلوب: {pattern}",
        }

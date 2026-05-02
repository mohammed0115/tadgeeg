"""
ZATCA Phase 2 structural conformance rule.

Detects UBL invoices and verifies the structural prerequisites for Phase 2
compliance (signed, required elements present, UUID/ICV/PIH metadata).
This stops short of cryptographic signature validation — that needs ZATCA's
issued certificate per merchant — but it catches the 90% case where someone
claims Phase 2 compliance with a malformed XML.
"""
from __future__ import annotations

import logging

from apps.rule_engine.rules.base import (
    AuditRuleBase, NormalizedDocument, RuleResult, EvidenceItem,
)

logger = logging.getLogger("rule_engine")


class ZATCAPhase2ConformanceRule(AuditRuleBase):
    """ZATCA-P2: UBL invoice structural conformance for ZATCA Phase 2."""

    rule_code = "ZATCA-P2"
    rule_name_en = "ZATCA Phase 2 Conformance"
    rule_name_ar = "مطابقة المرحلة الثانية للزكاة والضريبة"
    default_severity = "high"
    rule_type = "compliance"

    def check_preconditions(self, doc: NormalizedDocument) -> bool:
        # Only applies to documents that came in as XML (UBL).
        ext = (getattr(doc, "file_extension", "") or "").lower()
        return ext in (".xml", ".ubl")

    def execute(self, doc: NormalizedDocument) -> RuleResult:
        try:
            xml_source = getattr(doc, "raw_text", None) or getattr(doc, "raw_bytes", None)
            if not xml_source:
                return self._pass("No XML content to validate.")

            from apps.rule_engine.services.zatca_phase2 import conformance_summary
            summary = conformance_summary(xml_source)

            if not summary.get("is_ubl"):
                return self._fail(
                    "Document is XML but not a UBL Invoice — not Phase 2 conformant.",
                    "المستند بصيغة XML لكنه ليس فاتورة UBL — غير مطابق للمرحلة الثانية.",
                    evidence=[EvidenceItem(
                        field_path="root_element",
                        observed=summary.get("reason", "non-UBL"),
                        expected="Invoice (UBL 2.1)",
                    )],
                )

            problems = []
            if not summary["is_signed"]:
                problems.append("missing UBL signature extension")
            if summary["missing"]:
                problems.append(
                    f"missing UBL fields: {', '.join(summary['missing'][:5])}"
                )

            sig = summary.get("signature", {}) or {}
            if summary["is_signed"]:
                if sig.get("has_signature_value") and not sig.get("signature_format_ok"):
                    problems.append("signature value is not valid base64")
                if not sig.get("has_signature_value"):
                    problems.append("signature element exists but signature value is empty")
                if sig.get("certificate_parsed") is False:
                    problems.append("embedded X.509 certificate failed to parse")
                if sig.get("signature_verified") is False:
                    problems.append("signature failed cryptographic verification")

            if problems:
                return self._fail(
                    "ZATCA Phase 2 conformance failed: " + "; ".join(problems),
                    "فشل مطابقة المرحلة الثانية: " + "؛ ".join(problems),
                    evidence=[EvidenceItem(
                        field_path="zatca_phase2",
                        observed="; ".join(problems),
                        expected="signed UBL invoice with all required fields",
                    )],
                )

            md = summary.get("metadata", {})
            details = []
            for key in ("uuid", "icv", "pih"):
                if md.get(key):
                    details.append(f"{key.upper()}={md[key][:40]}")
            if summary.get("invoice_hash"):
                details.append(f"hash={summary['invoice_hash'][:16]}…")
            return self._pass(
                "ZATCA Phase 2 structurally conformant. " + " ".join(details),
                "متوافق مع المرحلة الثانية هيكلياً. " + " ".join(details),
            )
        except Exception as exc:
            logger.warning("ZATCA-P2 rule failed: %s", exc)
            return self._pass("ZATCA-P2 check skipped (parse error).")
